from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import AccountState
from app.integrations.auth_browser import InteractiveAuthBrowser
from app.integrations.remote_screen import RemoteScreen
from app.repositories import AccountsRepository


@dataclass
class AuthSession:
    token: str
    account_id: int
    screen_url: str | None
    status: str  # running | needs_intervention | completed | failed | unavailable
    error: str | None = None
    vnc_password: str | None = None


class AuthService:
    def __init__(
        self,
        database,
        repository: AccountsRepository,
        browser: InteractiveAuthBrowser,
        screen: RemoteScreen,
        sessions_path: str,
        auth_timeout_seconds: int = 900,
    ):
        self._database = database
        self._repository = repository
        self._browser = browser
        self._screen = screen
        self._sessions_path = Path(sessions_path)
        self._auth_timeout_seconds = auth_timeout_seconds
        self._sessions: dict[str, AuthSession] = {}
        self._stop_events: dict[str, threading.Event] = {}

    def start(self, account_id: int) -> AuthSession:
        with self._database.connect() as connection:
            self._repository.get(connection, account_id)

        if any(session.status in {"running", "needs_intervention"} for session in self._sessions.values()):
            return AuthSession(
                token="",
                account_id=account_id,
                screen_url=None,
                status="failed",
                error="an authentication flow is already running for this account",
            )

        if not self._screen.available():
            diagnostics = self._screen.diagnostics()
            missing = [tool for tool, present in diagnostics.get("tools", {}).items() if not present]
            if missing:
                reason = f"missing remote screen tools: {', '.join(missing)}"
            elif not diagnostics.get("novnc_web_dir_exists", True):
                reason = f"noVNC web directory not found: {diagnostics.get('novnc_web_dir')}"
            else:
                reason = "remote screen not available"
            return AuthSession(
                token="",
                account_id=account_id,
                screen_url=None,
                status="unavailable",
                error=reason,
            )

        vnc_password = secrets.token_urlsafe(16)
        display = self._screen.start(vnc_password)
        if display is None:
            diagnostics = self._screen.diagnostics()
            last_error = diagnostics.get("last_error") or "remote screen failed to start"
            return AuthSession(
                token="",
                account_id=account_id,
                screen_url=None,
                status="unavailable",
                error=last_error,
            )
        token = secrets.token_urlsafe(24)
        stop_event = threading.Event()
        session = AuthSession(
            token=token,
            account_id=account_id,
            # The ephemeral VNC password AND the token gate the remote screen;
            # never expose them in logs or events.
            screen_url=self._screen.screen_url(token, vnc_password),
            status="running",
            vnc_password=vnc_password,
        )
        self._sessions[session.token] = session
        self._stop_events[session.token] = stop_event
        thread = threading.Thread(
            target=self._run_browser, args=(session, display, stop_event), daemon=True
        )
        thread.start()
        return session

    def _run_browser(
        self,
        session: AuthSession,
        display: str | None,
        stop_event: threading.Event,
    ) -> None:
        try:
            with self._database.connect() as connection:
                account = self._repository.get(connection, session.account_id)
                profile_path = str(self._sessions_path / str(account.id))
                outcome = self._browser.run_auth(
                    profile_path=profile_path,
                    display=display,
                    timeout_seconds=self._auth_timeout_seconds,
                    on_intervention=lambda reason: self._mark_intervention(session, reason),
                    should_stop=stop_event.is_set,
                )
                self._complete(session, outcome)
        except Exception as exc:  # pragma: no cover - defensive
            session.status = "failed"
            session.error = str(exc)
            self._screen.stop()

    def _mark_intervention(self, session: AuthSession, reason: str) -> None:
        session.status = "needs_intervention"
        session.error = reason
        with self._database.connect() as connection:
            self._repository.update(
                connection,
                session.account_id,
                state=AccountState.NEEDS_INTERVENTION,
                last_block_reason=reason,
            )

    def _complete(self, session: AuthSession, outcome) -> None:
        try:
            with self._database.connect() as connection:
                account = self._repository.get(connection, session.account_id)
                if outcome.success:
                    display_name = outcome.display_name or account.display_name
                    self._repository.update(
                        connection,
                        session.account_id,
                        state=AccountState.ACTIVE,
                        epic_identity=outcome.epic_identity,
                        display_name=display_name,
                        last_block_reason=None,
                    )
                    session.status = "completed"
                elif outcome.needs_intervention:
                    self._repository.update(
                        connection,
                        session.account_id,
                        state=AccountState.NEEDS_INTERVENTION,
                        last_block_reason=outcome.error,
                    )
                    session.status = "completed"
                    session.error = outcome.error
                else:
                    self._repository.update(
                        connection,
                        session.account_id,
                        state=AccountState.NEEDS_AUTHENTICATION,
                        last_block_reason=outcome.error,
                    )
                    session.status = "completed"
                    session.error = outcome.error
        finally:
            self._screen.stop()

    def get(self, token: str) -> AuthSession | None:
        return self._sessions.get(token)

    def revoke(self, token: str) -> None:
        self._revoke(token)

    def revoke_account(self, account_id: int) -> None:
        for token, session in list(self._sessions.items()):
            if session.account_id == account_id:
                self._revoke(token)

    def _revoke(self, token: str) -> None:
        session = self._sessions.pop(token, None)
        event = self._stop_events.pop(token, None)
        if event is not None:
            event.set()
        if session is not None:
            self._screen.stop()

    def close_all(self) -> None:
        for token in list(self._sessions):
            self._revoke(token)
