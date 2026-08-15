from app.database import Database
from app.domain.models import AccountState, ClaimState, RunState, RunTrigger
from app.integrations.epic_adapter import GameCandidate
from app.repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
)
from app.services.run_workflow import RunLock, RunWorkflow
from tests.fakes import (
    FakeEpicAdapter,
    intervention_error,
    auth_error,
    rate_limit_error,
    blocked_error,
)


class FakeSettings:
    max_retry_attempts = 3


class FakeSettingsProvider:
    def __call__(self, connection):
        return FakeSettings()


def _database(tmp_path) -> Database:
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    return database


def _build(database, adapter, delay=None, sleeper=None):
    lock = RunLock()
    workflow = RunWorkflow(
        database=database,
        adapter=adapter,
        accounts_repository=AccountsRepository(),
        games_repository=GamesRepository(),
        claims_repository=ClaimsRepository(),
        attempts_repository=ClaimAttemptsRepository(),
        runs_repository=RunsRepository(),
        events_repository=RunEventsRepository(),
        lock=lock,
        settings_provider=FakeSettingsProvider(),
        delay_between_actions=delay,
        sleeper=sleeper or (lambda _: None),
    )
    return workflow


def _games():
    return [
        GameCandidate(epic_id="g1", name="Game One", url="https://store/g1"),
        GameCandidate(epic_id="g2", name="Game Two", url="https://store/g2"),
    ]


def _active_account(database) -> int:
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")
        accounts.set_state(connection, account.id, AccountState.ACTIVE)
    return account.id


def test_workflow_successful_run(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    workflow = _build(database, FakeEpicAdapter(games=_games()))

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.status == RunState.COMPLETED
    assert outcome.claimed_count == 2
    assert outcome.games_detected == 2
    assert outcome.accounts_processed == 1

    claims = ClaimsRepository()
    with database.connect() as connection:
        stored = claims.list(connection, account_id=account_id)
    assert {c.status for c in stored} == {ClaimState.CLAIMED}


def test_workflow_already_owned(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    adapter = FakeEpicAdapter(games=_games(), owned={"g1"})
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.claimed_count == 1
    assert outcome.already_owned_count == 1
    assert adapter._claim_calls.get("g1", 0) == 0


def test_workflow_idempotent_repeat_run(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    adapter = FakeEpicAdapter(games=_games())
    workflow = _build(database, adapter)

    first = workflow.run(RunTrigger.MANUAL)
    second = workflow.run(RunTrigger.SCHEDULER)

    assert first.claimed_count == 2
    assert second.claimed_count == 0
    assert second.already_owned_count == 2

    claims = ClaimsRepository()
    with database.connect() as connection:
        stored = claims.list(connection, account_id=account_id)
    assert len(stored) == 2

    attempts = ClaimAttemptsRepository()
    with database.connect() as connection:
        history = attempts.list_by_claim(connection, stored[0].id)
    assert len(history) == 2


def test_workflow_sequential_processing_order(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        first = accounts.create(connection, "First")
        accounts.update(connection, first.id, processing_order=2, state=AccountState.ACTIVE)
        second = accounts.create(connection, "Second")
        accounts.update(connection, second.id, processing_order=1, state=AccountState.ACTIVE)

    adapter = FakeEpicAdapter(games=_games())
    workflow = _build(database, adapter)
    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.claimed_count == 4
    assert outcome.accounts_processed == 2


def test_workflow_retry_transient_then_success(tmp_path):
    database = _database(tmp_path)
    _active_account(database)
    adapter = FakeEpicAdapter(
        games=_games(),
        claim_outcomes={"g1": "transient"},
        retries_before_success={"g1": 2},
    )
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.status == RunState.COMPLETED
    assert outcome.claimed_count == 2
    assert adapter._claim_calls["g1"] == 3


def test_workflow_retry_limit_exhausted(tmp_path):
    database = _database(tmp_path)
    _active_account(database)
    adapter = FakeEpicAdapter(
        games=_games(),
        claim_outcomes={"g1": "transient"},
    )
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.status == RunState.PARTIAL
    assert outcome.failed_count == 1
    assert adapter._claim_calls["g1"] == 3


def test_workflow_intervention_pauses_account_and_continues_others(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        blocked = accounts.create(connection, "Blocked")
        accounts.set_state(connection, blocked.id, AccountState.ACTIVE)
        healthy = accounts.create(connection, "Healthy")
        accounts.set_state(connection, healthy.id, AccountState.ACTIVE)

    adapter = FakeEpicAdapter(
        games=_games(),
        claim_outcomes={f"{blocked.id}:g1": intervention_error()},
    )
    workflow = _build(database, adapter)
    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.failed_count == 1
    assert outcome.claimed_count == 2

    with database.connect() as connection:
        blocked_stored = accounts.get(connection, blocked.id)
        healthy_stored = accounts.get(connection, healthy.id)
    assert blocked_stored.state == AccountState.NEEDS_INTERVENTION
    assert healthy_stored.state == AccountState.ACTIVE


def test_workflow_lock_prevents_concurrent_runs(tmp_path):
    database = _database(tmp_path)
    _active_account(database)
    lock = RunLock()
    assert lock.acquire() is True
    workflow = _build(database, FakeEpicAdapter(games=_games()))
    workflow._lock = lock

    outcome = workflow.run(RunTrigger.API)

    assert outcome.status == "conflict"
    lock.release()


def test_workflow_auth_required_sets_needs_authentication(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    adapter = FakeEpicAdapter(
        games=_games(), claim_outcomes={f"{account_id}:g1": auth_error()}
    )
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.failed_count == 1
    with database.connect() as connection:
        stored = AccountsRepository().get(connection, account_id)
    assert stored.state == AccountState.NEEDS_AUTHENTICATION


def test_workflow_rate_limit_pauses_account(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    adapter = FakeEpicAdapter(
        games=_games(), claim_outcomes={f"{account_id}:g1": rate_limit_error()}
    )
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.failed_count == 1
    with database.connect() as connection:
        stored = AccountsRepository().get(connection, account_id)
    assert stored.state == AccountState.PAUSED


def test_workflow_blocked_account_pauses(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    adapter = FakeEpicAdapter(
        games=_games(), claim_outcomes={f"{account_id}:g1": blocked_error()}
    )
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    with database.connect() as connection:
        stored = AccountsRepository().get(connection, account_id)
    assert stored.state == AccountState.PAUSED


def test_workflow_one_game_failure_does_not_stop_next_game(tmp_path):
    database = _database(tmp_path)
    account_id = _active_account(database)
    adapter = FakeEpicAdapter(
        games=_games(),
        claim_outcomes={
            f"{account_id}:g1": "transient",
        },
    )
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.failed_count == 1
    assert outcome.claimed_count == 1


def test_workflow_discovery_security_pauses_accounts(tmp_path):
    database = _database(tmp_path)
    _active_account(database)
    adapter = FakeEpicAdapter(games=_games())
    adapter.fail_discovery = intervention_error()
    workflow = _build(database, adapter)

    outcome = workflow.run(RunTrigger.MANUAL)

    assert outcome.status == RunState.FAILED
    with database.connect() as connection:
        stored = AccountsRepository().list(connection)
    assert stored[0].state == AccountState.NEEDS_INTERVENTION
