from app.config import Settings, ConfigError


def test_settings_use_safe_defaults(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("SESSIONS_PATH", raising=False)
    monkeypatch.delenv("STATE_PATH", raising=False)

    settings = Settings.from_env()

    assert settings.app_port == 8765
    assert settings.database_path == "./data/database/epic.db"
    assert settings.claim_delay_min_seconds == 2
    assert settings.claim_delay_max_seconds == 5
    assert settings.max_retry_attempts == 3


def test_settings_from_override(monkeypatch):
    settings = Settings.from_env(
        {
            "APP_PORT": "9000",
            "CLAIM_DELAY_MIN_SECONDS": "3",
            "CLAIM_DELAY_MAX_SECONDS": "7",
            "SCHEDULER_ENABLED": "false",
        }
    )
    assert settings.app_port == 9000
    assert settings.claim_delay_min_seconds == 3
    assert settings.claim_delay_max_seconds == 7
    assert settings.scheduler_enabled is False


def test_settings_invalid_port_raises():
    import pytest

    with pytest.raises(ConfigError):
        Settings.from_env({"APP_PORT": "0"})


def test_settings_invalid_delay_range_raises():
    import pytest

    with pytest.raises(ConfigError):
        Settings.from_env(
            {"CLAIM_DELAY_MIN_SECONDS": "5", "CLAIM_DELAY_MAX_SECONDS": "2"}
        )


def test_settings_telegram_requires_token_and_chat():
    import pytest

    with pytest.raises(ConfigError):
        Settings.from_env(
            {"TELEGRAM_ENABLED": "true", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
        )


def test_settings_external_api_key_requires_value():
    import pytest

    with pytest.raises(ConfigError):
        Settings.from_env({"EXTERNAL_API_KEY_ENABLED": "true", "EXTERNAL_API_KEY": ""})
