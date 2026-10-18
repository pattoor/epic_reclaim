from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class RemoteScreen(ABC):
    ws_port: int = 6080

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
    def screen_url(self, token: str | None = None, password: str | None = None) -> str | None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass


class LocalHeadedScreen(RemoteScreen):
    """No remote screen: the headed browser shows on the local machine.

    Used on GUI development machines (e.g. Windows) where the user watches
    the Chromium window directly and no VNC layer is needed.
    """

    ws_port = 0

    def available(self) -> bool:
        return True

    def diagnostics(self) -> dict:
        return {"mode": "local-headed", "tools": {}, "running": False}

    def start(self, password: str) -> str:
        # Empty string is truthy-checked via `is None` in auth service.
        return ""

    def screen_url(self, token: str | None = None, password: str | None = None) -> None:
        return None

    def stop(self) -> None:
        pass


class NoVNCProvider(RemoteScreen):
    """Runs Xvnc (TigerVNC: X server + VNC server in one process) + websockify.

    x11vnc was replaced after live validation showed it entering a userspace
    busy-loop on Debian 13 (never accept()ing connections, browser stuck on
    "connecting"); Xvnc answers the RFB banner immediately (DECISIONS D9).

    VNC is protected with a per-session password (never no auth). websockify
    serves the noVNC web client from NOVNC_WEB_DIR (or the system path) and
    the stack runs standalone: the client connects directly to the published
    websockify port, never through a proxy inside this application.
    """

    def __init__(
        self,
        display: str = ":99",
        vnc_port: int = 5900,
        ws_port: int = 6080,
        novnc_web_dir: str | None = None,
        public_host: str = "",
        startup_timeout_seconds: float = 10.0,
        startup_poll_interval: float = 0.2,
    ):
        self._display = display
        self._vnc_port = vnc_port
        self._ws_port = ws_port
        self._novnc_web_dir = novnc_web_dir or "/usr/share/novnc"
        self._public_host = (public_host or "").strip()
        self._startup_timeout_seconds = startup_timeout_seconds
        self._startup_poll_interval = startup_poll_interval
        self._processes: list[subprocess.Popen] = []
        self._stderrs: list[subprocess.Popen] = []
        self._passfile: Path | None = None
        self._last_error: str | None = None

    def _write_passfile(self, password: str, passfile: str) -> None:
        """Write an 8-byte obfuscated VNC password file (libvncserver format).

        Debian 13 dropped the `vncpasswd` utility, so the obfuscated password
        is produced with `openssl`: key = first 8 password bytes with every
        bit reversed, encrypting 8 zero bytes in DES-ECB with no padding
        (exactly what vncpasswd -f produces). Cross-checked against
        pycryptodome. Falls back to the legacy provider for OpenSSL 3.
        """
        key = bytearray(password.encode("utf-8")[:8].ljust(8, b"\x00"))
        for index, byte in enumerate(key):
            reversed_bits = 0
            for _ in range(8):
                reversed_bits = (reversed_bits << 1) | (byte & 1)
                byte >>= 1
            key[index] = reversed_bits

        command = ["openssl", "enc", "-des-ecb", "-K", bytes(key).hex().upper(), "-nopad"]
        result = subprocess.run(command, input=b"\x00" * 8, capture_output=True)
        if not result.stdout or len(result.stdout) != 8:
            result = subprocess.run(
                command + ["-provider", "legacy", "-provider", "default"],
                input=b"\x00" * 8,
                capture_output=True,
            )
        if len(result.stdout) != 8:
            stderr = result.stderr.decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"openssl des-ecb failed: {stderr or 'no output'}")
        Path(passfile).write_bytes(result.stdout)

    def diagnostics(self) -> dict:
        tools = ("Xvnc", "openssl", "websockify")
        tool_status = {tool: shutil.which(tool) is not None for tool in tools}
        novnc_exists = Path(self._novnc_web_dir).is_dir()
        alive, error = self._check_processes_alive()
        vnc_listening = self._port_is_listening(self._vnc_port)
        ws_listening = self._port_is_listening(self._ws_port)
        return {
            "tools": tool_status,
            "novnc_web_dir": self._novnc_web_dir,
            "novnc_web_dir_exists": novnc_exists,
            "vnc_port": self._vnc_port,
            "ws_port": self._ws_port,
            "display": self._display,
            "processes_alive": alive,
            "processes_alive_error": error,
            "vnc_listening": vnc_listening,
            "ws_listening": ws_listening,
            "last_error": self._last_error,
            "running": bool(self._processes),
        }

    def available(self) -> bool:
        tools = ("Xvnc", "openssl", "websockify")
        if not all(shutil.which(tool) for tool in tools):
            return False
        if not Path(self._novnc_web_dir).is_dir():
            return False
        return True

    def _terminate_stale_processes(self) -> None:
        """Kill leftover Xvnc/websockify (and pre-migration Xvfb/x11vnc).

        In the single-purpose container only this application owns these
        tools; killing by name keeps the ports reusable after a crash or a
        killed exec session. Harmless no-op outside Linux.
        """
        if not (shutil.which("pkill") and shutil.which("ps")):
            return
        for pattern in ("Xvnc", "Xvfb", "x11vnc", "websockify"):
            try:
                subprocess.run(
                    ["pkill", "-f", pattern],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except OSError:  # pragma: no cover - defensive
                continue
        # A crashed X server leaves its lock/socket behind; the next start
        # would die with "Server is already active for display".
        try:
            display_number = self._display.lstrip(":").split(".")[0]
            for stale in (
                f"/tmp/.X{display_number}-lock",
                f"/tmp/.X{display_number}-sock",
                f"/tmp/.X11-unix/X{display_number}",
            ):
                Path(stale).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive
            pass
        # give the kernel a beat to release the listening sockets
        try:
            time.sleep(0.3)
        except Exception:  # pragma: no cover
            pass

    def _port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return True
        return False

    def _port_is_listening(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _wait_for_port(self, port: int, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._port_is_listening(port):
                return True
            time.sleep(self._startup_poll_interval)
        return False

    def _check_processes_alive(self) -> tuple[bool, str | None]:
        for process, name in zip(self._processes, ("Xvnc", "websockify")):
            if process.poll() is not None:
                stderr = self._read_stderr(process)
                detail = f"stderr: {stderr}" if stderr else f"exit code {process.returncode}"
                return False, f"{name} died ({detail})"
        return True, None

    def _read_stderr(self, process: subprocess.Popen) -> str:
        if process.stderr is None:
            return ""
        try:
            data = process.stderr.read()
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")[:500]
            return str(data)[:500]
        except Exception:
            return ""

    def _collect_stderrs(self) -> list[str]:
        return [self._read_stderr(p) for p in self._processes if p.stderr is not None]

    def start(self, password: str) -> str | None:
        self._last_error = None
        if not self.available():
            self._last_error = self._format_unavailable_reason()
            logger.error("remote_screen_unavailable: %s", self._last_error)
            return None

        for port_name, port in (("VNC", self._vnc_port), ("websockify", self._ws_port)):
            if self._port_in_use(port):
                self._terminate_stale_processes()
                break
        if self._port_in_use(self._vnc_port):
            self._last_error = f"VNC port {self._vnc_port} is already in use"
            logger.error(self._last_error)
            return None
        if self._port_in_use(self._ws_port):
            self._last_error = f"websockify port {self._ws_port} is already in use"
            logger.error(self._last_error)
            return None
        if not self._public_host:
            # Container deployments MUST set PUBLIC_HOST: without it the URL
            # is only reachable from inside the container.
            logger.warning(
                "public_host_unset: the returned screen URL will only be "
                "usable from inside the container (set PUBLIC_HOST)"
            )

        fd, passfile = tempfile.mkstemp(prefix="epic-reclaim-vnc-")
        os.close(fd)
        try:
            self._write_passfile(password, passfile)
        except Exception as exc:
            self._last_error = f"could not create VNC password file: {exc}"
            logger.exception("storepasswd_failed")
            try:
                os.unlink(passfile)
            except FileNotFoundError:
                pass
            return None
        self._passfile = Path(passfile)

        xvnc = subprocess.Popen(
            [
                "Xvnc",
                self._display,
                "-geometry",
                "1280x800",
                "-depth",
                "24",
                "-rfbport",
                str(self._vnc_port),
                "-PasswordFile",
                passfile,
                "-localhost",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        websockify = subprocess.Popen(
            [
                "websockify",
                "--web",
                self._novnc_web_dir,
                str(self._ws_port),
                f"127.0.0.1:{self._vnc_port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._processes = [xvnc, websockify]

        alive, error = self._check_processes_alive()
        if not alive:
            self._last_error = error
            logger.error("remote_screen_process_died: %s", error)
            self.stop()
            return None

        if not self._wait_for_port(self._vnc_port, self._startup_timeout_seconds):
            self._last_error = f"Xvnc did not start listening on port {self._vnc_port}; stderr: {self._collect_stderrs()}"
            logger.error(self._last_error)
            self.stop()
            return None

        if not self._wait_for_port(self._ws_port, self._startup_timeout_seconds):
            self._last_error = f"websockify did not start listening on port {self._ws_port}; stderr: {self._collect_stderrs()}"
            logger.error(self._last_error)
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
        tools = ("Xvnc", "openssl", "websockify")
        missing = [tool for tool in tools if not shutil.which(tool)]
        if missing:
            return f"missing tools: {', '.join(missing)}"
        if not Path(self._novnc_web_dir).is_dir():
            return f"noVNC web dir not found: {self._novnc_web_dir}"
        return "remote screen not available"

    def screen_url(self, token: str | None = None, password: str | None = None) -> str | None:
        """Full URL for a one-use interactive session.

        The token is informational ( Logs/identification only); the real gate
        is the ephemeral VNC password which is regenerated per session and
        bound to the started Xvnc server. No cookies, CDP or the persistent
        profile are ever exposed through this URL.
        """
        if not self._processes:
            return None
        alive, error = self._check_processes_alive()
        if not alive:
            self._last_error = error
            return None
        host = self._public_host or "127.0.0.1"
        query = (
            f"host={host}&port={self._ws_port}&password={password or ''}"
            "&autoconnect=1&bell=off&show_dot=1"
        )
        return f"http://{host}:{self._ws_port}/vnc.html?{query}"

    def stop(self) -> None:
        for process in self._processes:
            try:
                process.terminate()
            except Exception:
                pass
        self._processes = []
        # Xvnc leaves a display lock/socket behind; remove it so the next
        # start (possibly after a hard kill of this process) does not die
        # with "Server is already active for display".
        try:
            display_number = self._display.lstrip(":").split(".")[0]
            for stale in (
                f"/tmp/.X{display_number}-lock",
                f"/tmp/.X{display_number}-sock",
                f"/tmp/.X11-unix/X{display_number}",
            ):
                Path(stale).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive
            pass
        if self._passfile is not None:
            try:
                self._passfile.unlink()
            except FileNotFoundError:
                pass
            self._passfile = None


def create_default_screen(settings) -> RemoteScreen:
    """Pick the remote-screen implementation fitting the environment.

    Linux servers (the g7 Docker deployment) use the standalone
    Xvnc+websockify/noVNC stack; GUI machines (Windows/macOS desktops) show
    the headed browser locally instead, avoiding a VNC layer during
    development.
    """
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return LocalHeadedScreen()
    if not os.environ.get("DISPLAY") and shutil.which("Xvnc") is not None:
        # Headless Linux server: NoVNCProvider works fine without DISPLAY.
        pass
    return NoVNCProvider(
        ws_port=settings.no_vnc_port,
        public_host=settings.public_host,
    )
