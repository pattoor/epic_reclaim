from datetime import datetime, timezone
from pathlib import Path
import json
from datetime import date

from app.config import Settings
from app.database import Database
from app.repositories import SettingsRepository
from app.services.settings_service import SettingsService
from app.bootstrap import build_runtime
from app.config import Settings as S
from app.domain.models import RunTrigger
from app.services.run_workflow import RunLock, RunWorkflow
from app.repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
)


def _settings(tmp_path, **overrides):
    env = {
        "DATABASE_PATH": str(tmp_path / "epic.db"),
        "SESSIONS_PATH": str(tmp_path / "sessions"),
        "STATE_PATH": str(tmp_path / "state"),
        "SCHEDULER_ENABLED": "false",
    }
    env.update(overrides)
    return Settings.from_env(env)


def test_legacy_interval_migrates_to_daily_preset(tmp_path):
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    with database.connect() as connection:
        SettingsRepository().set(connection, "scheduler_interval_seconds", "1440")
        service = SettingsService(settings, SettingsRepository())
        effective = service.load(connection)
        assert effective.scheduler_daily is False  # migrated weekly slot
        assert effective.scheduler_days.endswith("THU") or effective.scheduler_days == "THU" or \
               effective.scheduler_days == "MON,TUE,WED,THU,FRI,SAT,SUN"
        raw = SettingsRepository().all(connection)
    assert "scheduler_interval_seconds" not in raw
    assert raw["scheduler_days"]  # migrated


def test_legacy_interval_24h_migrates_to_full_days(tmp_path):
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    with database.connect() as connection:
        SettingsRepository().set(connection, "scheduler_interval_seconds", "86400")
        service = SettingsService(settings, SettingsRepository())
        service.load(connection)
        raw = SettingsRepository().all(connection)
    assert raw["scheduler_days"] == "MON,TUE,WED,THU,FRI,SAT,SUN"


def test_legacy_interval_other_value_migrates_to_default_slot(tmp_path):
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    with database.connect() as connection:
        SettingsRepository().set(connection, "scheduler_interval_seconds", "7200")
        service = SettingsService(settings, SettingsRepository())
        service.load(connection)
        raw = SettingsRepository().all(connection)
    assert raw["scheduler_days"] == "THU"
    assert raw["scheduler_times"] == "14:05"


def test_view_hides_secret_settings(tmp_path):
    from app.config import Settings as C

    base = C.from_env(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "TELEGRAM_BOT_TOKEN": "secret-token",
            "TELEGRAM_CHAT_ID": "secret-chat",
        }
    )
    database = Database(base.database_path)
    database.initialize()
    with database.connect() as connection:
        raw_repo = SettingsRepository()
        raw_repo.set(connection, "telegram_bot_token", "leaked-secret")
        service = SettingsService(base, raw_repo)
        visible = service.view(connection)
    assert "telegram_bot_token" not in visible
