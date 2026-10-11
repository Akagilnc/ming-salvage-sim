"""Test-owned rendezvous polling and lock observer for concurrency tests (#1723)."""
from __future__ import annotations

import threading
import time
from typing import Callable


def wait_until(predicate: Callable[[], bool]) -> None:
    """Bound test observations without changing production waiting semantics."""
    poll = threading.Event()
    deadline = time.monotonic() + 1
    while not predicate():
        remaining = deadline - time.monotonic()
        assert remaining > 0, "test rendezvous was not reached"
        poll.wait(min(0.01, remaining))


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
