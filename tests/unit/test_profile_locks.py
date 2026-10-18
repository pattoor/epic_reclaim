"""Tests de clear_stale_profile_locks (recuperacion de locks Chromium)."""

from pathlib import Path

from app.integrations.profile_locks import clear_stale_profile_locks


def _make_profile(tmp_path: Path, lock_target: str | None) -> Path:
    profile = tmp_path / "profile"
    profile.mkdir()
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        if lock_target is None:
            (profile / name).write_text("")
        else:
            (profile / name).write_text(lock_target)
    return profile


def test_removes_locks_from_dead_process(tmp_path):
    profile = _make_profile(tmp_path, "deadhost-181")

    clear_stale_profile_locks(profile, pid_is_alive=lambda pid: False)

    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        assert (profile / name).exists() is False


def test_keeps_locks_of_live_profile_process(tmp_path):
    profile = _make_profile(tmp_path, "samehost-4242")

    clear_stale_profile_locks(profile, pid_is_alive=lambda pid: pid == 4242)

    assert (profile / "SingletonLock").read_text() == "samehost-4242"


def test_pid_is_alive_rejects_other_processes(tmp_path):
    # default checker: /proc missing in dev => pid considered dead
    profile = _make_profile(tmp_path, "samehost-4242")
    clear_stale_profile_locks(profile)
    assert (profile / "SingletonLock").exists() is False


def test_removes_unparseable_lock(tmp_path):
    profile = _make_profile(tmp_path, "garbage-target")

    clear_stale_profile_locks(profile, pid_is_alive=lambda pid: True)

    assert (profile / "SingletonLock").exists() is False


def test_noop_without_profile(tmp_path):
    clear_stale_profile_locks(tmp_path / "missing")  # no levanta error
