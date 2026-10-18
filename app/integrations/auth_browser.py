from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable


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
    def run_auth(
        self,
        profile_path: str,
        display: str | None,
        timeout_seconds: int,
        on_intervention: Callable[[str], None] | None = None,
    ) -> AuthOutcome:
        pass


class PlaywrightAuthBrowser(InteractiveAuthBrowser):
    """Headed Chromium used only for the interactive login session.

    The browser targets the Epic store landing page of the configured store
    locale (empty locale => let Epic's IP-based region resolution apply).
    """

    def __init__(self, locale: str = ""):
        self._locale = (locale or "").strip()

    def _base(self) -> str:
        return f"https://store.epicgames.com/{self._locale}" if self._locale else "https://store.epicgames.com"

    def run_auth(
        self,
        profile_path: str,
        display: str | None,
        timeout_seconds: int,
        on_intervention: Callable[[str], None] | None = None,
    ) -> AuthOutcome:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return AuthOutcome(success=False, error="playwright not installed")

        env = {}
        if display:
            env["DISPLAY"] = display
        intervention: str | None = None
        import time

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=False,
                    env=env,
                )
                try:
                    page = browser.pages[0] if browser.pages else browser.new_page()
                    page.goto(self._store_url(), timeout=30000)
                    if "Sign In" in page.inner_text("body"):
                        page.goto(self._login_url(), timeout=30000)

                    deadline = time.monotonic() + timeout_seconds
                    while time.monotonic() < deadline:
                        time.sleep(3)
                        body = page.inner_text("body")
                        lowered = body.lower()
                        current_intervention = _intervention_kind(lowered)
                        if current_intervention and current_intervention != intervention:
                            intervention = current_intervention
                            if on_intervention is not None:
                                on_intervention(intervention)
                        if _is_logged_in(page):
                            return AuthOutcome(
                                success=True,
                                epic_identity=_extract_identity(page),
                                display_name=None,
                            )
                    return AuthOutcome(
                        success=False,
                        needs_intervention=intervention is not None,
                        error=intervention or "auth timeout",
                    )
                finally:
                    browser.close()
        except TimeoutError:
            return AuthOutcome(success=False, error="auth timeout")

    def _store_url(self) -> str:
        return f"{self._base()}/"

    def _login_url(self) -> str:
        return f"{self._base()}/login"


def _is_logged_in(page) -> bool:
    try:
        return page.get_by_role("button", name="Sign Out").is_visible(timeout=2000)
    except Exception:
        return False


def _intervention_kind(body: str) -> str | None:
    if "captcha" in body or "verify you are human" in body:
        return "captcha"
    if "mfa" in body or "two-factor" in body or "verification code" in body:
        return "mfa"
    return None


def _extract_identity(page) -> str | None:
    try:
        button = page.get_by_role("button", name="Sign Out")
        button.hover(timeout=2000)
        return page.url.split("/")[-1] or None
    except Exception:
        return None
