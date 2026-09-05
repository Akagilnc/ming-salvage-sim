"""Shared unbounded poll helper and lock observer for concurrency tests (#1723).

Permanent hang is owned by the CI job final line — not by a test-local deadline.
"""
from __future__ import annotations

import threading
from typing import Callable


def wait_until(predicate: Callable[[], bool]) -> None:
    """Poll until predicate is true. Backoff only; not a correctness deadline."""
    poll = threading.Event()
    while True:
        if predicate():
            return
        poll.wait(0.01)


def reset_menu_path_leases() -> None:
    """测试夹具：清空菜单路径租约（不经生产钩子；两文件共用，禁重复定义）。"""
    import web_app

    with web_app._menu_path_lock:
        web_app._menu_path_leases.clear()


class ObservingLock:
    """Test-side Lock drop-in: signals contending when acquire finds the lock held.
    No production hooks; not a general framework.
    """

    def __init__(self, contending: threading.Event) -> None:
        self._lock = threading.Lock()
        self._contending = contending

    def acquire(self, blocking: bool = True) -> bool:
        if self._lock.acquire(blocking=False):
            return True
        self._contending.set()
        if not blocking:
            return False
        return self._lock.acquire(blocking=True)

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
