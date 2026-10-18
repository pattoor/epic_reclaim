from app.integrations.epic_playwright import PlaywrightEpicAdapter, free_games_url
from app.domain.errors import TransientError


def test_free_games_url_with_locale_pins_domain():
    assert free_games_url("es-AR") == "https://store.epicgames.com/es-AR/free-games"
    assert free_games_url("en-US") == "https://store.epicgames.com/en-US/free-games"


def test_free_games_url_empty_locale_uses_ip_region():
    assert free_games_url("") == "https://store.epicgames.com/free-games"
    assert free_games_url(None) == "https://store.epicgames.com/free-games"


def test_adapter_uses_configured_locale():
    adapter = PlaywrightEpicAdapter("./sessions", locale="es-AR")
    assert adapter._free_games_url == "https://store.epicgames.com/es-AR/free-games"

    adapter_default = PlaywrightEpicAdapter("./sessions")
    assert adapter_default._free_games_url == "https://store.epicgames.com/free-games"
