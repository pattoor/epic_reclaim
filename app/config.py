from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_host: str = "0.0.0.0"
    app_port: int = 8765
    database_path: str = "./data/database/epic.db"
    sessions_path: str = "./data/sessions"
    state_path: str = "./data/state"
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 21600
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
        values.update(overrides or {})

        def get(name: str, default: str) -> str:
            return values.get(name, default)

        return cls(
            app_host=get("APP_HOST", cls.app_host),
            app_port=int(get("APP_PORT", str(cls.app_port))),
            database_path=get("DATABASE_PATH", cls.database_path),
            sessions_path=get("SESSIONS_PATH", cls.sessions_path),
            state_path=get("STATE_PATH", cls.state_path),
            scheduler_enabled=values.get("SCHEDULER_ENABLED", str(cls.scheduler_enabled)).lower() in {"1", "true", "yes", "on"},
            scheduler_interval_seconds=int(get("SCHEDULER_INTERVAL_SECONDS", str(cls.scheduler_interval_seconds))),
            claim_delay_min_seconds=float(get("CLAIM_DELAY_MIN_SECONDS", str(cls.claim_delay_min_seconds))),
            claim_delay_max_seconds=float(get("CLAIM_DELAY_MAX_SECONDS", str(cls.claim_delay_max_seconds))),
            max_retry_attempts=int(get("MAX_RETRY_ATTEMPTS", str(cls.max_retry_attempts))),
            telegram_enabled=values.get("TELEGRAM_ENABLED", str(cls.telegram_enabled)).lower() in {"1", "true", "yes", "on"},
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=get("TELEGRAM_CHAT_ID", ""),
            external_api_key_enabled=values.get("EXTERNAL_API_KEY_ENABLED", str(cls.external_api_key_enabled)).lower() in {"1", "true", "yes", "on"},
            external_api_key=get("EXTERNAL_API_KEY", ""),
        )

    def ensure_directories(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.sessions_path).mkdir(parents=True, exist_ok=True)
        Path(self.state_path).mkdir(parents=True, exist_ok=True)
