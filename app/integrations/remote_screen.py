from __future__ import annotations

import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class RemoteScreen(ABC):
    @abstractmethod
    def available(self) -> bool:
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

    def available(self) -> bool:
        tools = ("Xvfb", "x11vnc", "websockify")
        if not all(shutil.which(tool) for tool in tools):
            return False
        if not Path(self._novnc_web_dir).is_dir():
            return False
        return True

    def start(self, password: str) -> str | None:
        if not self.available():
            return None

        fd, passfile = tempfile.mkstemp(prefix="epic-reclaim-vnc-")
        with Path(passfile).open("w") as handle:
            handle.write(password)
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
        return self._display

    def screen_url(self, token: str | None = None) -> str | None:
        if not self._processes:
            return None
        token = token or ""
        return f"/auth-screen?token={token}&port={self._ws_port}"

    def stop(self) -> None:
        for process in self._processes:
            process.terminate()
        self._processes = []
        if self._passfile is not None:
            try:
                self._passfile.unlink()
            except FileNotFoundError:
                pass
            self._passfile = None
