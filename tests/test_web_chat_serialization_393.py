from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import web_app
from tests.web_audience_test_doubles import HallAdmissionSessionMixin
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
        assert self.allow_finish.wait(timeout=5)
        yield RunCompletedEvent()


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


def _runtime_for_stream_race(monkeypatch, game):
    allow_finish = threading.Event()
    settlement_attempting = threading.Event()
    settlement_holding = threading.Event()
    settlement_release = threading.Event()
    db, state, content = game
    state.turn_phase = "summoning"
    character = content.characters["毕自严"]
    agent = _FakeAgent(allow_finish)

    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(character, agent, state, db)
    runtime.session.content = content
    runtime.chat_history = {character.name: [], "殿上": []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime.session._write_queue = runtime._write_queue
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.can_undo_last_chat = lambda minister_name: False
    runtime.pending_directive_count = lambda: 0

    def settlement():
        settlement_attempting.set()
        with runtime._write_gate:
            settlement_holding.set()
            runtime.state.turn = 2
            assert settlement_release.wait(timeout=5)
            settlement_holding.clear()

    settlement.holding = settlement_holding  # type: ignore[attr-defined]
    settlement.release_event = settlement_release  # type: ignore[attr-defined]
    return runtime, character.name, allow_finish, settlement_attempting, settlement


def test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn(monkeypatch, game):
    runtime, minister_name, allow_finish, settlement_attempting, settlement = _runtime_for_stream_race(monkeypatch, game)

    accepted_turn = int(runtime.state.turn)
    stream = runtime.chat_stream("殿上", "请奏")
    first = next(stream)
    assert first["type"] == "accepted"
    assert next(stream)["type"] == "delta"

    settlement_thread = threading.Thread(target=settlement)
    settlement_thread.start()
    assert settlement_attempting.wait(timeout=5)
    assert settlement.holding.wait(timeout=5)

    done_box: list = []
    done_collected = threading.Event()

    def _take_done() -> None:
        while True:
            item = next(stream)
            if item.get("type") == "done":
                done_box.append(item)
                done_collected.set()
                return

    threading.Thread(target=_take_done, daemon=True).start()
    allow_finish.set()
    try:
        assert settlement.holding.is_set(), "settlement released before epilogue"
        assert not done_collected.is_set(), "done arrived before settlement released gate"
        assert runtime.db.reign.read_chat_turn(first["chat_turn_id"])["minister_message_id"] is None
    finally:
        settlement.release_event.set()
    assert done_collected.wait(timeout=5)
    done = done_box[0]
    settlement_thread.join(timeout=5)
    assert not settlement_thread.is_alive()

    assert done["type"] == "done"
    replied = runtime.db.reign.read_chat_turn(first["chat_turn_id"])
    reply = runtime.db.conn.execute("SELECT turn FROM chat_messages WHERE id=?", (replied["minister_message_id"],)).fetchone()
    assert reply["turn"] == accepted_turn
    assert runtime.state.turn == 2


def test_identity_setup_failure_preserves_question_and_releases_pending_owner(monkeypatch, game):
    runtime, *_ = _runtime_for_stream_race(monkeypatch, game)
    fault = RuntimeError("identity read failed")
    def fail(_key):
        raise fault
    monkeypatch.setattr(runtime.db.reign, "kv_get", fail)
    events = list(runtime.chat_stream("殿上", "请奏"))
    assert len(events) == 1 and events[0]["type"] == "error"
    turn_id = events[0]["chat_turn_id"]
    row = runtime.db.reign.read_chat_turn(turn_id)
    assert row["status"] == "interrupted" and row["user_message_id"] > 0
    question = runtime.db.conn.execute("SELECT content FROM chat_messages WHERE id=?", (row["user_message_id"],)).fetchone()
    assert question["content"] == "请奏"
    assert runtime._write_queue.inflight_count() == 0


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
    assert chat_result["answer"] == "臣已知悉。"


def test_nonstream_chat_rejects_when_session_draining(game):
    from fastapi import HTTPException
    character = SimpleNamespace(name='测试大臣')
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase='summoning')
    db, state, _ = game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(character, _FakeAgent(threading.Event()), state, db)
    runtime.chat_history = {character.name: [], '殿上': []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_queue.seal()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ('pending',))
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)
    events = list(runtime.chat_stream('殿上', '边饷如何？'))
    assert events and events[0].get('type') == 'error'
    assert runtime._write_queue.inflight_count() == 0
