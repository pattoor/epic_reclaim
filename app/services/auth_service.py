from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import AccountState
from app.integrations import epic_oauth
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
    # Device/code mode (D10): the login page the user opens from any device.
    auth_url: str | None = None


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

    def start(self, account_id: int, mode: str = "screen") -> AuthSession:
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

        if mode == "device":
            return self._start_device(account_id)
        if mode == "local":
            return self._start_local(account_id)
        return self._start_screen(account_id)

    def _start_screen(self, account_id: int) -> AuthSession:
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

    def _start_device(self, account_id: int) -> AuthSession:
        # No screen: the login happens on the user's own device; the code
        # exchange and SSO settle run in a headless browser.
        session = AuthSession(
            token=secrets.token_urlsafe(24),
            account_id=account_id,
            screen_url=None,
            status="running",
            auth_url=epic_oauth.auth_page_url(),
        )
        self._sessions[session.token] = session
        self._stop_events[session.token] = threading.Event()
        return session

    def submit_code(self, token: str, code: str) -> AuthSession | None:
        """Exchange the user-provided authorization code (device mode, D10)."""
        session = self._sessions.get(token)
        if session is None or session.auth_url is None:
            return None
        try:
            tokens = epic_oauth.exchange_authorization_code(code)
        except epic_oauth.EpicOAuthError as exc:
            # Keep the session running so the user can retry the code.
            session.error = str(exc)
            return session
        epic_oauth.save_session_tokens(self._profile_path(session.account_id), tokens)
        stop_event = self._stop_events[session.token]
        session.status = "running"
        session.error = None
        thread = threading.Thread(
            target=self._run_exchange, args=(session, tokens, stop_event), daemon=True
        )
        thread.start()
        return session

    def silent_restore(self, account_id: int) -> bool:
        """Try to restore the profile session from the stored refresh token.

        Returns False when there is nothing stored, a flow is already
        running, or Epic rejects the token; never raises.
        """
        if any(session.status in {"running", "needs_intervention"} for session in self._sessions.values()):
            return False
        profile_path = str(self._sessions_path / str(account_id))
        refresh_token = epic_oauth.load_refresh_token(profile_path)
        if not refresh_token:
            return False
        try:
            tokens = epic_oauth.refresh_tokens(refresh_token)
            epic_oauth.save_session_tokens(profile_path, tokens)
            exchange_code = epic_oauth.create_exchange_code(tokens["access_token"])
        except epic_oauth.EpicOAuthError:
            return False
        outcome = self._browser.run_auth(
            profile_path=profile_path,
            display=None,
            timeout_seconds=120,
            start_url=epic_oauth.web_exchange_url(exchange_code),
            headless=True,
        )
        if not outcome.success:
            return False
        with self._database.connect() as connection:
            self._repository.update(
                connection,
                account_id,
                state=AccountState.ACTIVE,
                epic_identity=tokens.get("account_id"),
                display_name=tokens.get("display_name"),
                last_block_reason=None,
            )
        return True

    def _profile_path(self, account_id: int) -> str:
        return str(self._sessions_path / str(account_id))

    def _run_browser(
        self,
        session: AuthSession,
        display: str | None,
        stop_event: threading.Event,
    ) -> None:
        try:
            with self._database.connect() as connection:
                account = self._repository.get(connection, session.account_id)
                outcome = self._browser.run_auth(
                    profile_path=self._profile_path(account.id),
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

    def _run_exchange(self, session: AuthSession, tokens: dict, stop_event: threading.Event) -> None:
        try:
            exchange_code = epic_oauth.create_exchange_code(tokens["access_token"])
            outcome = self._browser.run_auth(
                profile_path=self._profile_path(session.account_id),
                display=None,
                timeout_seconds=120,
                on_intervention=lambda reason: self._mark_intervention(session, reason),
                should_stop=stop_event.is_set,
                start_url=epic_oauth.web_exchange_url(exchange_code),
                headless=True,
            )
            self._complete(
                session,
                outcome,
                identity=tokens.get("account_id"),
                display_name=tokens.get("display_name"),
            )
        except epic_oauth.EpicOAuthError as exc:
            session.status = "failed"
            session.error = str(exc)

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

    def _complete(self, session: AuthSession, outcome, identity: str | None = None, display_name: str | None = None) -> None:
        try:
            with self._database.connect() as connection:
                account = self._repository.get(connection, session.account_id)
                if outcome.success:
                    self._repository.update(
                        connection,
                        session.account_id,
                        state=AccountState.ACTIVE,
                        epic_identity=identity or outcome.epic_identity,
                        display_name=display_name or outcome.display_name or account.display_name,
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
