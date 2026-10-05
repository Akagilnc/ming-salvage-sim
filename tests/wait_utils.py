"""Shared unbounded poll helper and lock observer for concurrency tests (#1723).

Permanent hang is owned by the CI job final line — not by a test-local deadline.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Callable


def wait_until(predicate: Callable[[], bool]) -> None:
    """Poll until predicate is true. Backoff only; not a correctness deadline."""
    poll = threading.Event()
    while True:
        if predicate():
            return
        poll.wait(0.01)


async def _await_condition_or_task(
    predicate: Callable[[], bool], task: asyncio.Task,
) -> None:
    """成功谓词或 worker 终态均可唤醒；worker 异常原样传播，不把失败藏成挂起。

    谓词与 task 同时终态时仍消费 task 异常——不得因谓词先真而吞掉 worker 失败。
    """
    while not predicate() and not task.done():
        await asyncio.sleep(0)
    if task.done():
        exc = task.exception()
        if exc is not None:
            raise exc
        if not predicate():
            raise AssertionError("worker finished without expected condition")
        return
    # 谓词已真且 task 仍在跑（如 started 后 hang on allow）——成功会合。


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
