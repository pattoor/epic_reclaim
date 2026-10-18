import os
import time

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


def test_multi_lock_release_without_acquire_is_noop(tmp_path):
    combined = MultiRunLock(FileRunLock(tmp_path / "c.lock"))
    combined.release()  # must not raise nor free a never-held lock
    lock = FileRunLock(tmp_path / "c.lock")
    assert lock.acquire() is True
    lock.release()


def test_stale_removal_does_not_delete_freshly_reacquired_lock(tmp_path):
    """TOCTOU guard: if between our stat and our unlink another process
    re-created the lock, the unlink must be skipped (fresh lock survives)."""
    path = tmp_path / "run.lock"
    stale_mtime = time.time() - (60 * 60 * 3)
    fresh_mtime = time.time()
    path.write_text("stale-holder")
    os.utime(path, (stale_mtime, stale_mtime))

    class RacyLock(FileRunLock):
        """Re-stamps the file to fresh between the two internal reads."""

        def __init__(self, target):
            super().__init__(target, stale_after_seconds=60)
            self._reads = 0

        def _stat(self):
            self._reads += 1
            if self._reads > 1:
                path.write_text("fresh-holder")
                os.utime(path, (fresh_mtime, fresh_mtime))
            return os.stat(path)

    racy = RacyLock(path)
    racy._remove_if_stale()  # must NOT unlink the recreated fresh lock
    with open(path) as handle:
        assert handle.read() == "fresh-holder"
    # and acquiring must fail because the fresh holder owns it
    assert racy.acquire() is False
    with open(path) as handle:
        assert handle.read() == "fresh-holder"
