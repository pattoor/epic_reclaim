"""Stale Chromium profile-lock recovery.

Chromium writes SingletonLock/SingletonCookie/SingletonSocket inside a
persistent profile and unlinks them on clean exit. A SIGKILL, an interrupted
authentication session or an image rebuild leaves them behind, and the next
launch aborts with "The profile appears to be in use by another Chromium
process". The helper removes those files only when the lock is demonstrably
stale (the locked pid is not a live browser process for this profile).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

_SINGLETON_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")
_PID_PATTERN = re.compile(r"-(\d+)$")


def _make_pid_is_alive(profile_path: Path) -> Callable[[int], bool]:
    """True only when the pid is a browser process pinned to THIS profile."""

    def pid_is_alive(pid: int) -> bool:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmdline = handle.read()
        except OSError:
            return False
        return ("--user-data-dir=" + str(profile_path)).encode() in cmdline

    return pid_is_alive


def _read_lock_target(lock_path: Path) -> str | None:
    try:
        return os.readlink(lock_path)
    except (OSError, ValueError):
        # Not a symlink: some volume copies turn it into a regular file
        # whose content is still the "hostname-pid" string.
        try:
            return lock_path.read_text().strip()
        except OSError:
            return None


def clear_stale_profile_locks(
    profile_path: Path | str,
    pid_is_alive: Callable[[int], bool] | None = None,
) -> None:
    """Delete Chromium singleton files left by dead processes.

    The caller is responsible for not running two browsers concurrently on the
    same profile (the auth flow enforces a single session); when a browser from
    this host is still running, `pid_is_alive` must keep the files untouched.
    """
    base = Path(profile_path)
    if not base.is_dir():
        return
    if pid_is_alive is None:
        pid_is_alive = _make_pid_is_alive(base)

    lock = base / _SINGLETON_FILES[0]
    if not os.path.lexists(lock):
        return

    stale = False
    target = _read_lock_target(lock)
    if target is None:
        stale = True
    else:
        match = _PID_PATTERN.search(target)
        if match is None:
            stale = True
        else:
            stale = not pid_is_alive(int(match.group(1)))

    if not stale:
        return
    for name in _SINGLETON_FILES:
        candidate = base / name
        try:
            if os.path.lexists(candidate):
                candidate.unlink()
        except OSError:
            pass
