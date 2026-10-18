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
from app.integrations.profile_locks import clear_stale_profile_locks

FREE_GAMES_PATH = "https://store.epicgames.com/free-games"


def free_games_url(locale: str = "") -> str:
    """Registry URL for the Free Games section.

    A configured locale pins the store domain (deterministic claims); an
    empty locale relies on Epic's IP-based region resolution.
    """
    locale = (locale or "").strip()
    if locale:
        return f"https://store.epicgames.com/{locale}/free-games"
    return FREE_GAMES_PATH

_NON_ELIGIBLE = ("coming soon", "unavailable", "demo", "free to play")
_PAID_CTA = ("buy", "add to cart", "purchase", "pre-order", "preorder", "checkout")
_FREE_SIGNAL = ("free", "get", "add to library")
_PRICE_RE = re.compile(r"(?:\$|€|£)\s*\d")
_SECURITY_MARKERS = (
    "captcha",
    "verify you are human",
    "verify you're human",
)  # explicit human checks
_CHALLENGE_MARKERS = (
    "one more step",
    "security check",
    "confirming you are not a bot",
    "checking your browser",
)  # proxy/anti-bot challenges (e.g. Cloudflare)


def _is_security_condition(page_text: str, status_title: str = "") -> str | None:
    lowered = page_text.lower()
    title = status_title.lower()
    if any(marker in lowered for marker in _SECURITY_MARKERS) or "captcha" in title:
        return Outcome.INTERVENTION
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
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


def classify_playwright_error(error: Exception) -> Exception:
    name = type(error).__name__.lower()
    message = str(error).lower()
    if any(marker in name or marker in message for marker in ("timeout", "network", "connection")):
        return TransientError("temporary Playwright or network failure")
    return error


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
    def __init__(self, sessions_path: str, locale: str = "", base_url: str | None = None):
        self._sessions_path = Path(sessions_path)
        self._locale = (locale or "").strip()
        self._free_games_url = base_url or free_games_url(self._locale)

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

    def discover_free_games(self, profile_account_id: int | None = None) -> list[GameCandidate]:
        try:
            with self._import_playwright() as playwright:
                if profile_account_id is not None:
                    # Reuse the user's own persistent profile (cookies created
                    # by the manual interactive login) for store browsing.
                    profile = self._profile_path(profile_account_id)
                    clear_stale_profile_locks(profile)
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(profile),
                        headless=True,
                    )
                    try:
                        return self._scrape_free_games(context)
                    finally:
                        context.close()
                else:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        return self._scrape_free_games(browser.new_context())
                    finally:
                        browser.close()
        except (InterventionRequiredError, RateLimitError, TransientError):
            raise
        except Exception as error:
            raise classify_playwright_error(error) from error

    def _scrape_free_games(self, context) -> list[GameCandidate]:
        page = context.new_page()
        page.goto(self._free_games_url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        title = page.title().strip()
        page_text = page.inner_text("body")
        condition = _is_security_condition(page_text, status_title=title)
        if condition == Outcome.INTERVENTION:
            raise InterventionRequiredError(
                "store security challenge during discovery (requires manual login)"
            )
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
        # Fallback: when the offer cards change, classify the failure instead
        # of silently returning zero games.
        if not offers:
            lower = page_text.lower()
            if "free games" not in lower and "juegos gratis" not in lower:
                raise InterventionRequiredError(
                    "free-games page not in expected format (selectors need review)"
                )
        return candidates

    def open_account_session(self, account_id: int) -> AccountSession:
        playwright = self._import_playwright()
        try:
            profile = self._profile_path(account_id)
            clear_stale_profile_locks(profile)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=True,
            )
            return PlaywrightSession(context, playwright)
        except Exception as error:
            playwright.stop()
            raise classify_playwright_error(error) from error

    def _active_page(self, session: AccountSession):
        if session.context.pages:
            return session.context.pages[0]
        return session.context.new_page()

    def is_owned(self, session: AccountSession, game: GameCandidate) -> bool:
        try:
            page = self._active_page(session)
            page.goto(game.url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            text = page.inner_text("body").lower()
            condition = _is_security_condition(text)
            if condition == Outcome.INTERVENTION:
                raise InterventionRequiredError("captcha detected during ownership check")
            if condition == Outcome.RATE_LIMITED:
                raise RateLimitError("rate limited during ownership check")
            return _has_library_marker(page)
        except (InterventionRequiredError, RateLimitError):
            raise
        except Exception as error:
            raise classify_playwright_error(error) from error

    def claim(self, session: AccountSession, game: GameCandidate) -> ClaimResult:
        try:
            page = self._active_page(session)
            page.goto(game.url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            text = page.inner_text("body").lower()
            condition = _is_security_condition(text)
            if condition == Outcome.INTERVENTION:
                raise InterventionRequiredError("captcha detected during claim")
            if condition == Outcome.RATE_LIMITED:
                raise RateLimitError("rate limited during claim")

            if _has_library_marker(page):
                return ClaimResult(outcome=Outcome.ALREADY_OWNED)
            cta = _find_get_cta(page)
            if cta is None:
                return ClaimResult(outcome=Outcome.TRANSIENT, error="claim CTA not found")
            cta.click(timeout=15000)
            page.wait_for_timeout(3000)
            if _has_library_marker(page):
                return ClaimResult(outcome=Outcome.CLAIMED)
            return ClaimResult(outcome=Outcome.TRANSIENT, error="claim not confirmed")
        except (InterventionRequiredError, RateLimitError):
            raise
        except Exception as error:
            raise classify_playwright_error(error) from error

    def authenticate(self, account_id: int, mode: str) -> AuthProgress:
        raise NotImplementedError("interactive authentication implemented in auth service")


def _has_library_marker(page) -> bool:
    for locator in (
        page.get_by_role("button", name="In Library", exact=True),
        page.get_by_text("In Library", exact=True),
    ):
        try:
            if locator.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def _find_get_cta(page):
    for locator in (
        page.get_by_role("button", name="Get", exact=True),
        page.get_by_text("Get", exact=True),
    ):
        try:
            if locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None
