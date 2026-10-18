"""Run locking: in-process thread lock plus optional cross-process file lock.

The web mode (scheduler + API) and the console CLI run in separate processes
of the same container, so the classic in-memory RunLock alone is not enough.
A small O_EXCL file lock with stale detection closes that gap; the combined
lock is what the shared bootstrap wires into the workflow.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

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
        except OSError:  # pragma: no cover - fs problems should not kill runs
            return True

    def release(self) -> None:
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass
        except OSError:  # pragma: no cover
            pass

    def _remove_if_stale(self) -> None:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            return
        if time.time() - stat.st_mtime > self._stale_after:
            try:
                self._path.unlink()
            except OSError:  # pragma: no cover
                return


class MultiRunLock:
    """Combines locks atomically: releases already-acquired ones on failure."""

    def __init__(self, *locks):
        self._locks = locks

    def acquire(self) -> bool:
        acquired: list[int] = []
        for index, lock in enumerate(self._locks):
            if lock.acquire():
                acquired.append(index)
            else:
                for held in reversed(acquired):
                    self._locks[held].release()
                return False
        return True

    def release(self) -> None:
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
