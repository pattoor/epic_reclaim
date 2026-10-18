from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.domain import scheduling


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    app_host: str = "0.0.0.0"
    app_port: int = 8765
    no_vnc_port: int = 6080
    public_host: str = ""
    locale: str = ""
    database_path: str = "./data/database/epic.db"
    sessions_path: str = "./data/sessions"
    state_path: str = "./data/state"
    scheduler_enabled: bool = True
    scheduler_days: str = "THU"
    scheduler_times: str = "14:05"
    scheduler_daily: bool = False
    claim_delay_min_seconds: float = 2
    claim_delay_max_seconds: float = 5
    max_retry_attempts: int = 3
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    external_api_key_enabled: bool = False
    external_api_key: str = ""

    @classmethod
    def from_env(cls, overrides: dict[str, str] | None = None) -> "Settings":
        values = dict(os.environ)
        if overrides:
            values.update(overrides)

        def get(name: str, default: str) -> str:
            return values.get(name, default)

        def boolean(name: str, default: bool) -> bool:
            return _bool(values.get(name), default)

        settings = cls(
            app_host=get("APP_HOST", cls.app_host),
            app_port=int(get("APP_PORT", str(cls.app_port))),
            no_vnc_port=int(get("NOVNC_PORT", str(cls.no_vnc_port))),
            public_host=get("PUBLIC_HOST", cls.public_host),
            locale=get("LOCALE", cls.locale),
            database_path=get("DATABASE_PATH", cls.database_path),
            sessions_path=get("SESSIONS_PATH", cls.sessions_path),
            state_path=get("STATE_PATH", cls.state_path),
            scheduler_enabled=boolean("SCHEDULER_ENABLED", cls.scheduler_enabled),
            scheduler_days=get("SCHEDULER_DAYS", cls.scheduler_days),
            scheduler_times=get("SCHEDULER_TIMES", cls.scheduler_times),
            scheduler_daily=boolean("SCHEDULER_DAILY", cls.scheduler_daily),
            claim_delay_min_seconds=float(
                get("CLAIM_DELAY_MIN_SECONDS", str(cls.claim_delay_min_seconds))
            ),
            claim_delay_max_seconds=float(
                get("CLAIM_DELAY_MAX_SECONDS", str(cls.claim_delay_max_seconds))
            ),
            max_retry_attempts=int(get("MAX_RETRY_ATTEMPTS", str(cls.max_retry_attempts))),
            telegram_enabled=boolean("TELEGRAM_ENABLED", cls.telegram_enabled),
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=get("TELEGRAM_CHAT_ID", ""),
            external_api_key_enabled=boolean(
                "EXTERNAL_API_KEY_ENABLED", cls.external_api_key_enabled
            ),
            external_api_key=get("EXTERNAL_API_KEY", ""),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 1 <= self.app_port <= 65535:
            raise ConfigError(f"APP_PORT must be in 1..65535, got {self.app_port}")
        if not 1 <= self.no_vnc_port <= 65535:
            raise ConfigError(f"NOVNC_PORT must be in 1..65535, got {self.no_vnc_port}")
        try:
            scheduling.normalize_days(self.scheduler_days)
            scheduling.normalize_times(self.scheduler_times)
        except scheduling.ScheduleError as exc:
            raise ConfigError(str(exc)) from exc
        if self.claim_delay_min_seconds < 0:
            raise ConfigError(
                f"CLAIM_DELAY_MIN_SECONDS must be >= 0, got {self.claim_delay_min_seconds}"
            )
        if self.claim_delay_max_seconds < self.claim_delay_min_seconds:
            raise ConfigError(
                "CLAIM_DELAY_MAX_SECONDS must be >= CLAIM_DELAY_MIN_SECONDS "
                f"({self.claim_delay_max_seconds} < {self.claim_delay_min_seconds})"
            )
        if self.max_retry_attempts < 0:
            raise ConfigError(
                f"MAX_RETRY_ATTEMPTS must be >= 0, got {self.max_retry_attempts}"
            )
        if self.telegram_enabled and not (self.telegram_bot_token and self.telegram_chat_id):
            raise ConfigError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when enabled")
        if self.external_api_key_enabled and not self.external_api_key:
            raise ConfigError("EXTERNAL_API_KEY is required when enabled")

    def ensure_directories(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.sessions_path).mkdir(parents=True, exist_ok=True)
        Path(self.state_path).mkdir(parents=True, exist_ok=True)
