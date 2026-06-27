"""#396: menu lifecycle endpoints must drain in-flight writes before closing DB sessions."""
from __future__ import annotations

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import web_app


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    poll = threading.Event()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        poll.wait(0.01)
    return predicate()


def test_drain_and_close_session_waits_for_gate_then_closes():
    gate = threading.Lock()
    closed: list[int] = []
    game = SimpleNamespace(
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )

    gate.acquire()
    done = threading.Event()

    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(game), done.set()),
        daemon=True,
    )
    thread.start()

    assert not done.wait(0.2)
    assert closed == []

    gate.release()

    assert done.wait(2.0)
    assert closed == [1]
    assert not gate.locked()


def test_exit_to_menu_returns_before_delayed_close_drains(monkeypatch):
    gate = threading.Lock()
    closed: list[int] = []
    fake_game = SimpleNamespace(
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "web_game", fake_game)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_exit())

    assert result == {"ok": True}
    assert web_app.web_game is None
    assert closed == []

    gate.release()

    assert _wait_for(lambda: closed == [1])
    assert not gate.locked()


def test_new_game_returns_before_delayed_close_drains(monkeypatch):
    """#396: new_game 与 exit_to_menu 同构——界面立刻构建新局返回，
    旧 session 的后台队列在 daemon 线程排空 write_gate 后再关连接（detach）。"""
    gate = threading.Lock()
    closed: list[int] = []
    fake_old_game = SimpleNamespace(
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "web_game", fake_old_game)

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    assert closed == []  # 旧 session 尚未关闭（gate 被模拟 worker 持有）

    gate.release()

    assert _wait_for(lambda: closed == [1])
    assert not gate.locked()


def test_shutdown_waits_for_drain_before_returning_or_killing(monkeypatch):
    gate = threading.Lock()
    closed: list[int] = []
    killed: list[object] = []
    fake_game = SimpleNamespace(
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "web_game", fake_game)
    monkeypatch.setattr(os, "kill", lambda *args, **kwargs: killed.append(args))
    monkeypatch.setattr(os, "_exit", lambda code=0: killed.append(code))
    monkeypatch.setattr(time, "sleep", lambda *_args: None)

    gate.acquire()
    done = threading.Event()

    async def run_shutdown() -> None:
        await web_app.api_menu_shutdown()
        done.set()

    thread = threading.Thread(target=lambda: asyncio.run(run_shutdown()), daemon=True)
    thread.start()

    assert not done.wait(0.3)
    assert closed == []
    assert killed == []

    gate.release()

    assert done.wait(3.0)
    assert closed == [1]
    assert _wait_for(lambda: bool(killed))
