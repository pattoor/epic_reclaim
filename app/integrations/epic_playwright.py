from __future__ import annotations

import re
from pathlib import Path

from app.domain.errors import (
    InterventionRequiredError,
    RateLimitError,
    TransientError,
)
from app.integrations.epic_adapter import (
    AccountSession,
    AuthProgress,
    ClaimResult,
    EpicAdapter,
    GameCandidate,
    Outcome,
)

FREE_GAMES_URL = "https://store.epicgames.com/en-US/free-games"

_NON_ELIGIBLE = ("coming soon", "unavailable", "demo", "free to play")
_PAID_CTA = ("buy", "add to cart", "purchase", "pre-order", "preorder", "checkout")
_FREE_SIGNAL = ("free", "get", "add to library")
_PRICE_RE = re.compile(r"(?:\$|€|£)\s*\d")
_SECURITY_MARKERS = ("captcha", "verify you are human", "rate limit")


def _is_security_condition(page_text: str) -> str | None:
    lowered = page_text.lower()
    if "captcha" in lowered or "verify you are human" in lowered:
        return Outcome.INTERVENTION
    if "rate limit" in lowered or "too many requests" in lowered:
        return Outcome.RATE_LIMITED
    return None


def _has_nonzero_price(price: str | None) -> bool:
    if not price:
        return False
    return bool(_PRICE_RE.search(price.lower()))


def _is_paid_cta(cta: str | None) -> bool:
    if not cta:
        return False
    lowered = cta.lower()
    return any(marker in lowered for marker in _PAID_CTA)


def _has_free_signal(price: str | None, cta: str | None, badge: str | None) -> bool:
    signals = " ".join(item for item in (price, cta, badge) if item).lower()
    return any(marker in signals for marker in _FREE_SIGNAL)


def classify_offer(
    title: str,
    status_badge: str | None,
    price: str | None = None,
    cta: str | None = None,
) -> GameCandidate | None:
    combined = " ".join(item for item in (title, status_badge, price, cta) if item).lower()
    if any(marker in combined for marker in _NON_ELIGIBLE):
        return None
    if _is_paid_cta(cta) or _is_paid_cta(status_badge):
        return None
    if _has_nonzero_price(price):
        return None
    if not _has_free_signal(price, cta, status_badge):
        return None
    return GameCandidate(epic_id=None, name=title, url="")


class PlaywrightSession(AccountSession):
    def __init__(self, context, playwright):
        self.context = context
        self._playwright = playwright

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self._playwright.stop()


class PlaywrightEpicAdapter(EpicAdapter):
    def __init__(self, sessions_path: str):
        self._sessions_path = Path(sessions_path)

    def _import_playwright(self):
        try:
            from playwright.sync_api import sync_playwright

            return sync_playwright()
        except ImportError as exc:
            raise TransientError("playwright is not installed") from exc

    def _profile_path(self, account_id: int) -> Path:
        path = self._sessions_path / str(account_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def discover_free_games(self) -> list[GameCandidate]:
        with self._import_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(FREE_GAMES_URL, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                page_text = page.inner_text("body")
                condition = _is_security_condition(page_text)
                if condition == Outcome.INTERVENTION:
                    raise InterventionRequiredError("captcha detected during discovery")
                if condition == Outcome.RATE_LIMITED:
                    raise RateLimitError("rate limited during discovery")

                candidates: list[GameCandidate] = []
                offers = page.query_selector_all(
                    "a[href*='/p/']:has([data-testid='OfferTitle'])"
                )
                for offer in offers:
                    title_el = offer.query_selector("[data-testid='OfferTitle']")
                    if title_el is None:
                        continue
                    title = title_el.inner_text().strip()
                    price_el = offer.query_selector(
                        "[data-testid='OfferPrice'], [data-testid='Price']"
                    )
                    price = price_el.inner_text().strip() if price_el else None
                    badge_el = offer.query_selector("[data-testid='OfferStatus']")
                    badge = badge_el.inner_text().strip() if badge_el else None
                    cta_el = offer.query_selector(
                        "[data-testid='CTAButton'], button"
                    )
                    cta = cta_el.inner_text().strip() if cta_el else None
                    candidate = classify_offer(title, badge, price=price, cta=cta)
                    if candidate is None:
                        continue
                    href = offer.get_attribute("href") or ""
                    epic_id = None
                    if "/p/" in href:
                        slug = href.split("/p/", 1)[1].rstrip("/")
                        epic_id = slug or None
                    candidates.append(
                        GameCandidate(
                            epic_id=epic_id,
                            name=title,
                            url="https://store.epicgames.com" + href,
                        )
                    )
                return candidates
            finally:
                browser.close()

    def open_account_session(self, account_id: int) -> AccountSession:
        playwright = self._import_playwright()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_path(account_id)),
            headless=True,
        )
        return PlaywrightSession(context, playwright)

    def _active_page(self, session: AccountSession):
        if session.context.pages:
            return session.context.pages[0]
        return session.context.new_page()

    def is_owned(self, session: AccountSession, game: GameCandidate) -> bool:
        page = self._active_page(session)
        page.goto(game.url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        text = page.inner_text("body").lower()
        condition = _is_security_condition(text)
        if condition == Outcome.INTERVENTION:
            raise InterventionRequiredError("captcha detected during ownership check")
        if condition == Outcome.RATE_LIMITED:
            raise RateLimitError("rate limited during ownership check")
        return "in library" in text

    def claim(self, session: AccountSession, game: GameCandidate) -> ClaimResult:
        page = self._active_page(session)
        page.goto(game.url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        text = page.inner_text("body").lower()
        condition = _is_security_condition(text)
        if condition == Outcome.INTERVENTION:
            raise InterventionRequiredError("captcha detected during claim")
        if condition == Outcome.RATE_LIMITED:
            raise RateLimitError("rate limited during claim")

        if "in library" in text:
            return ClaimResult(outcome=Outcome.ALREADY_OWNED)
        if "get" in text:
            page.click("text=Get", timeout=15000)
            page.wait_for_timeout(3000)
            confirmed = page.inner_text("body").lower()
            if "in library" in confirmed or "owned" in confirmed:
                return ClaimResult(outcome=Outcome.CLAIMED)
            return ClaimResult(outcome=Outcome.TRANSIENT, error="claim not confirmed")
        return ClaimResult(outcome=Outcome.ALREADY_OWNED)

    def authenticate(self, account_id: int, mode: str) -> AuthProgress:
        raise NotImplementedError("interactive authentication implemented in auth service")
