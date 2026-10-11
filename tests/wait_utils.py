from __future__ import annotations
import asyncio
import threading
from typing import Callable
import time
"""Test-owned rendezvous polling and lock observer for concurrency tests (#1723)."""



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
