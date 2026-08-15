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
    status: str  # running | completed | failed | unavailable
    error: str | None = None


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

    def start(self, account_id: int) -> AuthSession:
        with self._database.connect() as connection:
            self._repository.get(connection, account_id)

        if not self._screen.available():
            return AuthSession(
                token="",
                account_id=account_id,
                screen_url=None,
                status="unavailable",
                error="remote screen not available",
            )

        display = self._screen.start()
        session = AuthSession(
            token=secrets.token_urlsafe(24),
            account_id=account_id,
            screen_url=self._screen.screen_url(),
            status="running",
        )
        self._sessions[session.token] = session
        thread = threading.Thread(
            target=self._run_browser, args=(session, display), daemon=True
        )
        thread.start()
        return session

    def _run_browser(self, session: AuthSession, display: str | None) -> None:
        try:
            with self._database.connect() as connection:
                account = self._repository.get(connection, session.account_id)
                profile_path = str(self._sessions_path / str(account.id))
                outcome = self._browser.run_auth(
                    profile_path=profile_path,
                    display=display,
                    timeout_seconds=self._auth_timeout_seconds,
                )
                self._complete(session, outcome)
        except Exception as exc:  # pragma: no cover - defensive
            session.status = "failed"
            session.error = str(exc)
            self._revoke(session.token)

    def _complete(self, session: AuthSession, outcome) -> None:
        with self._database.connect() as connection:
            if outcome.success:
                self._repository.update(
                    connection,
                    session.account_id,
                    state=AccountState.ACTIVE,
                    epic_identity=outcome.epic_identity,
                    display_name=outcome.display_name,
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
        self._revoke(session.token)

    def get(self, token: str) -> AuthSession | None:
        return self._sessions.get(token)

    def revoke(self, token: str) -> None:
        self._revoke(token)

    def _revoke(self, token: str) -> None:
        session = self._sessions.pop(token, None)
        if session is not None:
            self._screen.stop()

    def close_all(self) -> None:
        for token in list(self._sessions):
            self._revoke(token)
