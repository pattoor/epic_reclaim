import threading

from app.services.locks import FileRunLock, MultiRunLock


def test_file_lock_is_exclusive(tmp_path):
    lock = FileRunLock(tmp_path / "run.lock")
    assert lock.acquire() is True
    assert lock.acquire() is False
    lock.release()
    assert lock.acquire() is True
    lock.release()


def test_file_lock_rejects_stale_lockfile(tmp_path):
    import os
    import time as time_module

    path = tmp_path / "run.lock"
    path.write_text("stale")
    stale = time_module.time() - (60 * 60 * 3)
    os.utime(path, (stale, stale))

    lock = FileRunLock(path, stale_after_seconds=2 * 60 * 60)
    assert lock.acquire() is True
    lock.release()


def test_multi_lock_releases_acquired_on_failure(tmp_path):
    first = FileRunLock(tmp_path / "a.lock")
    second = FileRunLock(tmp_path / "b.lock")
    second.acquire()
    combined = MultiRunLock(first, second)
    assert combined.acquire() is False
    # first was acquired then rolled back: it must be free again
    assert first.acquire() is True
    first.release()
    second.release()


def test_multi_lock_acquires_both(tmp_path):
    combined = MultiRunLock(FileRunLock(tmp_path / "a.lock"), FileRunLock(tmp_path / "b.lock"))
    assert combined.acquire() is True
    assert FileRunLock(tmp_path / "a.lock").acquire() is False
    combined.release()
    assert FileRunLock(tmp_path / "a.lock").acquire() is True
