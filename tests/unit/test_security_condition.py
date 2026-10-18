from app.integrations.epic_adapter import Outcome
from app.integrations.epic_playwright import _is_security_condition
from tests.fakes import FakeEpicAdapter


def test_cloudflare_challenge_is_classified_as_intervention():
    text = "One more step | Please complete a security check to continue | Session ID"
    assert _is_security_condition(text) == Outcome.INTERVENTION


def test_plain_negative_page_is_not_security():
    assert _is_security_condition("No free games right now") is None


def test_captcha_marker_is_intervention():
    assert _is_security_condition("Please verify you are human") == Outcome.INTERVENTION


def test_rate_limit_is_rate_limited():
    assert _is_security_condition("too many requests") == Outcome.RATE_LIMITED


def test_fake_adapter_accepts_discovery_profile_arg():
    adapter = FakeEpicAdapter(games=[])
    assert adapter.discover_free_games() == []
    assert adapter.discover_free_games(profile_account_id=1) == []
