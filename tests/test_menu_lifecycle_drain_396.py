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


# ── Gap A: MING_SIM_DB 配置路径下 new_game 不删旧库 ────────────────────────

def test_new_game_with_ming_sim_db_env_does_not_clobber_old_configured_db(monkeypatch, tmp_path):
    """#396 Gap A: MING_SIM_DB 指定的旧库路径下，new_game 仍立刻返回、不删旧库（旧后台 worker
    仍写）、排空后旧库归档为可读存档。env 优先级不再让 active_db.txt 切换失效——new_game 同步
    覆写 env 到新路径，fresh=True 只删新路径，旧 worker 续写旧库。"""
    import sqlite3

    env_db_path = str(tmp_path / "env_configured.db")
    conn = sqlite3.connect(env_db_path)
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

    assert _wait_for(lambda: closed == [1])
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
        assert self.allow_finish.wait(2.0), "gapB agent timed out"
        yield _GapBRunCompleted()


class _GapBRegistry:
    session_ids: dict = {}

    def __init__(self, agents: dict):
        self.agents = agents

    def get(self, character):
        return self.agents[character.name]


class _GapBSession:
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


def test_drain_waits_for_queued_chat_stream_not_just_gate_holder():
    """#396 Gap B: drain 不能只等当前持锁 worker——已排队（阻塞在 gate.acquire()）的旧召对请求
    也须先跑完写库，drain 才关 session。否则 drain 抢到下一轮 acquire 直接关连接，排队请求要么
    永不跑、要么写 closed database。"""
    allow_finish_a = threading.Event()
    allow_finish_b = threading.Event()
    closed: list[int] = []

    char_a = SimpleNamespace(name="大臣甲")
    char_b = SimpleNamespace(name="大臣乙")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _GapBDB()

    runtime = object.__new__(web_app.WebGame)
    runtime.session = _GapBSession(
        {char_a.name: char_a, char_b.name: char_b},
        {char_a.name: _GapBAgent(allow_finish_a), char_b.name: _GapBAgent(allow_finish_b)},
        state, db)
    runtime.session.close = lambda: closed.append(1)
    runtime.chat_history = {char_a.name: [], char_b.name: []}
    runtime._write_gate = threading.Lock()
    runtime._drain_cond = threading.Condition()
    runtime._pending_writes_count = 0
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
    assert _wait_for(lambda: runtime._pending_writes_count >= 2), \
        f"B 未进入排队；counter={runtime._pending_writes_count}"

    # drain 启动（须等 B 跑完才关）
    drain_done = threading.Event()

    def run_drain():
        web_app._drain_and_close_session(runtime)
        drain_done.set()

    thread_drain = threading.Thread(target=run_drain, daemon=True)
    thread_drain.start()

    assert not drain_done.wait(0.2), "drain 在排队 B 跑完前就关了连接"

    # A 完成 → 释放 gate → B 拿到锁开始跑
    allow_finish_a.set()
    assert _wait_for(lambda: any(e.get("type") == "delta" for e in b_events), timeout=2.0), \
        "B 未拿到 gate 开始跑"

    # B 仍持锁（agent 阻塞在 allow_finish_b）→ drain 仍未关
    assert not drain_done.wait(0.05), "drain 在 B 仍持锁时关了连接"

    allow_finish_b.set()

    assert drain_done.wait(2.0), "drain 未在 B 完成后关连接"
    assert closed == [1]
    assert not runtime._write_gate.locked()

    # B 回奏已入档（关连接前写完）
    assert any(m["minister"] == char_b.name and m["role"] == "minister"
               and "臣已知悉" in m["content"] for m in db.messages)
