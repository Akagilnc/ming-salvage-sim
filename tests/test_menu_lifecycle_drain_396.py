"""#396: menu lifecycle endpoints must drain in-flight writes before closing DB sessions."""
from __future__ import annotations

import pytest

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import web_app
from tests.web_audience_test_doubles import HallAdmissionSessionMixin, minister_double
from tests.wait_utils import wait_until


def test_drain_and_close_session_waits_for_gate_then_closes():
    from ming_sim.session_write_queue import get_session_write_queue

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
    # Prove drain reached barrier/close acquire while gate held — not start-race is_set.
    wait_until(lambda: get_session_write_queue(game).has_open_barrier())
    assert not done.is_set()
    assert closed == []

    gate.release()

    done.wait()
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

    wait_until(lambda: closed == [1])
    assert not gate.locked()


def test_new_game_returns_before_delayed_close_drains(monkeypatch, tmp_path):
    """#396: new_game 与 exit_to_menu 同构——界面立刻构建新局返回，
    旧 session 的后台队列在 daemon 线程排空 write_gate 后再关连接（detach）。"""
    gate = threading.Lock()
    closed: list[int] = []
    fake_old_game = SimpleNamespace(
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "web_game", fake_old_game)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    assert closed == []  # 旧 session 尚未关闭（gate 被模拟 worker 持有）

    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()


def test_new_game_switches_db_path_and_archives_old_after_drain(monkeypatch, tmp_path):
    """#396 completeness: new_game must not delete or rename the old DB under a still-writing
    background worker. It switches the main DB path to a new file so fresh=True doesn't clobber it.
    The old worker continues writing to the old DB file safely. After drain, the old DB is archived."""
    import sqlite3

    db_path = str(tmp_path / "ming_sim.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
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

    wait_until(lambda: closed == [1])
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


def test_get_main_db_path_prefers_active_db_over_launch_env(monkeypatch, tmp_path):
    """#402 R1（Codex）：重启后 active_db.txt 必须压过启动 env，才能继续 new_game 切出的新主库。"""
    env_db_path = str(tmp_path / "launch_env.db")
    active_db_path = str(tmp_path / "active_from_new_game.db")
    monkeypatch.setenv("MING_SIM_DB", env_db_path)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    with open(web_app._active_db_path_file(), "w", encoding="utf-8") as f:
        f.write(active_db_path)

    assert web_app._get_main_db_path() == active_db_path


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

    old_game = SimpleNamespace(
        _write_gate=threading.Lock(),
        db_path=old_db_path,
        session=SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(web_app, "web_game", old_game)

    started_threads: list[object] = []

    class _ThreadShouldNotStart:
        def __init__(self, *args, **kwargs):
            started_threads.append((args, kwargs))

        def start(self):
            started_threads.append("start")

    monkeypatch.setattr(web_app.threading, "Thread", _ThreadShouldNotStart)

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
    assert started_threads == []


def test_drain_archive_move_failure_keeps_wal_and_shm(monkeypatch, tmp_path):
    """#402 R1（Gemini）：主库 move 失败时不得删除仍属旧库的 WAL/SHM。"""
    db_path = str(tmp_path / "ming_sim.db")
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    for path, content in ((db_path, "db"), (wal_path, "wal"), (shm_path, "shm")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    gate = threading.Lock()
    closed: list[int] = []
    game = SimpleNamespace(
        _write_gate=gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.shutil, "move", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")))

    web_app._drain_and_close_session(game, archive_db=True)

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
    game = SimpleNamespace(
        _write_gate=threading.Lock(),
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    web_app._drain_and_close_session(game, archive_db=True)

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
    game = SimpleNamespace(
        _write_gate=threading.Lock(),
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

    web_app._drain_and_close_session(game, archive_db=True)

    assert closed == [1]
    assert os.path.exists(db_path)
    assert os.path.exists(wal_path)
    assert list((tmp_path / "saves").glob("*.db")) == []


def test_drain_archive_skips_move_when_session_close_fails(monkeypatch, tmp_path):
    """#402 R2（CodeRabbit）：旧连接没关成功时，不移动仍可能被占用的 DB 文件。"""
    db_path = str(tmp_path / "ming_sim.db")
    with open(db_path, "w", encoding="utf-8") as f:
        f.write("db")

    moves: list[tuple[str, str]] = []
    game = SimpleNamespace(
        _write_gate=threading.Lock(),
        db_path=db_path,
        session=SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("close failed"))),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.shutil, "move", lambda src, dst: moves.append((src, dst)))

    web_app._drain_and_close_session(game, archive_db=True)

    assert moves == []
    assert os.path.exists(db_path)
    assert not (tmp_path / "saves").exists()


def test_restore_main_db_path_config_ignores_active_remove_failure(monkeypatch, tmp_path):
    """#402 R2/R3：active_db.txt 删除失败时，不遮蔽原错，且回写有效主库路径。"""
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    active_file = web_app._active_db_path_file()
    with open(active_file, "w", encoding="utf-8") as f:
        f.write(str(tmp_path / "new.db"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "new.db"))
    monkeypatch.setattr(web_app.os, "remove", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")))

    web_app._restore_main_db_path_config((False, "", False, ""))

    assert "MING_SIM_DB" not in os.environ
    with open(active_file, "r", encoding="utf-8") as f:
        assert f.read().strip() == str(tmp_path / "ming_sim.db")


def test_new_game_active_write_failure_restores_env_and_old_game(monkeypatch, tmp_path):
    """#402 R2（CodeRabbit）：active_db.txt 写失败也必须回滚已改的 MING_SIM_DB。"""
    old_db_path = str(tmp_path / "old_main.db")
    old_game = SimpleNamespace(
        _write_gate=threading.Lock(),
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
    from ming_sim.session_write_queue import get_session_write_queue

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
    wait_until(lambda: get_session_write_queue(fake_game).has_open_barrier())
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


# ── Gap A: MING_SIM_DB 配置路径下 new_game 不删旧库 ────────────────────────

def test_new_game_with_ming_sim_db_env_does_not_clobber_old_configured_db(monkeypatch, tmp_path):
    """#396 Gap A: MING_SIM_DB 指定的旧库路径下，new_game 仍立刻返回、不删旧库（旧后台 worker
    仍写）、排空后旧库归档为可读存档。env 优先级不再让 active_db.txt 切换失效——new_game 同步
    覆写 env 到新路径，fresh=True 只删新路径，旧 worker 续写旧库。"""
    import sqlite3

    env_db_path = str(tmp_path / "env_configured.db")
    conn = sqlite3.connect(env_db_path, check_same_thread=False)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO kv_store VALUES ('data', 'before_new_game')")
    conn.commit()

    gate = threading.Lock()
    closed: list[int] = []
    fake_old_game = SimpleNamespace(
        _write_gate=gate,
        db_path=env_db_path,
        session=SimpleNamespace(close=lambda: (closed.append(1), conn.close())),
    )
    monkeypatch.setattr(web_app, "web_game", fake_old_game)
    monkeypatch.setenv("MING_SIM_DB", env_db_path)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    gate.acquire()  # 模拟旧后台 worker 持锁

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    assert os.path.exists(env_db_path)  # 旧 env 库未被删
    assert os.environ["MING_SIM_DB"] != env_db_path  # env 已切到新路径

    conn.execute("INSERT INTO kv_store VALUES ('reply', 'background_minister_reply')")
    conn.commit()

    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()

    save_files = list((tmp_path / "saves").glob("*.db"))
    assert len(save_files) == 1
    assert not os.path.exists(env_db_path)  # 旧库已归档移走

    check = sqlite3.connect(str(save_files[0]))
    rows = dict(check.execute("SELECT key, value FROM kv_store").fetchall())
    check.close()
    assert rows["data"] == "before_new_game"
    assert rows["reply"] == "background_minister_reply"


# ── Gap B: drain 须等排队等 gate 的旧召对 worker ──────────────────────────

class _GapBRunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class _GapBRunCompleted:
    content = ""
    tools = []


class _GapBAgent:
    def __init__(self, allow_finish: threading.Event):
        self.allow_finish = allow_finish

    def run(self, *_args, **_kwargs):
        yield _GapBRunContent("臣已知悉。")
        self.allow_finish.wait()
        yield _GapBRunCompleted()


class _GapBRegistry:
    session_ids: dict = {}

    def __init__(self, agents: dict):
        self.agents = agents

    def get(self, character):
        return self.agents[character.name]


class _GapBSession(HallAdmissionSessionMixin):
    temporary_characters: set = set()

    def __init__(self, characters, agents, state, db):
        self.state = state
        self.db = db
        self.content = SimpleNamespace(characters=characters)
        self.registry = _GapBRegistry(agents)

    def _character(self, name):
        return self.content.characters[name]

    def _start_cli_action_intent(self, *_a, **_k):
        return None

    def _finish_cli_action_intent(self, *_a, **_k):
        return None

    def apply_cli_conversation_actions(self, *_a, **_k):
        return {"directive": None, "secret_order_id": 0, "pending_action_id": 0}

    def pending_count(self):
        return 0

    # #542 scene lifecycle seams — production chat_stream/_start_chat_turn call these.
    def start_chat_turn_scene(self, *_a, **_k):
        return None

    def start_chat_turn_exit_scene(self, *_a, **_k):
        return None

    def join_chat_turn_scene(self, *_a, **_k):
        return []

    def persist_chat_turn_scene(self, *_a, **_k):
        return None

    def abandon_chat_turn_scene(self, *_a, **_k):
        return None


class _GapBDB:
    def __init__(self):
        self.messages: list[dict] = []
        self._next_id = 1

    def agno_runs_length(self, _session_id):
        return 0

    def capture_chat_rollback_snapshot(self):
        return {}

    def create_chat_turn(self, *_a, **_k):
        return 7

    def append_chat_message(self, minister_name, turn, role, content):
        self.messages.append(
            {"minister": minister_name, "turn": int(turn), "role": role, "content": content})
        row_id = self._next_id
        self._next_id += 1
        return row_id

    def update_chat_turn_messages(self, *_a, **_k):
        return None

    def persist_minister_reply(self, minister_name, turn, content, chat_turn_id):
        # #499 单一事务插入回话+链接+接受（本 stub 复用 append 记账，返回其 id）
        return self.append_chat_message(minister_name, turn, "minister", content)

    def record_chat_turn_rollback_diffs(self, *_a, **_k):
        return None

    def get_last_active_chat_turn(self, *_a, **_k):
        return None

    def fail_chat_turn(self, *_a, **_k):
        return None

    def load_all_chat_history(self):
        result: dict = {}
        for m in self.messages:
            result.setdefault(m["minister"], []).append(
                {"role": m["role"], "content": m["content"]})
        return result


@pytest.mark.usefixtures("_atomic_connless_test_shell_compat")
def test_drain_waits_for_queued_chat_stream_not_just_gate_holder():
    """#396 Gap B: drain 不能只等当前持锁 worker——已排队（阻塞在 gate.acquire()）的旧召对请求
    也须先跑完写库，drain 才关 session。否则 drain 抢到下一轮 acquire 直接关连接，排队请求要么
    永不跑、要么写 closed database。"""
    allow_finish_a = threading.Event()
    allow_finish_b = threading.Event()
    closed: list[int] = []

    char_a = minister_double("大臣甲")
    char_b = minister_double("大臣乙")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _GapBDB()

    runtime = object.__new__(web_app.WebGame)
    runtime.session = _GapBSession(
        {char_a.name: char_a, char_b.name: char_b},
        {char_a.name: _GapBAgent(allow_finish_a), char_b.name: _GapBAgent(allow_finish_b)},
        state, db)
    runtime.session.close = lambda: closed.append(1)
    runtime.chat_history = {char_a.name: [], char_b.name: []}
    from ming_sim.session_write_queue import SessionWriteQueue
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda _c: []
    runtime.can_undo_last_chat = lambda _name: False

    # A 持锁跑流式召对
    stream_a = runtime.chat_stream(char_a.name, "请奏A")
    first_a = next(stream_a)
    assert first_a == {"type": "delta", "content": "臣已知悉。"}

    # B 排队等 gate（独立线程 next → 阻塞在 gate.acquire()）
    b_events: list[dict] = []

    def run_b():
        stream_b = runtime.chat_stream(char_b.name, "请奏B")
        for item in stream_b:
            b_events.append(item)
            if item.get("type") in ("done", "error"):
                break

    thread_b = threading.Thread(target=run_b, daemon=True)
    thread_b.start()

    # B 已进入 chat_stream 体（mark 后 counter >= 2）
    wait_until(lambda: runtime._pending_writes_count >= 2)

    # drain 启动（须等 B 跑完才关）
    drain_done = threading.Event()

    def run_drain():
        web_app._drain_and_close_session(runtime)
        drain_done.set()

    thread_drain = threading.Thread(target=run_drain, daemon=True)
    thread_drain.start()
    # Prove drain entered barrier while B ticket still open.
    wait_until(lambda: runtime._write_queue.has_open_barrier())
    assert not drain_done.is_set(), "drain 在排队 B 跑完前就关了连接"

    # A 完成 → 释放 gate → B 拿到锁开始跑
    allow_finish_a.set()
    wait_until(lambda: any(e.get("type") == "delta" for e in b_events))

    # B 仍持锁（agent 阻塞在 allow_finish_b）→ drain 仍未关
    assert runtime._write_queue.has_open_barrier()
    assert not drain_done.is_set(), "drain 在 B 仍持锁时关了连接"

    allow_finish_b.set()

    drain_done.wait()
    assert closed == [1]
    assert not runtime._write_gate.locked()

    # B 回奏已入档（关连接前写完）
    assert any(m["minister"] == char_b.name and m["role"] == "minister"
               and "臣已知悉" in m["content"] for m in db.messages)


def test_drain_rejects_late_pending_write_before_gate_acquire():
    """#402 R3（Sourcery）：drain 开始后，迟到的旧 game 写入不得再登记进关闭队列。"""
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    from ming_sim.session_write_queue import SessionWriteQueue
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

    wait_until(lambda: runtime._write_queue.is_sealed())
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
    from ming_sim.session_write_queue import SessionWriteQueue
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
    # 无进行中的 exit detach
    monkeypatch.setattr(web_app, "_menu_exit_detach_done", None)

    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

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
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    new_path = os.environ["MING_SIM_DB"]
    assert "ming_sim_" in os.path.basename(new_path)  # 新 timestamped 路径
    assert new_path != str(tmp_path / "ming_sim.db")  # 不是默认路径
    with open(web_app._active_db_path_file(), "r", encoding="utf-8") as f:
        assert f.read().strip() == new_path


def test_new_game_after_exit_does_not_clobber_old_db_while_detach_drains(monkeypatch, tmp_path):
    """#396 Step5 R4 P1 + #1732 T1 完整路径：退菜单→web_game=None+detach drain 写旧库→
    new_game 须切到新库路径，不与仍写的 detach 抢搬；排空关闭后旧库归档进 saves/。
    exit_to_menu 本身不搬库——「继续上局」在仅 exit 时仍可见主库。"""
    import sqlite3

    old_db_path = str(tmp_path / "old_configured.db")
    conn = sqlite3.connect(old_db_path)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO kv_store VALUES ('data', 'before_exit')")
    conn.commit()

    closed: list[int] = []
    gate = threading.Lock()
    fake_old_game = SimpleNamespace(
        _write_gate=gate,
        db_path=old_db_path,
        session=SimpleNamespace(close=lambda: (closed.append(1), conn.close())),
    )
    monkeypatch.setattr(web_app, "web_game", fake_old_game)
    monkeypatch.setenv("MING_SIM_DB", old_db_path)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    # 退菜单：web_game=None，detach drain 启动（gate 被持 = 旧 worker 在写旧库）
    gate.acquire()
    asyncio.run(web_app.api_menu_exit())
    assert web_app.web_game is None
    # #1732 T1：exit 本身不搬主库——继续上局仍可见
    assert os.path.exists(old_db_path)
    assert web_app._has_main_db()

    # new_game：web_game=None，但仍须切到新库路径
    fake_new_game = SimpleNamespace(state_payload=lambda: {"turn": 1})
    monkeypatch.setattr(web_app, "WebGame", lambda fresh: fake_new_game)
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    result = asyncio.run(web_app.api_menu_new_game())

    assert "state" in result
    assert web_app.web_game is fake_new_game
    assert os.environ["MING_SIM_DB"] != old_db_path  # 已切到新路径
    assert os.path.exists(old_db_path)  # 旧库未被删——detach worker 仍可安全续写

    # 旧 detach drain 仍写旧库（gate 释放后 close 才跑）
    conn.execute("INSERT INTO kv_store VALUES ('reply', 'detach_reply')")
    conn.commit()
    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()
    # #1732 T1：排空关闭后旧库归档，含迟到后台回奏；可被存档列表看见
    wait_until(lambda: not os.path.exists(old_db_path))
    save_files = list((tmp_path / "saves").glob("*.db"))
    assert len(save_files) == 1
    check = sqlite3.connect(str(save_files[0]))
    rows = dict(check.execute("SELECT key, value FROM kv_store").fetchall())
    check.close()
    assert rows["data"] == "before_exit"
    assert rows["reply"] == "detach_reply"
    scanned = web_app._scan_saves()
    assert any(s["name"] == save_files[0].stem for s in scanned)
