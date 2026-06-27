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


def test_new_game_switches_db_path_and_archives_old_after_drain(monkeypatch, tmp_path):
    """#396 completeness: new_game must not delete or rename the old DB under a still-writing
    background worker. It switches the main DB path to a new file so fresh=True doesn't clobber it.
    The old worker continues writing to the old DB file safely. After drain, the old DB is archived."""
    import sqlite3

    db_path = str(tmp_path / "ming_sim.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO kv_store VALUES ('data', 'before_new_game')")
    conn.commit()

    gate = threading.Lock()
    closed: list[int] = []
    fake_old_game = SimpleNamespace(
        _write_gate=gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: (closed.append(1), conn.close())),
    )
    monkeypatch.setattr(web_app, "web_game", fake_old_game)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.delenv("MING_SIM_DB", raising=False)

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    gate.acquire()  # simulate in-flight background worker

    result = asyncio.run(web_app.api_menu_new_game())

    # Returns immediately with new game
    assert "state" in result
    assert web_app.web_game is fake_new_game

    # Old DB file is NOT deleted or renamed, so the old worker can write to it safely
    assert os.path.exists(db_path)

    # Background worker writes through the old (still-open) connection
    conn.execute("INSERT INTO kv_store VALUES ('reply', 'background_minister_reply')")
    conn.commit()

    gate.release()  # worker finishes → drain proceeds

    assert _wait_for(lambda: closed == [1])
    assert not gate.locked()

    # Old DB is moved to saves/ after the drain finishes
    saves_dir = tmp_path / "saves"
    save_files = list(saves_dir.glob("*.db"))
    assert len(save_files) == 1
    assert not os.path.exists(db_path)  # moved out of the original path

    # Archived save contains both old data and the background-written reply
    check = sqlite3.connect(str(save_files[0]))
    rows = dict(check.execute("SELECT key, value FROM kv_store").fetchall())
    check.close()
    assert rows["data"] == "before_new_game"
    assert rows["reply"] == "background_minister_reply"


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
