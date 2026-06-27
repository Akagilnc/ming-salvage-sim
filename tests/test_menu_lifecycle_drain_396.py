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
