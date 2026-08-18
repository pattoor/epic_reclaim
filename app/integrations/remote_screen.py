from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class RemoteScreen(ABC):
    @abstractmethod
    def available(self) -> bool:
        pass

    @abstractmethod
    def diagnostics(self) -> dict:
        pass

    @abstractmethod
    def start(self, password: str) -> str | None:
        pass

    @abstractmethod
    def screen_url(self, token: str | None = None) -> str | None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass


class NoVNCProvider(RemoteScreen):
    """Runs Xvfb + x11vnc + websockify to expose a headed browser via noVNC.

    VNC is protected with a per-session password (never -nopw). websockify
    serves the noVNC web client from NOVNC_WEB_DIR (or the system path) so the
    dashboard can embed the remote browser page.
    """

    def __init__(
        self,
        display: str = ":99",
        vnc_port: int = 5900,
        ws_port: int = 6080,
        novnc_web_dir: str | None = None,
    ):
        self._display = display
        self._vnc_port = vnc_port
        self._ws_port = ws_port
        self._novnc_web_dir = novnc_web_dir or "/usr/share/novnc"
        self._processes: list[subprocess.Popen] = []
        self._passfile: Path | None = None
        self._last_error: str | None = None

    def diagnostics(self) -> dict:
        tools = ("Xvfb", "x11vnc", "websockify")
        tool_status = {tool: shutil.which(tool) is not None for tool in tools}
        novnc_exists = Path(self._novnc_web_dir).is_dir()
        return {
            "tools": tool_status,
            "novnc_web_dir": self._novnc_web_dir,
            "novnc_web_dir_exists": novnc_exists,
            "vnc_port": self._vnc_port,
            "ws_port": self._ws_port,
            "display": self._display,
            "last_error": self._last_error,
            "running": bool(self._processes),
        }

    def available(self) -> bool:
        tools = ("Xvfb", "x11vnc", "websockify")
        if not all(shutil.which(tool) for tool in tools):
            return False
        if not Path(self._novnc_web_dir).is_dir():
            return False
        return True

    def _port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return True
        return False

    def _check_processes_alive(self) -> tuple[bool, str | None]:
        for process, name in zip(self._processes, ("Xvfb", "x11vnc", "websockify")):
            if process.poll() is not None:
                return False, f"{name} exited with code {process.returncode}"
        return True, None

    def start(self, password: str) -> str | None:
        self._last_error = None
        if not self.available():
            self._last_error = self._format_unavailable_reason()
            logger.error("remote_screen_unavailable: %s", self._last_error)
            return None

        if self._port_in_use(self._vnc_port):
            self._last_error = f"VNC port {self._vnc_port} is already in use"
            logger.error(self._last_error)
            return None
        if self._port_in_use(self._ws_port):
            self._last_error = f"websockify port {self._ws_port} is already in use"
            logger.error(self._last_error)
            return None

        fd, passfile = tempfile.mkstemp(prefix="epic-reclaim-vnc-")
        os.close(fd)
        try:
            result = subprocess.run(
                ["x11vnc", "-storepasswd", password, passfile],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            self._last_error = f"x11vnc -storepasswd failed: {exc.stderr or 'unknown error'}"
            logger.exception("storepasswd_failed")
            try:
                os.unlink(passfile)
            except FileNotFoundError:
                pass
            return None
        self._passfile = Path(passfile)

        xvfb = subprocess.Popen(
            ["Xvfb", self._display, "-screen", "0", "1280x800x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        x11vnc = subprocess.Popen(
            [
                "x11vnc",
                "-display",
                self._display,
                "-rfbauth",
                passfile,
                "-localhost",
                "-forever",
                "-rfbport",
                str(self._vnc_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        websockify = subprocess.Popen(
            [
                "websockify",
                str(self._ws_port),
                f"localhost:{self._vnc_port}",
                "--web",
                self._novnc_web_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._processes = [xvfb, x11vnc, websockify]

        alive, error = self._check_processes_alive()
        if not alive:
            self._last_error = error
            logger.error("remote_screen_process_died: %s", error)
            self.stop()
            return None

        logger.info(
            "remote_screen_started",
            extra={
                "context": {
                    "display": self._display,
                    "vnc_port": self._vnc_port,
                    "ws_port": self._ws_port,
                }
            },
        )
        return self._display

    def _format_unavailable_reason(self) -> str:
        tools = ("Xvfb", "x11vnc", "websockify")
        missing = [tool for tool in tools if not shutil.which(tool)]
        if missing:
            return f"missing tools: {', '.join(missing)}"
        if not Path(self._novnc_web_dir).is_dir():
            return f"noVNC web dir not found: {self._novnc_web_dir}"
        return "remote screen not available"

    def screen_url(self, token: str | None = None) -> str | None:
        if not self._processes:
            return None
        alive, error = self._check_processes_alive()
        if not alive:
            self._last_error = error
            return None
        token = token or ""
        return f"/auth-screen?token={token}&port={self._ws_port}"

    def stop(self) -> None:
        for process in self._processes:
            try:
                process.terminate()
            except Exception:
                pass
        self._processes = []
        if self._passfile is not None:
            try:
                self._passfile.unlink()
            except FileNotFoundError:
                pass
            self._passfile = None
