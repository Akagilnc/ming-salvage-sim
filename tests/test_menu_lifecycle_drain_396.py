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
from tests.wait_utils import reset_menu_path_leases, wait_until
from ming_sim.session_write_queue import SessionWriteQueue

# 兼容旧调用名：真源在 wait_utils.reset_menu_path_leases。
_reset_path_leases = reset_menu_path_leases


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
    monkeypatch.setattr(web_app, "web_game", game)
    monkeypatch.setenv("MING_SIM_DB", db_path)
    monkeypatch.setattr(web_app, "WebGame", lambda *_a, **_k: SimpleNamespace(state_payload=lambda: {"turn": 1}))

    _reset_path_leases()
    assert web_app._register_holder(db_path, game) is not None
    asyncio.run(web_app.api_menu_new_game())

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
    monkeypatch.setattr(web_app, "web_game", game)
    monkeypatch.setenv("MING_SIM_DB", db_path)
    monkeypatch.setattr(web_app, "WebGame", lambda *_a, **_k: SimpleNamespace(state_payload=lambda: {"turn": 1}))

    _reset_path_leases()
    assert web_app._register_holder(db_path, game) is not None
    asyncio.run(web_app.api_menu_new_game())
    wait_until(lambda: list((tmp_path / "saves").glob("*.db")))

    save_files = list((tmp_path / "saves").glob("*.db"))
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
    monkeypatch.setattr(web_app, "web_game", game)
    monkeypatch.setenv("MING_SIM_DB", db_path)
    monkeypatch.setattr(web_app, "WebGame", lambda *_a, **_k: SimpleNamespace(state_payload=lambda: {"turn": 1}))

    _reset_path_leases()
    assert web_app._register_holder(db_path, game) is not None
    asyncio.run(web_app.api_menu_new_game())

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
    monkeypatch.setattr(web_app, "web_game", game)
    monkeypatch.setenv("MING_SIM_DB", db_path)
    monkeypatch.setattr(web_app, "WebGame", lambda *_a, **_k: SimpleNamespace(state_payload=lambda: {"turn": 1}))

    _reset_path_leases()
    assert web_app._register_holder(db_path, game) is not None
    asyncio.run(web_app.api_menu_new_game())
    wait_until(lambda: web_app.web_game is not game)

    assert moves == []
    assert os.path.exists(db_path)
    assert list((tmp_path / "saves").glob("*.db")) == []


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
        yield _GapBRunContent("canned-delta")
        self.allow_finish.wait()
        yield _GapBRunCompleted()


class _GapBSession(HallAdmissionSessionMixin):
    temporary_characters: set = set()

    def __init__(self, characters, agents, state, db):
        self.state = state
        self.db = db
        self.content = SimpleNamespace(characters=characters)
        self._agents = agents

    def _character(self, name):
        return self.content.characters[name]


    def pending_count(self):
        return 0

    def scene_chat(self, message, *, chat_turn_id=0, stream_emit=None, minister_name="", on_protagonist_changed=None):
        # #1849 reopen：殿上入口不绑单人 character；轻壳取任一假 agent。
        from ming_sim.session import ChatTurnResult

        agent = self._agents[next(iter(self.content.characters))]
        parts: list[str] = []
        for event in agent.run():
            content = getattr(event, "content", None)
            if content:
                parts.append(str(content))
                if stream_emit is not None:
                    stream_emit(str(content))
        return ChatTurnResult(answer="".join(parts))
    def schedule_pending_scene_translation(self, result):
        # #1842：WebGame persist 尾必调；轻壳无 pending 时 no-op。
        return None


class _GapBDB:
    def __init__(self):
        self.messages: list[dict] = []
        self._next_id = 1
        self._inflight: list[dict] = []
        # 故意不设 conn：生产路径 hasattr(db,"conn") 为假时走轻壳分支

    def agno_runs_length(self, _session_id):
        return 0

    def capture_chat_rollback_snapshot(self):
        return {}

    def create_chat_turn(self, *_a, **_k):
        tid = self._next_id
        self._next_id += 1
        self._inflight.append({"id": tid, "status": "generating", "minister_message_id": None})
        return tid

    def append_chat_message(self, minister_name, turn, role, content):
        self.messages.append(
            {"minister": minister_name, "turn": int(turn), "role": role, "content": content})
        row_id = self._next_id
        self._next_id += 1
        return row_id

    def update_chat_turn_messages(self, *_a, **_k):
        return None

    def persist_minister_reply(self, minister_name, turn, content, chat_turn_id, **_kw):
        # 同事务回话；stub 只记账 message id
        mid = self.append_chat_message(minister_name, turn, "minister", content)
        for row in self._inflight:
            if int(row["id"]) == int(chat_turn_id or 0):
                row["status"] = "active"
                row["minister_message_id"] = mid
        return mid

    def record_chat_turn_rollback_diffs(self, *_a, **_k):
        return None

    def get_last_active_chat_turn(self, *_a, **_k):
        return None

    def fail_chat_turn(self, *_a, **_k):
        return None

    def list_in_flight_chat_turns(self, **_k):
        return [
            row for row in self._inflight
            if row.get("status") == "generating"
            or not row.get("minister_message_id")
        ]

    def kv_get(self, _k):
        return ""

    def list_secret_orders(self):
        return []

    def build_chat_projection(self, minister_name: str):
        return [
            {"role": m["role"], "content": m["content"], "chat_turn_id": 0}
            for m in self.messages
            if m["minister"] == minister_name
        ]

    def list_pending_actions(self, turn, *a, **k):
        return []

    def set_message_highlights(self, message_id, phrases):
        return None

    def load_all_chat_history(self):
        result: dict = {}
        for m in self.messages:
            result.setdefault(m["minister"], []).append(
                {"role": m["role"], "content": m["content"]})
        return result


@pytest.mark.usefixtures("_atomic_connless_test_shell_compat")
def test_drain_waits_for_queued_chat_stream_not_just_gate_holder(monkeypatch):
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
    runtime.chat_history = {char_a.name: [], char_b.name: [], "殿上": []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.can_undo_last_chat = lambda _name: False

    # #1849 reopen：召对只剩殿上；同入口并发第二流被拒，drain 仍须等在飞 A 写完。
    stream_a = runtime.chat_stream("殿上", "请奏A")
    first_a = next(stream_a)
    assert first_a.get("type") == "delta"
    assert "content" in first_a

    b_events = list(runtime.chat_stream("殿上", "请奏B"))
    assert b_events and b_events[-1].get("type") == "error"

    db_path = "gap-b-wait.db"
    runtime.db_path = db_path
    _reset_path_leases()
    assert web_app._register_holder(db_path, runtime) is not None
    monkeypatch.setattr(web_app, "web_game", runtime)

    wait_prior_entered = threading.Event()
    real_wait_prior = runtime._write_queue.wait_prior

    def observe_wait_prior(ticket):
        wait_prior_entered.set()
        return real_wait_prior(ticket)

    runtime._write_queue.wait_prior = observe_wait_prior  # type: ignore[method-assign]

    threading.Thread(target=lambda: asyncio.run(web_app.api_menu_exit()), daemon=True).start()
    wait_prior_entered.wait()
    assert closed == [], "drain 在 A 在飞写完前就关了连接"

    allow_finish_a.set()
    # 消费 A 剩余事件至 end，放行 ticket
    for item in stream_a:
        if item.get("type") in ("done", "error", "end"):
            if item.get("type") == "end":
                break

    wait_until(lambda: closed == [1])
    assert closed == [1]
    assert not runtime._write_gate.locked()

    assert any(
        m["minister"] == "殿上" and m["role"] == "minister"
        for m in db.messages
    )


def test_drain_rejects_late_pending_write_before_gate_acquire(monkeypatch):
    """#402 R3（Sourcery）：drain 开始后，迟到的旧 game 写入不得再登记进关闭队列。"""
    runtime = object.__new__(web_app.WebGame)
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    closed: list[int] = []
    runtime.session = SimpleNamespace(close=lambda: closed.append(1))
    runtime.db_path = "late-claim.db"
    _reset_path_leases()
    assert web_app._register_holder(runtime.db_path, runtime) is not None
    monkeypatch.setattr(web_app, "web_game", runtime)

    runtime._write_gate.acquire()
    threading.Thread(target=lambda: asyncio.run(web_app.api_menu_exit()), daemon=True).start()

    wait_until(lambda: runtime._write_queue.is_sealed())
    assert runtime._write_queue.claim(key=("late",)) is None
    # 屏障票据在等 gate 期间可占 1；新 claim 已拒。
    assert runtime._write_queue.inflight_count() <= 1

    runtime._write_gate.release()

    wait_until(lambda: closed == [1])
    assert closed == [1]


@pytest.mark.usefixtures("_atomic_connless_test_shell_compat")
def test_spawn_pending_write_thread_start_failure_releases_ownership(monkeypatch):
    """回归（coderabbit #1087 / Gap B）：chat_stream 尾随高亮 Thread.start 失败须释放 pending。"""
    allow_finish = threading.Event()
    allow_finish.set()
    char = minister_double("大臣甲")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _GapBDB()
    runtime = object.__new__(web_app.WebGame)
    runtime.session = _GapBSession(
        {char.name: char}, {char.name: _GapBAgent(allow_finish)}, state, db,
    )
    runtime.chat_history = {char.name: [], "殿上": []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.can_undo_last_chat = lambda _name: False

    orig_thread = web_app.threading.Thread

    class _FailHighlightThread:
        def __init__(self, *a, **k):
            self._real = orig_thread(*a, **k)
            self.name = k.get("name") or getattr(self._real, "name", "")

        def start(self):
            if "highlight" in str(self.name):
                raise RuntimeError("线程池耗尽（模拟 start 失败）")
            return self._real.start()

        def join(self, *a, **k):
            return self._real.join(*a, **k)

    monkeypatch.setattr(web_app.threading, "Thread", _FailHighlightThread)

    events = list(runtime.chat_stream("殿上", "请奏"))
    assert events
    wait_until(lambda: runtime._write_queue.inflight_count() == 0)


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
