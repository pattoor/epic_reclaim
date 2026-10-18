from dataclasses import dataclass
import threading

from app.integrations.auth_browser import AuthOutcome, InteractiveAuthBrowser
from app.integrations.remote_screen import RemoteScreen


class FakeAuthBrowser(InteractiveAuthBrowser):
    def __init__(self, outcome: AuthOutcome):
        self.outcome = outcome
        self.calls = 0
        self.profile_path = None
        self.display = None

    def run_auth(
        self,
        profile_path: str,
        display: str | None,
        timeout_seconds: int,
        on_intervention=None,
        should_stop=None,
    ) -> AuthOutcome:
        self.calls += 1
        self.profile_path = profile_path
        self.display = display
        return self.outcome


class FakeScreen(RemoteScreen):
    ws_port = 6080

    def __init__(self, available: bool = True):
        self._available = available
        self.started = False
        self.stopped = False
        self.password = None
        self._diagnostics = {"running": False}

    def available(self) -> bool:
        return self._available

    def diagnostics(self) -> dict:
        diagnostics = dict(self._diagnostics)
        diagnostics.setdefault("tools", {})
        diagnostics.setdefault("novnc_web_dir_exists", True)
        return diagnostics

    def start(self, password: str) -> str | None:
        self.started = True
        self.password = password
        return ":99" if self._available else None

    def screen_url(self, token: str | None = None, password: str | None = None) -> str | None:
        if not self._available:
            return None
        host = "127.0.0.1"
        return (
            f"http://{host}:6080/vnc.html?host={host}&port=6080"
            f"&password={password or ''}&autoconnect=1"
        )

    def stop(self) -> None:
        self.stopped = True


class BlockingAuthBrowser(InteractiveAuthBrowser):
    def __init__(self):
        self.release = threading.Event()

    def run_auth(
        self,
        profile_path: str,
        display: str | None,
        timeout_seconds: int,
        on_intervention=None,
        should_stop=None,
    ) -> AuthOutcome:
        if on_intervention is not None:
            on_intervention("captcha")
        self.release.wait(timeout=5)
        return AuthOutcome(success=True, epic_identity="id-after-intervention")
