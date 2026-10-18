"""Epic account OAuth helpers for the code-based login flow (D10).

The user logs in from any device's browser (phone or PC) at Epic's official
page; Epic shows a one-time authorization code; this module exchanges it for
account tokens and produces a web exchange code the profile browser uses to
settle the SSO session. Client credentials are the public Epic Games
Launcher ones (the same defaults every open-source Epic client ships).

Tokens are session material: they are stored ONLY next to the account
profile on the server volume, never in the database, logs or backups.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OAUTH_HOST = "account-public-service-prod03.ol.epicgames.com"
# Public Epic Games Launcher client (also shipped by legendary/Heroic).
CLIENT_ID = "34a02cf8f4414e29b15921876da36f9a"
CLIENT_SECRET = "daafbccc737745039dffe53d94fc76cf"

_SESSION_FILE = "epic_session.json"


class EpicOAuthError(Exception):
    """Raised when Epic's OAuth endpoints reject the flow."""


def auth_page_url() -> str:
    """Login URL the user opens on any device; Epic then shows the code."""
    redirect = (
        "https://www.epicgames.com/id/api/redirect"
        f"?clientId={CLIENT_ID}&responseType=code"
    )
    return f"https://www.epicgames.com/id/login?redirectUrl={urllib.parse.quote(redirect, safe='')}"


def web_exchange_url(exchange_code: str) -> str:
    return (
        "https://www.epicgames.com/id/exchange"
        f"?exchangeCode={urllib.parse.quote(exchange_code)}"
        "&redirectUrl=https%3A%2F%2Fstore.epicgames.com%2F"
    )


def _basic_header() -> str:
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _http_form(url: str, headers: dict, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise EpicOAuthError(f"epic oauth http {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EpicOAuthError(f"epic oauth unreachable: {exc}") from exc


def _http_get_json(url: str, headers: dict) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise EpicOAuthError(f"epic oauth http {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EpicOAuthError(f"epic oauth unreachable: {exc}") from exc


def _token_request(grant_params: dict) -> dict:
    tokens = _http_form(
        f"https://{OAUTH_HOST}/account/api/oauth/token",
        {
            "Authorization": _basic_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        {"token_type": "eg1", **grant_params},
    )
    if "access_token" not in tokens:
        raise EpicOAuthError(f"epic oauth rejected the grant: {tokens.get('errorCode', tokens)}")
    return tokens


def exchange_authorization_code(code: str) -> dict:
    return _token_request({"grant_type": "authorization_code", "code": code.strip()})


def refresh_tokens(refresh_token: str) -> dict:
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


def create_exchange_code(access_token: str) -> str:
    payload = _http_get_json(
        f"https://{OAUTH_HOST}/account/api/oauth/exchange",
        {"Authorization": f"bearer {access_token}"},
    )
    code = payload.get("code")
    if not code:
        raise EpicOAuthError(f"epic exchange returned no code: {payload.get('errorCode', payload)}")
    return code


def extract_authorization_code(raw: str) -> str:
    """Accept the raw JSON Epic shows and pull the authorizationCode out of it.

    The final redirect lands on localhost/launcher/authorized (the launcher's
    own callback), so the user's browser just displays Epic's raw JSON. Let
    the user paste that whole JSON or the bare code.
    """
    text = raw.strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            return text
        code = payload.get("authorizationCode")
        return str(code).strip() if code else text
    return text


def save_session_tokens(profile_path: str, tokens: dict) -> None:
    """Persist the refresh token next to the profile (volume-only secret)."""
    directory = Path(profile_path)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _SESSION_FILE
    data = {
        "refresh_token": tokens["refresh_token"],
        "account_id": tokens.get("account_id"),
        "display_name": tokens.get("display_name"),
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_refresh_token(profile_path: str) -> str | None:
    path = Path(profile_path) / _SESSION_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = data.get("refresh_token")
    return token if token else None


def delete_session_tokens(profile_path: str) -> None:
    try:
        (Path(profile_path) / _SESSION_FILE).unlink()
    except OSError:
        pass
