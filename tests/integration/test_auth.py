import threading
import time

from app.database import Database
from app.domain.models import AccountState
from app.integrations import epic_oauth
from app.integrations.auth_browser import AuthOutcome
from app.repositories import AccountsRepository
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from tests.auth_fakes import BlockingAuthBrowser, FakeAuthBrowser, FakeScreen


def _database(tmp_path) -> Database:
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    return database


def test_account_service_create_list_update_delete(tmp_path):
    database = _database(tmp_path)
    service = AccountService(AccountsRepository())
    with database.connect() as connection:
        account = service.create(connection, "Personal")
        assert account.state == AccountState.NEEDS_AUTHENTICATION

        service.set_enabled(connection, account.id, False)
        service.set_state(connection, account.id, AccountState.ACTIVE)
        assert service.get(connection, account.id).state == AccountState.ACTIVE

        assert len(service.list(connection)) == 1
        service.delete(connection, account.id)
        assert service.list(connection) == []


def test_account_service_resolve_intervention(tmp_path):
    database = _database(tmp_path)
    service = AccountService(AccountsRepository())
    with database.connect() as connection:
        account = service.create(connection, "A")
        service.set_state(connection, account.id, AccountState.NEEDS_INTERVENTION)
        resolved = service.resolve_intervention(connection, account.id)
        assert resolved.state == AccountState.ACTIVE
        assert resolved.last_block_reason is None


def test_auth_success_activates_account(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(
            AuthOutcome(success=True, epic_identity="id-1", display_name="Epic User")
        ),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    assert session.status == "running"
    assert session.screen_url.startswith("http://127.0.0.1:6080/vnc.html?")

    _wait(lambda: session.status != "running")
    assert session.status == "completed"

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.ACTIVE
    assert stored.epic_identity == "id-1"
    assert stored.display_name == "Epic User"


def test_auth_intervention_sets_needs_intervention(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=False, needs_intervention=True, error="captcha")),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    _wait(lambda: session.status != "running")

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.NEEDS_INTERVENTION
    assert stored.last_block_reason == "captcha"


def test_auth_failure_sets_needs_authentication(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=False, error="auth timeout")),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    _wait(lambda: session.status != "running")

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.NEEDS_AUTHENTICATION


def test_auth_unavailable_when_no_remote_screen(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FakeScreen(available=False),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    assert session.status == "unavailable"
    assert session.token == ""
    assert session.error is not None


def test_auth_reports_failure_when_screen_start_returns_none(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    class FailingStartScreen(FakeScreen):
        def __init__(self):
            super().__init__(available=True)
            self._diagnostics["last_error"] = "port 6080 is already in use"

        def start(self, password: str) -> str | None:
            return None

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FailingStartScreen(),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    assert session.status == "unavailable"
    assert "port 6080" in (session.error or "")


def test_auth_rejects_second_concurrent_flow_for_account(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    browser = FakeAuthBrowser(AuthOutcome(success=True))
    screen = FakeScreen(available=True)
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=browser,
        screen=screen,
        sessions_path=str(tmp_path / "sessions"),
    )
    first = auth.start(account.id)
    assert first.status == "running"

    second = auth.start(account.id)
    assert second.status == "failed"
    assert "already running" in (second.error or "")


def test_auth_success_preserves_display_name_when_not_extracted(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Mi cuenta")

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(
            AuthOutcome(success=True, epic_identity="id-9", display_name=None)
        ),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    _wait(lambda: session.status != "running")

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.ACTIVE
    assert stored.display_name == "Mi cuenta"
    assert stored.epic_identity == "id-9"


def test_auth_screen_uses_session_vnc_password(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    screen = FakeScreen(available=True)
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=screen,
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    assert session.vnc_password is not None
    assert screen.password == session.vnc_password


def test_auth_intervention_keeps_browser_and_session_until_resolution(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    browser = BlockingAuthBrowser()
    screen = FakeScreen(available=True)
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=browser,
        screen=screen,
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id)
    _wait(lambda: session.status == "needs_intervention")

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.NEEDS_INTERVENTION
    assert screen.stopped is False
    assert auth.get(session.token) is session

    browser.release.set()
    _wait(lambda: session.status == "completed")
    assert auth.get(session.token) is session
    auth.revoke(session.token)
    assert screen.stopped is True


def _wait(predicate, timeout_seconds: float = 5):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached within timeout")


# --- Device code flow (D10) ---


def test_auth_device_mode_starts_without_screen(tmp_path, monkeypatch):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    screen = FakeScreen(available=True)
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=screen,
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id, mode="device")

    assert session.status == "running"
    assert session.screen_url is None
    assert session.auth_url is not None
    assert "id/login" in session.auth_url
    assert screen.started is False
    auth.revoke(session.token)


def test_auth_device_mode_completes_via_code(tmp_path, monkeypatch):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    sessions_dir = tmp_path / "sessions"

    def fake_exchange_code(code):
        # The CLI/API accept the whole raw JSON the launcher redirect shows.
        assert code == "ONE-TIME-CODE"
        return {"access_token": "at", "refresh_token": "re", "account_id": "acct-9", "display_name": "Epic User"}

    def fake_exchange_code_from_token(access_token):
        assert access_token == "at"
        return "web-exchange-code"

    monkeypatch.setattr(
        "app.integrations.epic_oauth.exchange_authorization_code", fake_exchange_code
    )
    monkeypatch.setattr(
        "app.integrations.epic_oauth.create_exchange_code",
        fake_exchange_code_from_token,
    )

    browser = FakeAuthBrowser(AuthOutcome(success=True))
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=browser,
        screen=FakeScreen(available=False),
        sessions_path=str(sessions_dir),
    )
    session = auth.start(account.id, mode="device")
    raw_json = (
        '{"warning":"Do not share this code with any 3rd party service.",'
        '"redirectUrl":"https://localhost/launcher/authorized?code=ONE-TIME-CODE",'
        '"authorizationCode":"ONE-TIME-CODE","exchangeCode":null,"sid":null}'
    )
    updated = auth.submit_code(session.token, raw_json)

    assert updated.status == "running"
    _wait(lambda: updated.status == "completed")

    assert browser.start_url is not None
    assert "id/exchange" in browser.start_url
    assert browser.headless is True
    assert browser.display is None

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.ACTIVE
    assert stored.epic_identity == "acct-9"
    assert stored.display_name == "Epic User"
    # The refresh token is stored next to the profile for future silent restores.
    stored_token = epic_oauth.load_refresh_token(str(sessions_dir / str(account.id)))
    assert stored_token == "re"


def test_auth_device_mode_rejects_bad_code_and_allows_retry(tmp_path, monkeypatch):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    attempts = []

    def fake_exchange_code(code):
        attempts.append(code)
        if len(attempts) == 1:
            raise epic_oauth.EpicOAuthError("invalid authorization code")
        return {"access_token": "at", "refresh_token": "re", "account_id": "a", "display_name": "U"}

    monkeypatch.setattr(
        "app.integrations.epic_oauth.exchange_authorization_code", fake_exchange_code
    )
    monkeypatch.setattr(
        "app.integrations.epic_oauth.create_exchange_code", lambda access_token: "exch"
    )

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    session = auth.start(account.id, mode="device")
    rejected = auth.submit_code(session.token, "bad-code")

    assert rejected.status == "running"
    assert "invalid authorization code" in (rejected.error or "")

    accepted = auth.submit_code(session.token, "good-code")
    assert accepted.status == "running"
    assert accepted.error is None
    _wait(lambda: accepted.status == "completed")
    auth._revoke(session.token)


def test_submit_code_unknown_token_returns_none(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    assert auth.submit_code("no-such-token", "123") is None


# --- Silent restore from stored refresh token (D10) ---


def test_silent_restore_activates_account_without_user(tmp_path, monkeypatch):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    sessions_dir = tmp_path / "sessions"
    profile = str(sessions_dir / str(account.id))
    epic_oauth.save_session_tokens(
        profile, {"refresh_token": "re", "account_id": "acct-5", "display_name": "Epic User"}
    )

    def fake_refresh(token):
        assert token == "re"
        return {"access_token": "at2", "refresh_token": "re2", "account_id": "acct-5", "display_name": "Epic User"}

    monkeypatch.setattr("app.integrations.epic_oauth.refresh_tokens", fake_refresh)
    monkeypatch.setattr(
        "app.integrations.epic_oauth.create_exchange_code",
        lambda access_token: "exch",
    )

    browser = FakeAuthBrowser(AuthOutcome(success=True))
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=browser,
        screen=FakeScreen(available=True),
        sessions_path=str(sessions_dir),
    )
    assert auth.silent_restore(account.id) is True

    assert browser.start_url is not None
    assert "id/exchange" in browser.start_url
    assert browser.headless is True

    with database.connect() as connection:
        stored = accounts.get(connection, account.id)
    assert stored.state == AccountState.ACTIVE
    # The rotated refresh token replaces the stored one.
    assert epic_oauth.load_refresh_token(profile) == "re2"


def test_silent_restore_returns_false_without_stored_token(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FakeScreen(available=True),
        sessions_path=str(tmp_path / "sessions"),
    )
    assert auth.silent_restore(account.id) is False


def test_silent_restore_returns_false_when_epic_rejects_token(tmp_path, monkeypatch):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    sessions_dir = tmp_path / "sessions"
    profile = str(sessions_dir / str(account.id))
    epic_oauth.save_session_tokens(
        profile, {"refresh_token": "re", "account_id": "acct-5", "display_name": "Epic User"}
    )

    def fake_refresh(token):
        raise epic_oauth.EpicOAuthError("invalid refresh token")

    monkeypatch.setattr("app.integrations.epic_oauth.refresh_tokens", fake_refresh)

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FakeScreen(available=True),
        sessions_path=str(sessions_dir),
    )
    assert auth.silent_restore(account.id) is False


def test_silent_restore_returns_false_when_another_flow_is_running(tmp_path, monkeypatch):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")

    sessions_dir = tmp_path / "sessions"
    epic_oauth.save_session_tokens(
        str(sessions_dir / str(account.id)), {"refresh_token": "re", "account_id": "a", "display_name": "U"}
    )
    monkeypatch.setattr(
        "app.integrations.epic_oauth.refresh_tokens", lambda token: {"access_token": "at", "refresh_token": "re", "account_id": "a", "display_name": "U"}
    )

    auth = AuthService(
        database=database,
        repository=accounts,
        browser=FakeAuthBrowser(AuthOutcome(success=True)),
        screen=FakeScreen(available=True),
        sessions_path=str(sessions_dir),
    )
    session = auth.start(account.id, mode="device")
    assert auth.silent_restore(account.id) is False
    auth._revoke(session.token)


def test_revoke_sets_cooperative_stop_and_closes_screen(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    service = AccountService(accounts, str(tmp_path / "sessions"))
    browser_started = threading.Event()
    stop_seen = []

    class CooperativeBrowser(FakeAuthBrowser):
        def __init__(self):
            super().__init__(AuthOutcome(success=True, epic_identity="e"))
            self.should_stop_seen = False

        def run_auth(self, profile_path, display, timeout_seconds, on_intervention=None, should_stop=None):
            self.calls += 1
            browser_started.set()
            deadline = time.time() + 5
            while time.time() < deadline:
                if should_stop is not None and should_stop():
                    self.should_stop_seen = True
                    stop_seen.append(True)
                    return AuthOutcome(success=False, error="revoked by user")
                time.sleep(0.05)
            return self.outcome

    with database.connect() as connection:
        account = service.create(connection, "Personal")

    screen = FakeScreen(available=True)
    browser = CooperativeBrowser()
    auth = AuthService(
        database=database,
        repository=accounts,
        browser=browser,
        screen=screen,
        sessions_path=str(tmp_path / "sessions"),
        auth_timeout_seconds=10,
    )
    session = auth.start(account.id)
    assert session.status == "running"
    assert browser_started.wait(timeout=5)
    auth.revoke(session.token)
    deadline = time.time() + 3
    while time.time() < deadline and not stop_seen:
        time.sleep(0.05)
    assert browser.should_stop_seen is True
    assert screen.stopped is True
    assert auth.get(session.token) is None
