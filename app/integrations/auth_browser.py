from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthOutcome:
    success: bool
    epic_identity: str | None = None
    display_name: str | None = None
    needs_intervention: bool = False
    error: str | None = None


class InteractiveAuthBrowser(ABC):
    """Runs the server-side headed browser for interactive authentication."""

    @abstractmethod
    def run_auth(self, profile_path: str, display: str | None, timeout_seconds: int) -> AuthOutcome:
        pass


class PlaywrightAuthBrowser(InteractiveAuthBrowser):
    def run_auth(
        self, profile_path: str, display: str | None, timeout_seconds: int
    ) -> AuthOutcome:
        try:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright()
        except ImportError as exc:
            return AuthOutcome(success=False, error="playwright not installed")

        env = {}
        if display:
            env["DISPLAY"] = display
        try:
            browser = playwright.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=False,
                env=env,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto("https://store.epicgames.com/en-US/", timeout=30000)
            if "Sign In" in page.inner_text("body"):
                page.goto("https://store.epicgames.com/en-US/login", timeout=30000)

            import time

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                time.sleep(3)
                body = page.inner_text("body")
                if "captcha" in body.lower() or "verify you are human" in body.lower():
                    return AuthOutcome(success=False, needs_intervention=True, error="captcha")
                if "Sign Out" in body or "Account" in body:
                    identity = _extract_identity(page.url)
                    return AuthOutcome(
                        success=True,
                        epic_identity=identity,
                        display_name="Epic User",
                    )
            return AuthOutcome(success=False, error="auth timeout")
        finally:
            try:
                browser.close()
            except Exception:
                pass
            playwright.stop()


def _extract_identity(url: str) -> str | None:
    if "epicgames" not in url:
        return None
    return "epic-account"
