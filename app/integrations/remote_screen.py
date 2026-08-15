from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod


class RemoteScreen(ABC):
    @abstractmethod
    def available(self) -> bool:
        pass

    @abstractmethod
    def start(self) -> str | None:
        pass

    @abstractmethod
    def screen_url(self) -> str | None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass


class UnavailableRemoteScreen(RemoteScreen):
    def available(self) -> bool:
        return False

    def start(self) -> str | None:
        return None

    def screen_url(self) -> str | None:
        return None

    def stop(self) -> None:
        pass


class NoVNCProvider(RemoteScreen):
    """Runs Xvfb + x11vnc + websockify to expose a headed browser via noVNC."""

    def __init__(self, display: str = ":99", vnc_port: int = 5900, ws_port: int = 6080):
        self._display = display
        self._vnc_port = vnc_port
        self._ws_port = ws_port
        self._processes: list[subprocess.Popen] = []

    def available(self) -> bool:
        return all(shutil.which(tool) for tool in ("Xvfb", "x11vnc", "websockify"))

    def start(self) -> str | None:
        if not self.available():
            return None
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
                "-nopw",
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
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._processes = [xvfb, x11vnc, websockify]
        return self._display

    def screen_url(self) -> str | None:
        if not self._processes:
            return None
        return f"/auth-screen?token=one-time-token&port={self._ws_port}"

    def stop(self) -> None:
        for process in self._processes:
            process.terminate()
        self._processes = []
