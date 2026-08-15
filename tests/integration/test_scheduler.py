import asyncio

from app.config import Settings
from app.database import Database
from app.domain.models import RunTrigger
from app.repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
    SettingsRepository,
)
from app.scheduler import Scheduler
from app.services.run_workflow import RunLock, RunWorkflow
from app.services.settings_service import SettingsService
from tests.fakes import FakeEpicAdapter


class FakeSettings:
    def __init__(self, enabled: bool):
        self.scheduler_enabled = enabled
        self.scheduler_interval_seconds = 60
        self.max_retry_attempts = 3


def _build(tmp_path, enabled: bool):
    settings = Settings.from_env(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": str(enabled).lower(),
        }
    )
    database = Database(settings.database_path)
    database.initialize()
    workflow = RunWorkflow(
        database=database,
        adapter=FakeEpicAdapter(),
        accounts_repository=AccountsRepository(),
        games_repository=GamesRepository(),
        claims_repository=ClaimsRepository(),
        attempts_repository=ClaimAttemptsRepository(),
        runs_repository=RunsRepository(),
        events_repository=RunEventsRepository(),
        lock=RunLock(),
        settings_provider=lambda connection: FakeSettings(enabled),
        delay_between_actions=lambda: None,
    )
    service = SettingsService(settings, SettingsRepository())
    scheduler = Scheduler(workflow, service, database)
    return database, scheduler, RunsRepository()


def test_scheduler_disabled_does_not_run(tmp_path):
    database, scheduler, runs = _build(tmp_path, enabled=False)
    asyncio.run(scheduler._tick_if_enabled())
    with database.connect() as connection:
        assert runs.list(connection) == []


def test_scheduler_enabled_runs_workflow(tmp_path):
    database, scheduler, runs = _build(tmp_path, enabled=True)
    asyncio.run(scheduler._tick_if_enabled())
    with database.connect() as connection:
        stored = runs.list(connection)
    assert len(stored) == 1
    assert stored[0].trigger_source == RunTrigger.SCHEDULER
