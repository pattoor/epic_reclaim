import time

from app.database import Database
from app.domain.models import AccountState
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
