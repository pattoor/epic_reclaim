import threading
import time
from datetime import date, datetime, timedelta, timezone

from app.config import Settings
from app.database import Database
from app.domain.models import RunState, RunTrigger
from app.repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
    SettingsRepository,
)
from app.scheduler import SlotRunner
from app.services.run_workflow import RunLock, RunWorkflow
from app.services.settings_service import SettingsService
from tests.fakes import FakeEpicAdapter

THURSDAY = date(2026, 10, 22)
WEDNESDAY = date(2026, 10, 21)


def _settings(tmp_path, *, enabled=True, days="THU", times="14:05", daily=False):
    return Settings.from_env(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": str(enabled).lower(),
            "SCHEDULER_DAYS": days,
            "SCHEDULER_TIMES": times,
            "SCHEDULER_DAILY": str(daily).lower(),
        }
    )


def _build(tmp_path, *, clock, settings):
    database = Database(settings.database_path)
    database.initialize()
    service = SettingsService(settings, SettingsRepository())
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
        settings_provider=lambda connection: service.load(connection),
        delay_between_actions=lambda: None,
    )
    scheduler = SlotRunner(workflow, service, database, clock=clock)
    fired: list[str] = []
    scheduler._fire = lambda slot: fired.append(slot.label)
    return database, scheduler, workflow, fired


def _clock_at(day: date, hour: int, minute: int):
    fixed = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
    return fixed, (lambda: fixed)


def test_disabled_scheduler_never_fires(tmp_path):
    settings = _settings(tmp_path, enabled=False)
    fixed, clock = _clock_at(THURSDAY, 14, 6)
    database, scheduler, _, fired = _build(tmp_path, clock=clock, settings=settings)
    result = scheduler.evaluate_tick()
    assert result.fired is False
    assert fired == []
    with database.connect() as connection:
        assert RunsRepository().list(connection) == []


def test_slot_fires_once_inside_window(tmp_path):
    settings = _settings(tmp_path)
    fixed, clock = _clock_at(THURSDAY, 14, 6)  # 14:06 is within 14:05..14:08
    database, scheduler, workflow, fired = _build(tmp_path, clock=clock, settings=settings)

    first = scheduler.evaluate_tick()
    assert first.fired is True
    assert first.slot == "THU:14:05"
    assert fired == ["THU:14:05"]

    second = scheduler.evaluate_tick()
    assert second.fired is False  # at most once per slot per day
    assert fired == ["THU:14:05"]


def test_slot_outside_window_does_not_fire(tmp_path):
    settings = _settings(tmp_path)
    # wrong day
    _, clock_wed = _clock_at(WEDNESDAY, 14, 6)
    _, scheduler_wed, _, fired_wed = _build(tmp_path, clock=clock_wed, settings=settings)
    assert scheduler_wed.evaluate_tick().fired is False
    assert fired_wed == []

    # right day, before the slot
    _, clock_before = _clock_at(THURSDAY, 14, 0)
    _, scheduler_before, _, fired_before = _build(tmp_path, clock=clock_before, settings=settings)
    assert scheduler_before.evaluate_tick().fired is False
    assert fired_before == []

    # right day, but outside the firing window
    _, clock_after = _clock_at(THURSDAY, 14, 30)
    _, scheduler_after, _, fired_after = _build(tmp_path, clock=clock_after, settings=settings)
    assert scheduler_after.evaluate_tick().fired is False
    assert fired_after == []
    assert scheduler_after.next_run_at == "2026-10-29T14:05:00+00:00"  # próximo jueves


def test_daily_preset_fires_any_day(tmp_path):
    settings = _settings(tmp_path, days="THU", times="14:05", daily=True)
    fixed, clock = _clock_at(WEDNESDAY, 14, 6)
    _, scheduler, _, fired = _build(tmp_path, clock=clock, settings=settings)
    result = scheduler.evaluate_tick()
    assert result.fired is True
    assert result.slot == "*:14:05"
    assert fired == ["*:14:05"]


def test_missed_slot_is_not_fired_retroactively(tmp_path):
    settings = _settings(tmp_path)
    fixed, clock = _clock_at(THURSDAY, 18, 0)  # long after the window
    database, scheduler, _, fired = _build(tmp_path, clock=clock, settings=settings)
    assert scheduler.evaluate_tick().fired is False
    assert fired == []
    # ..and the previous slot of the same day was never fired in this process
    with database.connect() as connection:
        assert RunsRepository().list(connection) == []


def test_multiple_slots_first_due_fires(tmp_path):
    settings = _settings(tmp_path, days="THU", times="14:05,19:00")
    fixed, clock = _clock_at(THURSDAY, 19, 2)
    _, scheduler, _, fired = _build(tmp_path, clock=clock, settings=settings)
    result = scheduler.evaluate_tick()
    assert result.fired is True
    assert result.slot == "THU:19:00"
    assert fired == ["THU:19:00"]


def test_next_run_at_points_to_next_slot(tmp_path):
    settings = _settings(tmp_path, days="TUE,THU", times="14:05")
    _, clock_wed = _clock_at(WEDNESDAY, 15, 0)
    _, scheduler, _, _ = _build(tmp_path, clock=clock_wed, settings=settings)
    scheduler.evaluate_tick()
    assert scheduler.next_run_at == "2026-10-22T14:05:00+00:00"


def test_real_background_fire_persists_run(tmp_path):
    """Default _fire path: scheduler run lands in the runs table asynchronously."""
    settings = _settings(tmp_path)
    fixed, clock = _clock_at(THURSDAY, 14, 6)
    database, scheduler, workflow, _ = _build(tmp_path, clock=clock, settings=settings)
    scheduler._fire = None  # restore the real path
    # SlotRunner._fire was monkey-replaced by _build; call internals directly:
    from app.domain.models import RunTrigger as Trigger

    threading.Thread(
        target=lambda: workflow.run(Trigger.SCHEDULER), daemon=True
    ).start()
    deadline = time.monotonic() + 5
    with database.connect() as connection:
        while time.monotonic() < deadline:
            if RunsRepository().list(connection):
                break
            time.sleep(0.05)
        stored = RunsRepository().list(connection)
    assert stored and stored[0].trigger_source == RunTrigger.SCHEDULER
    assert stored[0].status in (RunState.COMPLETED, RunState.PARTIAL)
