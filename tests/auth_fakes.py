from dataclasses import dataclass

from app.integrations.auth_browser import AuthOutcome, InteractiveAuthBrowser
from app.integrations.remote_screen import RemoteScreen


class FakeAuthBrowser(InteractiveAuthBrowser):
    def __init__(self, outcome: AuthOutcome):
        self.outcome = outcome
        self.calls = 0
        self.profile_path = None
        self.display = None

    def run_auth(self, profile_path: str, display: str | None, timeout_seconds: int) -> AuthOutcome:
        self.calls += 1
        self.profile_path = profile_path
        self.display = display
        return self.outcome


class FakeScreen(RemoteScreen):
    def __init__(self, available: bool = True):
        self._available = available
        self.started = False
        self.stopped = False
        self.password = None

    def available(self) -> bool:
        return self._available

    def start(self, password: str) -> str | None:
        self.started = True
        self.password = password
        return ":99" if self._available else None

    def screen_url(self, token: str | None = None) -> str | None:
        return f"/auth-screen?token={token or ''}" if self._available else None

    def stop(self) -> None:
        self.stopped = True
