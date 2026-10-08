"""#396: menu lifecycle endpoints must drain in-flight writes before closing DB sessions."""
from __future__ import annotations

import pytest

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import web_app
from tests.wait_utils import reset_menu_path_leases, wait_until
from ming_sim.session_write_queue import SessionWriteQueue

# 兼容旧调用名：真源在 wait_utils.reset_menu_path_leases。
_reset_path_leases = reset_menu_path_leases


def _drain_then_archive(game, db_path: str) -> None:
    """测试辅助：登记 holder → 同步 drain → AR-req（生产归档不经 drain 写 pending）。"""
    entry = web_app._register_holder(db_path, game)
    assert entry is not None
    role, op = web_app._claim_close(entry, db_path)
    assert role == "executor" and op is not None
    web_app._drain_and_close_session(game, entry=entry, close_op=op)
    web_app._path_request_archive(db_path)


def test_drain_and_close_session_waits_for_gate_then_closes():
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )

    assert gate.acquire(blocking=False)
    done = threading.Event()

    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(game), done.set()),
        daemon=True,
    )
    thread.start()
    # While the live queue gate is held, drain must not close the session.
    assert not done.is_set()
    assert closed == []

    gate.release()

    done.wait()
    assert closed == [1]
    assert not gate.locked()


def test_exit_to_menu_returns_before_delayed_close_drains(monkeypatch, tmp_path):
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    db_path = str(tmp_path / "exit-delay.db")
    fake_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    _reset_path_leases()
    assert web_app._register_holder(db_path, fake_game) is not None
    monkeypatch.setattr(web_app, "web_game", fake_game)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_exit())

    assert result == {"ok": True}
    assert web_app.web_game is None
    assert closed == []

    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()


def test_new_game_returns_before_delayed_close_drains(monkeypatch, tmp_path):
    """#396: new_game 与 exit_to_menu 同构——界面立刻构建新局返回，
    旧 session 的后台队列在 daemon 线程排空 write_gate 后再关连接（detach）。"""
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    old_db = str(tmp_path / "old_delayed.db")
    Path = __import__("pathlib").Path
    Path(old_db).write_text("old", encoding="utf-8")
    fake_old_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        db_path=old_db,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    _reset_path_leases()
    assert web_app._register_holder(old_db, fake_old_game) is not None
    monkeypatch.setattr(web_app, "web_game", fake_old_game)
    monkeypatch.setenv("MING_SIM_DB", old_db)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh, **_kw: fake_new_game)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    assert closed == []  # 旧 session 尚未关闭（gate 被模拟 worker 持有）

    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()



def test_new_game_failure_restores_old_game_and_main_db_path(monkeypatch, tmp_path):
    """#402 R1（Codex/CodeRabbit）：新局初始化失败时，不退休旧局、不丢旧主库指针。"""
    old_db_path = str(tmp_path / "old_main.db")
    os.makedirs(tmp_path, exist_ok=True)
    with open(old_db_path, "w", encoding="utf-8") as f:
        f.write("old")
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setenv("MING_SIM_DB", old_db_path)
    with open(web_app._active_db_path_file(), "w", encoding="utf-8") as f:
        f.write(old_db_path)

    queue = SessionWriteQueue()
    old_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=queue.write_gate,
        db_path=old_db_path,
        session=SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(web_app, "web_game", old_game)

    # 失败路径不得 spawn drain；勿替换 threading.Thread——new_game 经 run_in_executor，
    # 空 start 会卡死默认线程池。
    drain_spawns: list[object] = []
    real_spawn = web_app._spawn_drain_close

    def _capture_spawn(*a, **k):
        drain_spawns.append(1)
        return real_spawn(*a, **k)

    monkeypatch.setattr(web_app, "_spawn_drain_close", _capture_spawn)

    def fail_new_game(*_args, **_kwargs):
        raise web_app.LLMUnavailable("missing llm")

    monkeypatch.setattr(web_app, "WebGame", fail_new_game)

    try:
        asyncio.run(web_app.api_menu_new_game())
    except web_app.HTTPException as exc:
        assert exc.status_code == 412
    else:
        raise AssertionError("new_game should surface LLMUnavailable as HTTP 412")

    assert web_app.web_game is old_game
    assert os.environ["MING_SIM_DB"] == old_db_path
    with open(web_app._active_db_path_file(), "r", encoding="utf-8") as f:
        assert f.read().strip() == old_db_path
    assert drain_spawns == []


def test_drain_archive_move_failure_keeps_wal_and_shm(monkeypatch, tmp_path):
    """#402 R1（Gemini）：主库 move 失败时不得删除仍属旧库的 WAL/SHM。"""
    db_path = str(tmp_path / "ming_sim.db")
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    for path, content in ((db_path, "db"), (wal_path, "wal"), (shm_path, "shm")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.shutil, "move", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")))

    _reset_path_leases()
    _drain_then_archive(game, db_path)

    assert closed == [1]
    assert os.path.exists(db_path)
    assert os.path.exists(wal_path)
    assert os.path.exists(shm_path)


def test_drain_archive_moves_wal_and_shm_with_main_db(monkeypatch, tmp_path):
    """#402 R2（Gemini）：成功归档主库时，SQLite WAL/SHM 也要随主库进存档目录。"""
    db_path = str(tmp_path / "ming_sim.db")
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    for path, content in ((db_path, "db"), (wal_path, "wal"), (shm_path, "shm")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    closed: list[int] = []
    queue = SessionWriteQueue()
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=queue.write_gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    # #1749：独立可复核——清空活局，禁被前序用例的 MING_SIM_DB 污染。
    monkeypatch.setattr(web_app, "web_game", None)
    monkeypatch.delenv("MING_SIM_DB", raising=False)

    _reset_path_leases()
    _drain_then_archive(game, db_path)

    save_files = list((tmp_path / "saves").glob("*.db"))
    assert closed == [1]
    assert len(save_files) == 1
    archived_db = str(save_files[0])
    assert os.path.exists(archived_db)
    assert os.path.exists(archived_db + "-wal")
    assert os.path.exists(archived_db + "-shm")
    assert not os.path.exists(db_path)
    assert not os.path.exists(wal_path)
    assert not os.path.exists(shm_path)


def test_drain_archive_rolls_back_main_db_when_wal_move_fails(monkeypatch, tmp_path):
    """#402 R3（CodeRabbit）：WAL 归档失败时，主库也要回滚回旧路径，避免存档缺 WAL。"""
    db_path = str(tmp_path / "ming_sim.db")
    wal_path = db_path + "-wal"
    for path, content in ((db_path, "db"), (wal_path, "wal")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    closed: list[int] = []
    queue = SessionWriteQueue()
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=queue.write_gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    real_move = web_app.shutil.move

    def fail_wal_move(src, dst):
        if src == wal_path:
            raise OSError("wal locked")
        return real_move(src, dst)

    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.shutil, "move", fail_wal_move)

    _reset_path_leases()
    _drain_then_archive(game, db_path)

    assert closed == [1]
    assert os.path.exists(db_path)
    assert os.path.exists(wal_path)
    assert list((tmp_path / "saves").glob("*.db")) == []


def test_drain_archive_skips_move_when_session_close_fails(monkeypatch, tmp_path):
    """#402 R2（CodeRabbit）+#1740：旧连接没关成功时上抛原异常，且不移动仍可能被占用的 DB 文件。"""
    db_path = str(tmp_path / "ming_sim.db")
    with open(db_path, "w", encoding="utf-8") as f:
        f.write("db")

    moves: list[tuple[str, str]] = []
    queue = SessionWriteQueue()
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=queue.write_gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("close failed"))),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.shutil, "move", lambda src, dst: moves.append((src, dst)))

    _reset_path_leases()
    entry = web_app._register_holder(db_path, game)
    assert entry is not None
    role, op = web_app._claim_close(entry, db_path)
    assert role == "executor" and op is not None
    with pytest.raises(RuntimeError):
        web_app._drain_and_close_session(game, entry=entry, close_op=op)
    # close 失败不发 AR；即使误发 C7 也被 holder 挡住
    web_app._path_request_archive(db_path)

    assert moves == []
    assert os.path.exists(db_path)
    assert not (tmp_path / "saves").exists()


def test_restore_main_db_path_config_remove_failure_is_loud(monkeypatch, tmp_path):
    """#1749 / ADR 0005：active_db.txt 删除失败须上抛，禁静默改写成 env/default 另一身份。"""
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    active_file = web_app._active_db_path_file()
    with open(active_file, "w", encoding="utf-8") as f:
        f.write(str(tmp_path / "new.db"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "new.db"))
    monkeypatch.setattr(
        web_app.os, "remove",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )

    with pytest.raises(PermissionError):
        web_app._restore_main_db_path_config((False, "", False, ""))

    # 失败后不得把身份改写成默认 ming_sim.db
    with open(active_file, "r", encoding="utf-8") as f:
        assert f.read().strip() == str(tmp_path / "new.db")


def test_new_game_active_write_failure_restores_env_and_old_game(monkeypatch, tmp_path):
    """#402 R2（CodeRabbit）：active_db.txt 写失败也必须回滚已改的 MING_SIM_DB。"""
    old_db_path = str(tmp_path / "old_main.db")
    queue = SessionWriteQueue()
    old_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=queue.write_gate,
        db_path=old_db_path,
        session=SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(web_app, "web_game", old_game)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setenv("MING_SIM_DB", old_db_path)
    monkeypatch.setattr(web_app, "_write_active_db_path", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))

    try:
        asyncio.run(web_app.api_menu_new_game())
    except OSError as exc:
        assert "disk full" in str(exc)
    else:
        raise AssertionError("active_db.txt write failure should surface")

    assert os.environ["MING_SIM_DB"] == old_db_path
    assert web_app.web_game is old_game


def test_shutdown_waits_for_drain_before_returning_or_killing(monkeypatch):
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    killed: list[object] = []
    fake_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "web_game", fake_game)
    monkeypatch.setattr(os, "kill", lambda *args, **kwargs: killed.append(args))
    monkeypatch.setattr(os, "_exit", lambda code=0: killed.append(code))
    monkeypatch.setattr(time, "sleep", lambda *_args: None)

    assert gate.acquire(blocking=False)
    done = threading.Event()

    async def run_shutdown() -> None:
        await web_app.api_menu_shutdown()
        done.set()

    thread = threading.Thread(target=lambda: asyncio.run(run_shutdown()), daemon=True)
    thread.start()
    assert not done.is_set()
    assert closed == []
    assert killed == []

    gate.release()

    done.wait()
    assert closed == [1]
    wait_until(lambda: bool(killed))


def test_shutdown_without_web_game_skips_drain_and_kills(monkeypatch):
    """#402 R1（Sourcery）：web_game 已是 None 时 shutdown 不 drain，仍调度退出。"""
    killed: list[object] = []
    monkeypatch.setattr(web_app, "web_game", None)
    monkeypatch.setattr(web_app, "_drain_and_close_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no drain expected")))
    monkeypatch.setattr(os, "kill", lambda *args, **kwargs: killed.append(args))
    monkeypatch.setattr(os, "_exit", lambda code=0: killed.append(code))
    monkeypatch.setattr(time, "sleep", lambda *_args: None)

    result = asyncio.run(web_app.api_menu_shutdown())

    assert result == {"ok": True}
    wait_until(lambda: bool(killed))


def test_drain_rejects_late_pending_write_before_gate_acquire():
    """#402 R3（Sourcery）：drain 开始后，迟到的旧 game 写入不得再登记进关闭队列。"""
    runtime = object.__new__(web_app.WebGame)
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    closed: list[int] = []
    runtime.session = SimpleNamespace(close=lambda: closed.append(1))

    runtime._write_gate.acquire()
    done = threading.Event()
    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(runtime), done.set()),
        daemon=True,
    )
    thread.start()

    # seal 后 claim 返回 None；探测时若尚未 seal 则 complete 掉误领票据，不为测试补 is_sealed API。
    def _queue_rejects_new_claims() -> bool:
        ticket = runtime._write_queue.claim(("__seal_probe__",))
        if ticket is None:
            return True
        runtime._write_queue.complete(ticket)
        return False

    wait_until(_queue_rejects_new_claims)
    assert runtime._mark_pending_write() is None
    # 屏障票据在等 gate 期间可占 1；新 claim 已拒。
    assert runtime._pending_writes_count <= 1

    runtime._write_gate.release()

    done.wait()
    assert closed == [1]


def test_spawn_pending_write_thread_start_failure_releases_ownership():
    """回归（coderabbit #1087 / Gap B）：`_spawn_pending_write_thread` 标 pending 后若
    `Thread.start()` 抛异常，须补偿 `_complete_pending_write` 再上抛——否则 pending 泄漏、
    drain 在 `_drain_cond` 永阻、关档/重置/加载挂死。断言异常上抛且计数归 0（无泄漏）。"""
    runtime = object.__new__(web_app.WebGame)
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore

    class _FailingThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("线程池耗尽（模拟 start 失败）")

    orig_thread = web_app.threading.Thread
    web_app.threading.Thread = _FailingThread
    try:
        raised = False
        try:
            runtime._spawn_pending_write_thread(lambda **_k: None, (), "t")
        except RuntimeError:
            raised = True
        assert raised, "start() 抛异常须上抛，不静默吞掉"
    finally:
        web_app.threading.Thread = orig_thread

    assert runtime._pending_writes_count == 0  # pending ownership 未泄漏


# ── #396 Step5 R4: web_game is None 时 new_game 仍须切换库路径 ───────────

def test_new_game_switches_db_path_when_web_game_is_none(monkeypatch, tmp_path):
    """#396 Step5 R4 P1 + #1732 T1: web_game is None（退菜单后 / 服务端首次启动）时，new_game
    仍必须切换主库路径到新文件；无活 session 时仍把旧主库归档进 saves/（同一权威实现）。"""
    import sqlite3

    old_db_path = str(tmp_path / "old_configured.db")
    conn = sqlite3.connect(old_db_path, check_same_thread=False)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO kv_store VALUES ('data', 'before_new_game')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(web_app, "web_game", None)
    monkeypatch.setenv("MING_SIM_DB", old_db_path)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    _reset_path_leases()

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh, **_kw: fake_new_game)

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    # env 已切到新路径
    new_path = os.environ["MING_SIM_DB"]
    assert new_path != old_db_path
    # active_db.txt 也已切到新路径
    with open(web_app._active_db_path_file(), "r", encoding="utf-8") as f:
        assert f.read().strip() == new_path
    # #1732 T1：无活 session 也归档旧主库
    wait_until(lambda: not os.path.exists(old_db_path))
    saves_dir = tmp_path / "saves"
    save_files = list(saves_dir.glob("*.db"))
    assert len(save_files) == 1
    check = sqlite3.connect(str(save_files[0]))
    rows = dict(check.execute("SELECT key, value FROM kv_store").fetchall())
    check.close()
    assert rows["data"] == "before_new_game"
    # 归档名可被存档扫描与 load 名校验接受
    scanned = web_app._scan_saves()
    assert len(scanned) == 1
    assert scanned[0]["name"] == save_files[0].stem


def test_new_game_switches_db_path_when_web_game_none_and_no_env(monkeypatch, tmp_path):
    """#396 Step5 R4: 服务端启动后 web_game=None 且无 MING_SIM_DB env，首次 new_game 也须
    切换到新库路径（覆写 env + active_db.txt），不让 fresh=True 在默认路径建库。"""
    monkeypatch.setattr(web_app, "web_game", None)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh, **_kw: fake_new_game)

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    new_path = os.environ["MING_SIM_DB"]
    assert "ming_sim_" in os.path.basename(new_path)  # 新 timestamped 路径
    assert new_path != str(tmp_path / "ming_sim.db")  # 不是默认路径
    with open(web_app._active_db_path_file(), "r", encoding="utf-8") as f:
        assert f.read().strip() == new_path
