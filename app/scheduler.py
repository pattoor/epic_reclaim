from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.domain.models import RunTrigger
from app.services.run_workflow import RunWorkflow
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        workflow: RunWorkflow,
        settings_service: SettingsService,
        database,
    ):
        self._workflow = workflow
        self._settings_service = settings_service
        self._database = database
        self._task: asyncio.Task | None = None
        self.next_run_at: str | None = None

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

    def _load_settings(self):
        with self._database.connect() as connection:
            return self._settings_service.load(connection)

    async def _loop(self) -> None:
        while True:
            await self._tick_if_enabled()
            settings = self._load_settings()
            if settings.scheduler_enabled:
                interval = max(settings.scheduler_interval_seconds, 60)
            else:
                interval = 60
            self.next_run_at = (
                datetime.now(timezone.utc) + timedelta(seconds=interval)
            ).isoformat(timespec="seconds")
            await asyncio.sleep(interval)

    async def _tick_if_enabled(self) -> None:
        try:
            settings = self._load_settings()
            if settings.scheduler_enabled:
                await self._tick()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("scheduler_tick_failed: %s", exc)

    async def _tick(self) -> None:
        logger.info("scheduler_tick")
        await asyncio.to_thread(self._workflow.run, RunTrigger.SCHEDULER)
