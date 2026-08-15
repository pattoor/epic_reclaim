from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.repositories import SettingsRepository


@dataclass(frozen=True)
class EffectiveSettings:
    scheduler_enabled: bool
    scheduler_interval_seconds: int
    claim_delay_min_seconds: float
    claim_delay_max_seconds: float
    max_retry_attempts: int
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str


class SettingsService:
    def __init__(self, settings: Settings, repository: SettingsRepository):
        self._settings = settings
        self._repository = repository

    def load(self, connection) -> EffectiveSettings:
        stored = self._repository.all(connection)

        def get_bool(key: str, default: bool) -> bool:
            value = stored.get(key)
            if value is None:
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        def get_int(key: str, default: int) -> int:
            value = stored.get(key)
            return int(value) if value is not None else default

        def get_float(key: str, default: float) -> float:
            value = stored.get(key)
            return float(value) if value is not None else default

        return EffectiveSettings(
            scheduler_enabled=get_bool(
                "scheduler_enabled", self._settings.scheduler_enabled
            ),
            scheduler_interval_seconds=get_int(
                "scheduler_interval_seconds", self._settings.scheduler_interval_seconds
            ),
            claim_delay_min_seconds=get_float(
                "claim_delay_min_seconds", self._settings.claim_delay_min_seconds
            ),
            claim_delay_max_seconds=get_float(
                "claim_delay_max_seconds", self._settings.claim_delay_max_seconds
            ),
            max_retry_attempts=get_int(
                "max_retry_attempts", self._settings.max_retry_attempts
            ),
            telegram_enabled=get_bool(
                "telegram_enabled", self._settings.telegram_enabled
            ),
            telegram_bot_token=stored.get(
                "telegram_bot_token", self._settings.telegram_bot_token
            ),
            telegram_chat_id=stored.get(
                "telegram_chat_id", self._settings.telegram_chat_id
            ),
        )

    def update(
        self, connection, updates: dict[str, str], allowed_keys: set[str]
    ) -> dict[str, str]:
        for key, value in updates.items():
            if key in allowed_keys:
                self._repository.set(connection, key, str(value))
        return self._repository.all(connection)
