"""Local Chrome window for the manual login fallback (docs/SPECS.md 15).

Runs the login on a GUI machine (the user's PC) when the server-side
remote screen cannot complete the login. The produced profile is then
copied explicitly to the server volume.

Two modes:
- persistent (default): reuses a dedicated profile directory, so Google and
  Epic sessions stay linked across runs (no repeated full verification).
- --fresh: wipes the dedicated profile first (isolated/clean login case).

Compare with the server: never point this at the user's daily Chrome
profile; the folder is copied to the server and must not carry unrelated
sessions (email, banking, etc.).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

LOGIN_URL = "https://www.epicgames.com/id/login"

_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def default_profile_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser(
        "~/AppData/Local"
    )
    # %APPDATA% is Roaming; Chrome-like data fits LocalAppData better.
    local = Path(base).parent / "Local" / "epic_reclaim" / "local_auth_profile"
    return local


def find_chrome() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--profile-dir",
        default=str(default_profile_dir()),
        help="Chrome user-data-dir reused across runs (default: dedicated profile)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="wipe the profile first (isolated login case)",
    )
    args = parser.parse_args(argv)

    chrome = find_chrome()
    if chrome is None:
        print("Chrome not found; adjust _CHROME_CANDIDATES", file=sys.stderr)
        return 1

    profile = Path(args.profile_dir).resolve()
    if args.fresh and profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)

    subprocess.Popen(
        [
            chrome,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-window-check",
            "--window-size=1280,900",
            LOGIN_URL,
        ],
        start_new_session=True,
    )
    print(f"profile: {profile}")
    print(f"url    : {LOGIN_URL}")
    print("Log in as usual; when inside, close Chrome before copying the profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
