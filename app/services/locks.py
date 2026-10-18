"""Run locking: in-process thread lock plus optional cross-process file lock.

The web mode (scheduler + API) and the console CLI run in separate processes
of the same container, so the classic in-memory RunLock alone is not enough.
A small O_EXCL file lock with stale detection closes that gap; the combined
lock is what the shared bootstrap wires into the workflow.

Invariant: acquire() returns True for exactly one holder; a failed acquire
must never be followed by release() (MultiRunLock tracks its own state).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

STALE_LOCK_SECONDS = 2 * 60 * 60  # a run can hardly exceed two hours


class FileRunLock:
    """Cross-process exclusion via O_EXCL lock file with stale detection."""

    def __init__(self, path: str | Path, stale_after_seconds: int = STALE_LOCK_SECONDS):
        self._path = Path(path)
        self._stale_after = stale_after_seconds

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_if_stale()
        try:
            handle = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, f"pid={os.getpid()} at={int(time.time())}".encode())
            os.close(handle)
            return True
        except FileExistsError:
            return False
        except OSError:
            # Cross-process protection could not be established (fs problems);
            # fall back to the in-process lock but make it loud.
            logger.warning(
                "file_run_lock_unavailable path=%s: falling back to in-process lock",
                self._path,
            )
            return True

    def release(self) -> None:
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass
        except OSError:  # pragma: no cover
            pass

    def _stat(self):
        return os.stat(self._path)

    def _remove_if_stale(self) -> None:
        """Remove a stale lockfile without ever deleting a fresh lock.

        Classic stat-then-unlink TOCTOU: another process may release and
        re-acquire the file between our stat and our unlink, and a blind
        unlink would delete its fresh lock leaving two holders. Re-stat and
        compare mtime right before deleting; skip on any difference.
        """
        try:
            stat = self._stat()
        except FileNotFoundError:
            return
        if time.time() - stat.st_mtime <= self._stale_after:
            return
        try:
            recheck = self._stat()
            if recheck.st_mtime != stat.st_mtime:
                return  # concurrent re-creation; treat as alive
            self._path.unlink()
        except FileNotFoundError:
            return
        except OSError:  # pragma: no cover - fs problems
            return


class MultiRunLock:
    """Combines locks atomically: releases already-acquired ones on failure.

    acquire() -> True/False; release() only has effect when a previous
    acquire() succeeded (tracked in self._acquired), guarding against the
    double-release/never-held pattern.
    """

    def __init__(self, *locks):
        self._locks = locks
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:  # single-holder discipline; never re-enter
            return False
        held: list[int] = []
        for index, lock in enumerate(self._locks):
            if lock.acquire():
                held.append(index)
            else:
                for victim in reversed(held):
                    self._locks[victim].release()
                return False
        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        self._acquired = False
        for lock in self._locks:
            try:
                lock.release()
            except Exception:  # pragma: no cover - defensive
                pass


class ThreadRunLock:
    """Thin wrapper around RunLock for explicit naming; behavior identical."""

    def __init__(self):
        self._thread_lock = threading.Lock()

    def acquire(self) -> bool:
        return self._thread_lock.acquire(blocking=False)

    def release(self) -> None:
        self._thread_lock.release()
