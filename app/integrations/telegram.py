from __future__ import annotations

import logging
import time

import httpx

from app.services.run_workflow import RunOutcome
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

ALERT_DEDUP_WINDOW_SECONDS = 600


class TelegramNotifier:
    def __init__(self, settings_service: SettingsService, database):
        self._settings_service = settings_service
        self._database = database
        self._last_alerts: dict[str, float] = {}

    def _is_enabled(self):
        with self._database.connect() as connection:
            settings = self._settings_service.load(connection)
        return settings.telegram_enabled

    def _dedup(self, text: str) -> bool:
        now = time.monotonic()
        last = self._last_alerts.get(text)
        if last is not None and now - last < ALERT_DEDUP_WINDOW_SECONDS:
            return True
        self._last_alerts[text] = now
        return False

    def _send(self, text: str) -> None:
        if not self._is_enabled():
            return
        with self._database.connect() as connection:
            settings = self._settings_service.load(connection)
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": settings.telegram_chat_id, "text": text}
        try:
            httpx.post(url, json=payload, timeout=10)
        except Exception:
            logger.warning("telegram_send_failed", exc_info=True)

    def notify_run_summary(self, outcome: RunOutcome) -> None:
        if outcome.run_id is None:
            return
        lines = [
            "Epic Claim finished",
            f"{outcome.accounts_processed} accounts",
            f"{outcome.games_detected} games detected",
            f"{outcome.claimed_count} successful claims",
            f"{outcome.already_owned_count} already owned",
            f"{outcome.failed_count} failures",
        ]
        if outcome.error:
            lines.append(f"error: {outcome.error}")
        self._send("\n".join(lines))

    def notify_alert(self, text: str) -> None:
        if self._dedup(text):
            return
        self._send(f"Epic Reclaim alert: {text}")

    def notify_resolved(self, text: str) -> None:
        self._send(f"Epic Reclaim resolved: {text}")
