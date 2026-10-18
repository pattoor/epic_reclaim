import json

import pytest

from app.integrations import epic_oauth
from app.integrations.epic_oauth import EpicOAuthError


@pytest.fixture
def http_calls(monkeypatch):
    calls = []

    def fake_form(url, headers, data):
        calls.append({"kind": "form", "url": url, "headers": headers, "data": data})
        return {
            "access_token": "at-token",
            "refresh_token": "re-token",
            "account_id": "acct-1",
            "display_name": "Epic User",
        }

    def fake_get_json(url, headers):
        calls.append({"kind": "get", "url": url, "headers": headers})
        return {"code": "exch-1"}

    monkeypatch.setattr(epic_oauth, "_http_form", fake_form)
    monkeypatch.setattr(epic_oauth, "_http_get_json", fake_get_json)
    return calls


def test_auth_page_url_points_to_login_with_launcher_redirect():
    url = epic_oauth.auth_page_url()
    assert url.startswith("https://www.epicgames.com/id/login?redirectUrl=")
    assert epic_oauth.CLIENT_ID in url
    assert "responseType%3Dcode" in url


def test_exchange_authorization_code_uses_launcher_credentials(http_calls):
    tokens = epic_oauth.exchange_authorization_code("abc-123")

    call = http_calls[0]
    assert call["kind"] == "form"
    assert call["url"].startswith(f"https://{epic_oauth.OAUTH_HOST}/account/api/oauth/token")
    auth_header = call["headers"]["Authorization"]
    assert auth_header.startswith("Basic ")
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == "abc-123"
    assert call["data"]["token_type"] == "eg1"
    assert tokens["access_token"] == "at-token"


def test_refresh_tokens_uses_refresh_grant(http_calls):
    tokens = epic_oauth.refresh_tokens("re-token")
    assert http_calls[0]["data"]["grant_type"] == "refresh_token"
    assert http_calls[0]["data"]["refresh_token"] == "re-token"
    assert tokens["account_id"] == "acct-1"


def test_create_exchange_code_uses_bearer_session(http_calls):
    code = epic_oauth.create_exchange_code("at-token")
    call = http_calls[0]
    assert call["kind"] == "get"
    assert call["url"].endswith("/account/api/oauth/exchange")
    assert call["headers"]["Authorization"] == "bearer at-token"
    assert code == "exch-1"


def test_web_exchange_url_encodes_redirect_to_store():
    url = epic_oauth.web_exchange_url("exch-1")
    assert url.startswith("https://www.epicgames.com/id/exchange?exchangeCode=exch-1")
    assert "redirectUrl=" in url
    assert "store.epicgames.com" in url


def test_http_error_becomes_epic_oauth_error(monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url="x", code=400, msg="bad", hdrs=None, fp=None
        )

    monkeypatch.setattr(epic_oauth.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(EpicOAuthError):
        epic_oauth.exchange_authorization_code("bad")


def test_session_tokens_roundtrip(tmp_path):
    profile = tmp_path / "session"
    profile.mkdir()
    tokens = {"refresh_token": "re-token", "account_id": "acct-1", "display_name": "Epic User"}

    epic_oauth.save_session_tokens(str(profile), tokens)
    stored = json.loads((profile / "epic_session.json").read_text(encoding="utf-8"))
    # Only session material lives in the file; access tokens are never written.
    assert stored["refresh_token"] == "re-token"
    assert "access_token" not in stored

    assert epic_oauth.load_refresh_token(str(profile)) == "re-token"
    epic_oauth.delete_session_tokens(str(profile))
    assert epic_oauth.load_refresh_token(str(profile)) is None


def test_load_refresh_token_missing_profile_is_none(tmp_path):
    assert epic_oauth.load_refresh_token(str(tmp_path)) is None


def test_extract_authorization_code_accepts_raw_launcher_json():
    raw = (
        '{"warning":"Do not share this code with any 3rd party service. It allows full access to your Epic account.",'
        '"redirectUrl":"https://localhost/launcher/authorized?code=abc123",'
        '"authorizationCode":"abc123","exchangeCode":null,"sid":null}'
    )
    assert epic_oauth.extract_authorization_code(raw) == "abc123"


def test_extract_authorization_code_passes_plain_code_through():
    assert epic_oauth.extract_authorization_code(" abc123 ") == "abc123"


def test_extract_authorization_code_unknown_json_returns_as_is():
    raw = '{"other": "value"}'
    assert epic_oauth.extract_authorization_code(raw) == raw
