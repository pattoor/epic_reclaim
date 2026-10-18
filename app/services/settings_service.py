from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import Settings
from app.domain import scheduling
from app.repositories import SettingsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EffectiveSettings:
    scheduler_enabled: bool
    scheduler_days: str
    scheduler_times: str
    scheduler_daily: bool = False  # promotional seasons (e.g. Christmas)
    claim_delay_min_seconds: float = 2
    claim_delay_max_seconds: float = 5
    max_retry_attempts: int = 3
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    def slots(self) -> list[scheduling.Slot]:
        return scheduling.build_slots(
            days=self.scheduler_days, times=self.scheduler_times, daily=self.scheduler_daily
        )


class SettingsService:
    """DB-backed non-secret settings with legacy interval migration."""

    LEGACY_INTERVAL_KEY = "scheduler_interval_seconds"
    MIN_AUTOMATIC_GAP_SECONDS = 30 * 60

    def __init__(self, settings: Settings, repository: SettingsRepository):
        self._settings = settings
        self._repository = repository

    def load(self, connection) -> EffectiveSettings:
        stored = self._repository.all(connection)
        self._migrate_legacy_interval(connection, stored)

        def get_bool(key: str, default: bool) -> bool:
            value = stored.get(key)
            if value is None:
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        def get_str(key: str, default: str) -> str:
            value = stored.get(key)
            return value if value is not None else default

        def get_float(key: str, default: float) -> float:
            value = stored.get(key)
            return float(value) if value is not None else default

        def get_int(key: str, default: int) -> int:
            value = stored.get(key)
            return int(value) if value is not None else default

        # NOTE: legacy migration writes into the repository during this same
        # load; refresh the snapshot so the FIRST result already reflects the
        # migrated schedule (the first tick must use the right slots).
        stored = self._repository.all(connection)
        return EffectiveSettings(
            scheduler_enabled=get_bool("scheduler_enabled", self._settings.scheduler_enabled),
            scheduler_days=get_str("scheduler_days", self._settings.scheduler_days),
            scheduler_times=get_str("scheduler_times", self._settings.scheduler_times),
            scheduler_daily=get_bool("scheduler_daily", self._settings.scheduler_daily),
            claim_delay_min_seconds=get_float(
                "claim_delay_min_seconds", self._settings.claim_delay_min_seconds
            ),
            claim_delay_max_seconds=get_float(
                "claim_delay_max_seconds", self._settings.claim_delay_max_seconds
            ),
            max_retry_attempts=get_int("max_retry_attempts", self._settings.max_retry_attempts),
            telegram_enabled=get_bool("telegram_enabled", self._settings.telegram_enabled),
            telegram_bot_token=stored.get("telegram_bot_token", self._settings.telegram_bot_token),
            telegram_chat_id=stored.get("telegram_chat_id", self._settings.telegram_chat_id),
        )

    def _migrate_legacy_interval(self, connection, stored: dict[str, str]) -> None:
        legacy = stored.get(self.LEGACY_INTERVAL_KEY)
        if legacy is None:
            return
        try:
            interval = int(legacy)
        except ValueError:
            interval = 0
        if not stored.get("scheduler_days"):
            if interval >= 86400:  # legacy interval >= 1 day -> daily preset
                days = ",".join(scheduling.ALL_DAYS)
            else:
                days = "THU"
            self._repository.set(connection, "scheduler_days", days)
            self._repository.set(connection, "scheduler_times", "14:05")
            logger.info(
                "scheduler_settings_migrated legacy_interval_seconds=%s -> days=%s",
                interval,
                days,
            )
        # The legacy key is idempotently deleted; no further marker needed.
        connection.execute("DELETE FROM settings WHERE key = ?", (self.LEGACY_INTERVAL_KEY,))
        connection.commit()

    VIEW_SECRET_KEYS = {"telegram_bot_token", "telegram_chat_id", "external_api_key"}

    def view(self, connection) -> dict[str, str]:
        """Non-secret raw settings snapshot for display purposes."""
        return {
            key: value
            for key, value in self._repository.all(connection).items()
            if key not in self.VIEW_SECRET_KEYS
        }

    def update(self, connection, updates: dict[str, str], allowed_keys: set[str]) -> dict[str, str]:
        for key, value in updates.items():
            if key in allowed_keys:
                self._repository.set(connection, key, str(value))
        return self._repository.all(connection)
