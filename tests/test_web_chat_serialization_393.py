from __future__ import annotations

import pytest

import asyncio
import json
import threading
from types import SimpleNamespace

import web_app
from tests.web_audience_test_doubles import HallAdmissionSessionMixin
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order
from tests.wait_utils import wait_until
from ming_sim.session_write_queue import SessionWriteQueue


class _RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:
    content = ""
    tools = []


class _FakeAgent:
    def __init__(self, allow_finish: threading.Event):
        self.allow_finish = allow_finish

    def run(self, *args, **kwargs):
        yield _RunContent("臣已知悉。")
        self.allow_finish.wait()
        yield RunCompletedEvent()


class _SecretOrderAgent:
    """A streamed tool result, matching the WebGame tool-result boundary."""

    def __init__(self, result: str):
        self.result = result

    def run(self, *args, **kwargs):
        yield _RunContent("臣已领密旨。")
        completed = RunCompletedEvent()
        completed.tools = [SimpleNamespace(tool_name="secret_order", result=self.result)]
        yield completed


class _FakeSession(HallAdmissionSessionMixin):
    temporary_characters = set()

    def __init__(self, character, agent: _FakeAgent, state, db):
        self.state = state
        self.db = db
        self.content = SimpleNamespace(characters={character.name: character})
        self._agent = agent

    def _character(self, minister_name: str):
        return self.content.characters[minister_name]


    def _merge_staged_new_secret_order_content(self, *args, **kwargs):
        return None

    def pending_count(self):
        return 0

    def scene_chat(self, message, *, chat_turn_id=0, stream_emit=None, minister_name="", on_protagonist_changed=None):
        # #1849 reopen：殿上入口不绑单人 character；轻壳直接驱动假 agent。
        from ming_sim.session import ChatTurnResult

        agent = self._agent
        parts: list[str] = []
        for event in agent.run():
            content = getattr(event, "content", None)
            if content:
                parts.append(str(content))
                if stream_emit is not None:
                    stream_emit(str(content))
        return ChatTurnResult(answer="".join(parts))

    def schedule_pending_scene_translation(self, result):
        # #1842：WebGame persist 尾必调；轻壳无 pending 时 no-op（与生产同形入口）。
        from ming_sim.session import GameSession
        return GameSession.schedule_pending_scene_translation(self, result)
    def can_summon(self, character):
        # #1402：web _require_active_minister 改调 session.can_summon——假壳挂真方法，禁自造文案表
        from ming_sim.session import GameSession
        return GameSession.can_summon(self, character)


class _RecordingDB:
    def __init__(self, settlement_holding: threading.Event):
        self.settlement_holding = settlement_holding
        self.messages = []
        self.overlapped_minister_commit = False
        self._next_id = 1

    def agno_runs_length(self, session_id: str) -> int:
        return 0

    def capture_chat_rollback_snapshot(self):
        return {}

    def create_chat_turn(self, state, minister_name, agno_session_id, agno_runs_before):
        return 7

    def append_chat_message(self, minister_name: str, turn: int, role: str, content: str) -> int:
        if role == "minister" and self.settlement_holding.is_set():
            self.overlapped_minister_commit = True
        self.messages.append({"minister": minister_name, "turn": int(turn), "role": role, "content": content})
        row_id = self._next_id
        self._next_id += 1
        return row_id

    def update_chat_turn_messages(self, *args, **kwargs):
        return None

    def persist_minister_reply(
        self, minister_name: str, turn: int, content: str, chat_turn_id: int, **_kw,
    ):
        # 同事务回话；stub 只记账 message id
        return self.append_chat_message(minister_name, turn, "minister", content)

    def fail_chat_turn(self, *_a, **_k):
        # 流式失败尾声 / identity 失败路径会调此口
        return None

    def record_chat_turn_rollback_diffs(self, *args, **kwargs):
        return None

    def get_last_active_chat_turn(self, minister_name: str, turn: int):
        return None

    def list_in_flight_chat_turns(self, *, night_id=None, minister_name=None, turn=None):
        return []

    def build_chat_projection(self, minister_name: str):
        # #499 单一投影出口（无读心记录的最小实现，供 done payload 装配）
        return [
            {"role": m["role"], "content": m["content"], "chat_turn_id": 0}
            for m in self.messages
            if m["minister"] == minister_name
        ]

    def set_message_highlights(self, message_id: int, phrases):
        # #544 生产接口；chat_stream 尾随高亮会调此口（#567 r3 替身补齐）
        return None

    def get_character_status(self, *_a, **_k):
        # #1402 can_summon 真源依赖：轻壳默认 active
        return ("active", "")

    def resolve_power_id(self, character):
        # #1402 can_summon 真源依赖：轻壳无 characters 表，回落同真源默认 ming
        return getattr(character, "power_id", "ming") or "ming"

    def list_pending_actions(self, turn, *a, **k):
        # #1716：_chat_payload 经 pending_directive_count 读此口；轻壳无拟旨暂存
        return []

    def load_all_chat_history(self):
        out: dict[str, list] = {}
        for m in self.messages:
            out.setdefault(m["minister"], []).append({"role": m["role"], "content": m["content"]})
        return out

    def kv_get(self, _key):
        return ""

    def list_secret_orders(self):
        return []


def _runtime_for_stream_race():
    allow_finish = threading.Event()
    settlement_attempting = threading.Event()
    settlement_holding = threading.Event()
    settlement_release = threading.Event()
    character = SimpleNamespace(name="测试大臣")
    agent = _FakeAgent(allow_finish)
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _RecordingDB(settlement_holding)

    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(character, agent, state, db)
    runtime.chat_history = {character.name: [], "殿上": []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.can_undo_last_chat = lambda minister_name: False
    runtime.pending_directive_count = lambda: 0

    def settlement():
        settlement_attempting.set()
        with runtime._write_gate:
            settlement_holding.set()
            runtime.state.turn = 2
            settlement_release.wait()  # hold gate until test releases (no wall clock)
            settlement_holding.clear()

    settlement.holding = settlement_holding  # type: ignore[attr-defined]
    settlement.release_event = settlement_release  # type: ignore[attr-defined]
    return runtime, character.name, allow_finish, settlement_attempting, settlement


@pytest.mark.usefixtures("_atomic_connless_test_shell_compat")
def test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn():
    runtime, minister_name, allow_finish, settlement_attempting, settlement = _runtime_for_stream_race()

    stream = runtime.chat_stream("殿上", "请奏")
    first = next(stream)
    assert first.get("type") == "delta"  # 控序：先 delta；不锁流式散文

    settlement_thread = threading.Thread(target=settlement)
    settlement_thread.start()
    settlement_attempting.wait()
    settlement.holding.wait()

    done_box: list = []
    done_collected = threading.Event()

    def _take_done() -> None:
        done_box.append(next(stream))
        done_collected.set()

    threading.Thread(target=_take_done, daemon=True).start()
    allow_finish.set()
    try:
        assert settlement.holding.is_set(), "settlement released before epilogue"
        assert not done_collected.is_set(), "done arrived before settlement released gate"
    finally:
        settlement.release_event.set()
    done_collected.wait()
    done = done_box[0]
    settlement_thread.join()

    assert done["type"] == "done"
    assert runtime.db.overlapped_minister_commit is False
    minister_messages = [msg for msg in runtime.db.messages if msg["role"] == "minister"]
    assert minister_messages and minister_messages[-1]["turn"] == 1
    assert runtime.state.turn == 2


def test_identity_setup_failure_preserves_question_and_releases_pending_owner():
    runtime, minister_name, _allow_finish, _settlement_attempting, _settlement = _runtime_for_stream_race()
    failed = []
    completed = []
    runtime.db.kv_get = lambda _key: (_ for _ in ()).throw(RuntimeError("identity read failed"))
    runtime._fail_chat_turn_and_reload = lambda turn_id, snapshot, error: failed.append((turn_id, snapshot, error))
    runtime._complete_pending_write = lambda ticket=None: completed.append(True)

    events = list(runtime.chat_stream("殿上", "请奏"))

    assert events[0]["type"] == "error"
    assert events[0]["chat_turn_id"] == 7
    assert events[0]["campaign_id"] == "" and events[0]["night_id"] == 0
    assert failed[0][:2] == (7, {})
    user_msgs = [m for m in runtime.db.messages if m["role"] == "user"]
    assert len(user_msgs) == 1  # 失败仍保留问话轮；角色条数结构，不锁问话散文
    assert completed == [True]


@pytest.mark.usefixtures("_atomic_connless_test_shell_compat")
def test_lightweight_stream_seam_reaches_done_without_durable_identity_or_night_signature():
    runtime, minister_name, allow_finish, _settlement_attempting, _settlement = _runtime_for_stream_race()
    stream = runtime.chat_stream("殿上", "请奏")
    assert next(stream)["type"] == "delta"
    allow_finish.set()
    assert next(stream)["type"] == "done"


def test_chat_stream_sse_waits_for_sync_generator_in_executor(monkeypatch):
    events: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    class _BlockingGame:
        def chat_stream(self, minister_name: str, message: str):
            entered.set()
            release.wait()  # block until tick observed entry (no wall clock)
            events.append("stream")
            yield {"type": "done", "payload": {"ok": True}}

    monkeypatch.setattr(web_app, "_require_active_minister", lambda minister_name: None)
    monkeypatch.setattr(web_app, "get_game", lambda: _BlockingGame())

    async def drive_first_event():
        response = await web_app.api_audience_chat_stream( web_app.ChatRequest(message="请奏"))
        iterator = response.body_iterator

        async def tick():
            await asyncio.to_thread(entered.wait)
            events.append("tick")
            release.set()

        first_event, _ = await asyncio.gather(iterator.__anext__(), tick())
        return first_event

    first = asyncio.run(drive_first_event())

    assert events == ["tick", "stream"]
    assert "event: done" in first


def test_nonstream_api_chat_keeps_game_state_responsive_while_chat_blocks(monkeypatch):
    """#1291+#1322: 非流式 chat 同步慢 LLM 在飞时，并发 GET /api/game/state 须在阈内响应。

    根因：async api_audience_chat 在事件循环上直调全同步 get_game().chat()（→ subprocess.run），
    整站 loop 卡死。对照流式端点 run_in_executor / directives to_thread——本测咬死卸载后
    的可观测序：state 探针先于阻塞 chat 完成。
    """
    events: list[str] = []
    chat_entered = threading.Event()
    allow_finish = threading.Event()

    class _SlowLLMGame:
        """离线慢 LLM 替身：chat_stream 进入后保持阻塞，直至 state 探针完成。"""

        def chat_stream(self, minister_name: str, message: str):
            chat_entered.set()
            allow_finish.wait()
            events.append("chat")
            yield {"type": "done", "payload": {"answer": "臣已知悉。"}}

        def state_payload(self):
            events.append("state")
            return {"ok": True, "turn": 1}

    monkeypatch.setattr(web_app, "get_game", lambda: _SlowLLMGame())

    async def drive_concurrent_state_probe():
        async def state_probe():
            await asyncio.to_thread(chat_entered.wait)
            try:
                payload = await web_app.api_state()
                # 先落成功标记再放行：set() 先执行则 chat 线程可先记 "chat"，
                # 与外部断言的严格顺序无 happens-before（#1722 判牒）。
                events.append("state_done")
            finally:
                # api_state 抛错也须放行 chat worker，否则 threadpool 永久阻塞。
                allow_finish.set()
            return payload

        chat_result, state_payload = await asyncio.gather(
            web_app.api_audience_chat(web_app.ChatRequest(message="边饷如何？")),
            state_probe(),
        )
        return chat_result, state_payload

    chat_result, state_payload = asyncio.run(drive_concurrent_state_probe())

    assert events == ["state", "state_done", "chat"], (
        f"event loop 被非流式 chat 冻结（events={events}）；"
        "期望 state 探针在 chat 完成前响应"
    )
    assert state_payload == {"ok": True, "turn": 1}


def test_nonstream_chat_rejects_when_session_draining():
    """drain 已开始时非流式 chat 不得再登记 pending——对齐 stream 拒绝路，HTTP 503。"""
    from fastapi import HTTPException

    character = SimpleNamespace(name="测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _RecordingDB(threading.Event())
    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(character, _FakeAgent(threading.Event()), state, db)
    runtime.chat_history = {character.name: [], "殿上": []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_queue.seal()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore

    events = list(runtime.chat_stream("殿上", "边饷如何？"))
    assert events and events[0].get("type") == "error"
    assert runtime._pending_writes_count == 0
