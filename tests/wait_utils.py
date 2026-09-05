"""Shared unbounded poll helper and lock observer for concurrency tests (#1723).

Permanent hang is owned by the CI job final line — not by a test-local deadline.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


def wait_until(predicate: Callable[[], bool]) -> None:
    """Poll until predicate is true. Backoff only; not a correctness deadline."""
    poll = threading.Event()
    while True:
        if predicate():
            return
        poll.wait(0.01)


class ObservingLock:
    """Test-side Lock drop-in: signals contending when acquire finds the lock held
    (or optional holding event is set). No production hooks; not a general framework.
    """

    def __init__(
        self,
        contending: threading.Event,
        *,
        holding: Optional[threading.Event] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._contending = contending
        self._holding = holding

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._holding is not None and self._holding.is_set():
            self._contending.set()
        if self._lock.acquire(blocking=False):
            return True
        self._contending.set()
        if not blocking:
            return False
        if timeout is None or timeout < 0:
            return self._lock.acquire(blocking=True)
        return self._lock.acquire(blocking=True, timeout=timeout)

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args) -> bool:
        self.release()
        return False
