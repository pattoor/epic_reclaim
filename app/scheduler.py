"""Slot-based scheduler: fires configured day+time windows.

Replaces the previous interval loop. Slots fire at most once per day they
apply to; a fired slot is remembered both in memory and by checking runs
started inside the window (restart-safe: a slot missed because the process
was down is simply not fired retroactively).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.run_workflow import RunWorkflow
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

# The scheduler polls settings at this cadence; a slot fires when `now` falls
# inside [slot_time, slot_time + slot_window). Keep the window comfortably
# larger than the check interval so ticks cannot skip a slot.
DEFAULT_CHECK_INTERVAL_SECONDS = 60
DEFAULT_SLOT_WINDOW_SECONDS = 180


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TickResult:
    fired: bool
    slot: str | None = None


class SlotRunner:
    """Deterministic scheduling core. Injectable clock for tests."""

    def __init__(
        self,
        workflow: RunWorkflow,
        settings_service: SettingsService,
        database,
        clock=None,
        slot_window_seconds: int = DEFAULT_SLOT_WINDOW_SECONDS,
    ):
        self._workflow = workflow
        self._settings_service = settings_service
        self._database = database
        self._clock = clock or utc_now
        self._slot_window = timedelta(
            seconds=max(slot_window_seconds, DEFAULT_SLOT_WINDOW_SECONDS)
        )
        self.next_run_at: str | None = None
        self._fired_marks: set[str] = set()

    def evaluate_tick(self) -> TickResult:
        """One tick: fire at most one due slot window and refresh next_run_at."""
        with self._database.connect() as connection:
            settings = self._settings_service.load(connection)
        if not settings.scheduler_enabled:
            self.next_run_at = None
            return TickResult(fired=False)

        slots = settings.slots()
        now = self._clock()
        fired: TickResult | None = None
        for slot in sorted(slots, key=lambda item: (item.time.hour, item.time.minute)):
            if not slot.matches(now):
                continue
            slot_start = now.replace(
                hour=slot.time.hour, minute=slot.time.minute, second=0, microsecond=0
            )
            if not (slot_start <= now < slot_start + self._slot_window):
                continue
            if self._already_fired(slot.label, slot_start):
                continue
            self._fire(slot)
            self._fired_marks.add(f"{slot.label}|{slot_start.date().isoformat()}")
            fired = TickResult(fired=True, slot=slot.label)
            break

        self._refresh_next_run(now)
        return fired or TickResult(fired=False)

    def _already_fired(self, label: str, slot_start: datetime) -> bool:
        window_start = (slot_start - self._slot_window).isoformat(timespec="seconds")
        window_end = (slot_start + self._slot_window).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            recent = connection.execute(
                "SELECT started_at FROM runs "
                "WHERE trigger_source = 'scheduler' AND started_at >= ? AND started_at <= ?",
                (window_start, window_end),
            ).fetchall()
        if recent:
            self._fired_marks.add(f"{label}|{slot_start.date().isoformat()}")
            return True
        return f"{label}|{slot_start.date().isoformat()}" in self._fired_marks

    def _fire(self, slot) -> None:
        logger.info("scheduler_slot_fired slot=%s", slot.label)
        thread = threading.Thread(
            target=self._run_workflow, args=(slot,), daemon=True
        )
        thread.start()

    def _run_workflow(self, slot) -> None:
        from app.domain.models import RunTrigger

        try:
            self._workflow.run(RunTrigger.SCHEDULER)
        except Exception:  # pragma: no cover - defensive
            logger.exception("scheduler_run_failed slot=%s", slot.label)

    def _refresh_next_run(self, now: datetime) -> None:
        from app.domain.scheduling import next_occurrence

        with self._database.connect() as connection:
            settings = self._settings_service.load(connection)
        upcoming = next_occurrence(settings.slots(), now)
        self.next_run_at = upcoming.isoformat(timespec="seconds") if upcoming else None


class Scheduler:
    """Async runtime wrapper: sweeps SlotRunner every check interval."""

    def __init__(
        self,
        workflow: RunWorkflow,
        settings_service: SettingsService,
        database,
        *,
        clock=None,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        slot_window_seconds: int = DEFAULT_SLOT_WINDOW_SECONDS,
    ):
        self._check_interval = max(check_interval_seconds, 30.0)
        # The firing window must comfortably span several polling ticks;
        # otherwise a slow-polling scheduler can skip slots entirely.
        effective_window = max(
            slot_window_seconds or DEFAULT_SLOT_WINDOW_SECONDS,
            self._check_interval * 2,
        )
        self._work_slot_window = effective_window
        self._clock = clock
        self._settings_service = settings_service
        self._database = database
        self._workflow = workflow
        self.next_run_at: str | None = None
        self._task: asyncio.Task | None = None
        self._runner: SlotRunner | None = None

    @property
    def runner(self) -> SlotRunner:
        if self._runner is None:
            self._runner = SlotRunner(
                self._workflow,
                self._settings_service,
                self._database,
                clock=self._clock,
                slot_window_seconds=self._work_slot_window,
            )
        return self._runner

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.runner.evaluate_tick)
            except Exception:  # defensive: never kill the scheduler loop
                logger.exception("scheduler_tick_failed")
            self.next_run_at = self.runner.next_run_at
            await asyncio.sleep(self._check_interval)
