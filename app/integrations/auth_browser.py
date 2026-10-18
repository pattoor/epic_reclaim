from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

from app.integrations.profile_locks import clear_stale_profile_locks


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
        should_stop: Callable[[], bool] | None = None,
        start_url: str | None = None,
        headless: bool = False,
    ) -> AuthOutcome:
        pass


FREE_GAMES_URL = "https://store.epicgames.com/free-games"


def _offers_visible(page) -> bool:
    """True when the free-games page shows its offers (the anti-bot wall is gone)."""
    try:
        return page.query_selector("a[href*='/p/'] [data-testid='OfferTitle']") is not None
    except Exception:
        return False


class PlaywrightAuthBrowser(InteractiveAuthBrowser):
    """Headed Chromium used only for the interactive login session.

    The browser opens Epic's real login page (/id/login) and, once the user
    completes it, lands back on the store home of the configured locale.
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
        should_stop: Callable[[], bool] | None = None,
        start_url: str | None = None,
        headless: bool = False,
    ) -> AuthOutcome:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return AuthOutcome(success=False, error="playwright not installed")

        clear_stale_profile_locks(profile_path)
        env = {}
        if display:
            env["DISPLAY"] = display
        intervention: str | None = None
        import time

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=headless,
                    env=env,
                )
                try:
                    page = browser.pages[0] if browser.pages else browser.new_page()
                    if start_url:
                        # Token-based flows (D10) land on Epic's /id/exchange
                        # page, which settles the SSO cookies without any
                        # user interaction; detection below does the rest.
                        page.goto(start_url, timeout=30000)
                    else:
                        # Id/login (the real Epic auth page) instead of the
                        # storefront: store pages sit behind the anti-bot
                        # wall and that challenge loops forever on a fresh
                        # profile, while the login page lets the user
                        # complete it manually.
                        page.goto(self._login_url(), timeout=30000)

                    deadline = time.monotonic() + timeout_seconds
                    while time.monotonic() < deadline:
                        time.sleep(3)
                        if should_stop is not None and should_stop():
                            return AuthOutcome(success=False, error="revoked by user")
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
                        if start_url and "/free-games" in start_url and _offers_visible(page):
                            # Unlock objective: the wall is gone and the user's
                            # session cookies are settled for the store pages.
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
        # /id/login is the real authentication page (no storefront anti-bot
        # wall); redirectUrl sends the browser back to the store home after
        # the user logs in, which is also where the success probe looks for
        # the Sign Out control.
        return f"https://www.epicgames.com/id/login?redirectUrl={quote(self._store_url(), safe='')}"


def _visible_control(page, role: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        try:
            locator = page.get_by_role(role, name=re.compile(pattern, re.IGNORECASE))
            if locator.first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


def _is_logged_in(page) -> bool:
    # Locale-aware: Epic serves store/id pages in the locale resolved per IP,
    # so both English and Spanish controls count.
    if _visible_control(page, "button", _SIGN_OUT_PATTERNS) or _visible_control(page, "link", _SIGN_OUT_PATTERNS):
        return True
    if "/login" in page.url.lower():
        return False
    body = page.inner_text("body").lower()
    if any(marker in body for marker in _SIGN_OUT_MARKERS):
        return True
    if _intervention_kind(body):
        return False
    if _visible_control(page, "link", _SIGN_IN_PATTERNS) or _visible_control(page, "button", _SIGN_IN_PATTERNS):
        return False
    if any(marker in body for marker in _SIGN_IN_MARKERS):
        return False
    return "epicgames.com" in page.url


_SIGN_OUT_PATTERNS = ("sign out", "cerrar sesi[oó]n")
_SIGN_OUT_MARKERS = ("sign out", "cerrar sesi[oó]n")
_SIGN_IN_PATTERNS = ("sign in", "iniciar sesi[oó]n", "log in")
_SIGN_IN_MARKERS = ("sign in", "iniciar sesi[oó]n")


def _intervention_kind(body: str) -> str | None:
    lowered = body.lower()
    if "captcha" in lowered or "verify you are human" in lowered:
        return "captcha"
    if "mfa" in lowered or "two-factor" in lowered or "verification code" in lowered:
        return "mfa"
    return None


def _extract_identity(page) -> str | None:
    try:
        button = page.get_by_role("button", name="Sign Out")
        button.hover(timeout=2000)
        return page.url.split("/")[-1] or None
    except Exception:
        return None
