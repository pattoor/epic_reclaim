from app.config import Settings
from app.database import Database
from app.integrations.telegram import TelegramNotifier
from app.repositories import SettingsRepository
from app.services.run_workflow import RunOutcome
from app.services.settings_service import SettingsService


def _make_notifier(tmp_path, telegram_enabled=False):
    settings = Settings.from_env(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "TELEGRAM_ENABLED": str(telegram_enabled).lower(),
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "test-chat",
        }
    )
    database = Database(settings.database_path)
    database.initialize()
    service = SettingsService(settings, SettingsRepository())
    return TelegramNotifier(service, database), database


def test_telegram_disabled_sends_nothing(tmp_path, monkeypatch):
    notifier, database = _make_notifier(tmp_path, telegram_enabled=False)

    calls = []

    def fake_send(text):
        calls.append(text)

    monkeypatch.setattr("app.integrations.telegram.httpx.post", fake_post)
    monkeypatch.setattr(notifier, "_is_enabled", lambda: False)

    notifier.notify_run_summary(
        RunOutcome(
            run_id=1,
            status="completed",
            accounts_processed=1,
            games_detected=2,
            claimed_count=1,
            already_owned_count=1,
            failed_count=0,
        )
    )
    notifier.notify_alert("captcha required")
    notifier.notify_resolved("account 1 active")

    assert calls == []


def fake_post(*args, **kwargs):
    raise AssertionError("should not call telegram when disabled")


def test_telegram_run_summary_format(tmp_path, monkeypatch):
    notifier, database = _make_notifier(tmp_path, telegram_enabled=True)
    notifier._is_enabled = lambda: True

    calls = []
    monkeypatch.setattr(notifier, "_send", lambda text: calls.append(text))

    notifier.notify_run_summary(
        RunOutcome(
            run_id=1,
            status="partial",
            accounts_processed=2,
            games_detected=2,
            claimed_count=1,
            already_owned_count=1,
            failed_count=1,
            error="captcha on account 2",
        )
    )
    assert len(calls) == 1
    text = calls[0]
    assert "Epic Claim finished" in text
    assert "2 accounts" in text
    assert "1 successful claims" in text
    assert "1 already owned" in text
    assert "1 failures" in text


def test_telegram_alert_mentions_context(tmp_path, monkeypatch):
    notifier, database = _make_notifier(tmp_path, telegram_enabled=True)
    notifier._is_enabled = lambda: True

    calls = []
    monkeypatch.setattr(notifier, "_send", lambda text: calls.append(text))

    notifier.notify_alert("account 3 paused (needs_intervention): captcha required")
    assert calls == ["Epic Reclaim alert: account 3 paused (needs_intervention): captcha required"]


def test_telegram_checks_http_response(tmp_path, monkeypatch):
    notifier, _ = _make_notifier(tmp_path, telegram_enabled=True)
    notifier._is_enabled = lambda: True

    class Response:
        def raise_for_status(self):
            raise RuntimeError("telegram rejected request")

        def json(self):
            return {"ok": False}

    calls = []
    monkeypatch.setattr("app.integrations.telegram.httpx.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.integrations.telegram.logger.warning", lambda *args, **kwargs: calls.append(args[0]))

    notifier.notify_alert("test")
    assert "telegram_send_failed" in calls
