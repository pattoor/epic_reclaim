from app.config import Settings


def test_settings_use_safe_defaults(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)

    settings = Settings.from_env()

    assert settings.app_port == 8765
    assert settings.database_path.endswith("data/database/epic.db")
    assert settings.claim_delay_min_seconds == 2
    assert settings.claim_delay_max_seconds == 5
