from __future__ import annotations


import asyncio
import threading

import web_app
from tests.wait_utils import _await_condition_or_task
from tests.test_web_audience_night_498 import _FakeAgent
from tests.conftest import stub_scene_agent


def _runtime_for_stream_race(web_game, monkeypatch):
    allow_finish = threading.Event()
    settlement_attempting = threading.Event()
    settlement_holding = threading.Event()
    settlement_release = threading.Event()
    runtime = web_game
    stub_scene_agent(monkeypatch, _FakeAgent(allow=allow_finish, answer="臣已知悉。"))

    def settlement():
        settlement_attempting.set()
        with runtime._write_gate:
            settlement_holding.set()
            runtime.state.turn = 2
            settlement_release.wait()  # hold gate until test releases (no wall clock)
            settlement_holding.clear()

    settlement.holding = settlement_holding  # type: ignore[attr-defined]
    settlement.release_event = settlement_release  # type: ignore[attr-defined]
    return runtime, "殿上", allow_finish, settlement_attempting, settlement


def test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn(web_game, monkeypatch):
    runtime, minister_name, allow_finish, settlement_attempting, settlement = _runtime_for_stream_race(web_game, monkeypatch)

    stream = runtime.chat_stream("殿上", "请奏")
    first = next(stream)
    assert first["type"] == "accepted"
    assert next(stream) == {"type": "delta", "content": "臣已知悉。"}

    settlement_thread = threading.Thread(target=settlement)
    settlement_thread.start()
    settlement_attempting.wait()
    settlement.holding.wait()

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
        assert runtime.db.conn.execute("SELECT COUNT(*) FROM chat_messages WHERE role='minister'").fetchone()[0] == 0
    finally:
        settlement.release_event.set()
    done_collected.wait()
    done = done_box[0]
    settlement_thread.join()

    assert done["type"] == "done"
    minister_messages = runtime.db.conn.execute("SELECT turn, content FROM chat_messages WHERE role='minister'").fetchall()
    assert minister_messages and minister_messages[-1]["turn"] == 1
    assert runtime.state.turn == 2


def test_identity_setup_failure_preserves_question_and_releases_pending_owner(web_game, monkeypatch):
    runtime, minister_name, _allow_finish, _settlement_attempting, _settlement = _runtime_for_stream_race(web_game, monkeypatch)
    monkeypatch.setattr(runtime.db, "kv_get", lambda _key: (_ for _ in ()).throw(RuntimeError("identity read failed")))

    events = list(runtime.chat_stream("殿上", "请奏"))

    assert len(events) == 1 and events[0]["type"] == "error"
    assert events[0]["message"] == "identity read failed"
    row = runtime.db.conn.execute("SELECT * FROM chat_turns ORDER BY id DESC LIMIT 1").fetchone()
    assert events[0]["chat_turn_id"] == row["id"]
    assert row["status"] == "interrupted"
    assert row["error_pack_path"]
    assert [r["content"] for r in runtime.db.conn.execute("SELECT content FROM chat_messages WHERE role='user'")] == ["请奏"]
    # 新开夜可并发唤起留中案预推；等这些既有写票落定，再核查无泄漏。
    assert runtime._runtime_write_queue().wait_idle()
    assert runtime._runtime_write_queue().inflight_count() == 0


def test_chat_stream_sse_waits_for_sync_generator_in_executor(web_game, monkeypatch):
    events: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    stub_scene_agent(monkeypatch, _FakeAgent(started=entered, allow=release, answer="臣已知悉。"))

    async def drive_first_event():
        response = await web_app.api_audience_chat_stream(web_app.ChatRequest(message="请奏"))
        iterator = response.body_iterator
        async def consume():
            return [chunk async for chunk in iterator]

        stream_task = asyncio.create_task(consume())

        async def tick():
            # entered 或 stream 终态；请求先失败须传播，禁无限等 thread Event（无 deadline）。
            await _await_condition_or_task(entered.is_set, stream_task)
            events.append("tick")
            release.set()

        watcher = asyncio.create_task(tick())
        try:
            chunks = await stream_task
            events.append("stream")
        finally:
            release.set()
            entered.set()
            await watcher
        return "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    first = asyncio.run(drive_first_event())

    assert events == ["tick", "stream"]
    from tests.test_chat_stream_failpaths_393 import _parse_sse
    parsed = _parse_sse(str(first))
    assert next(payload for kind, payload in parsed if kind == "done")["answer"] == "臣已知悉。"


def test_nonstream_api_chat_keeps_game_state_responsive_while_chat_blocks(web_game, monkeypatch):
    """#1291+#1322: 非流式 chat 同步慢 LLM 在飞时，并发 GET /api/game/state 须在阈内响应。

    根因：async api_audience_chat 在事件循环上直调全同步 get_game().chat()（→ subprocess.run），
    整站 loop 卡死。对照流式端点 run_in_executor / directives to_thread——本测咬死卸载后
    的可观测序：state 探针先于阻塞 chat 完成。
    """
    events: list[str] = []
    chat_entered = threading.Event()
    allow_finish = threading.Event()

    stub_scene_agent(monkeypatch, _FakeAgent(started=chat_entered, allow=allow_finish, answer="臣已知悉。"))
    turn = int(web_game.state.turn)

    async def drive_concurrent_state_probe():
        chat_task = asyncio.create_task(
            web_app.api_audience_chat(web_app.ChatRequest(message="边饷如何？")),
        )
        async def state_probe():
            try:
                await _await_condition_or_task(chat_entered.is_set, chat_task)
                payload = await web_app.api_state()
                # 先落成功标记再放行：set() 先执行则 chat 线程可先记 "chat"，
                # 与外部断言的严格顺序无 happens-before（#1722 判牒）。
                events.append("state_done")
            finally:
                # api_state 抛错也须放行 chat worker，否则 threadpool 永久阻塞。
                allow_finish.set()
            return payload

        chat_result, state_payload = await asyncio.gather(
            chat_task,
            state_probe(),
        )
        return chat_result, state_payload

    chat_result, state_payload = asyncio.run(drive_concurrent_state_probe())

    assert events == ["state_done"], (
        f"event loop 被非流式 chat 冻结（events={events}）；"
        "期望 state 探针在 chat 完成前响应"
    )
    assert state_payload["turn"]["turn"] == turn
    assert chat_result["answer"] == "臣已知悉。"


def test_nonstream_chat_rejects_when_session_draining(web_game):
    """drain 已开始时 chat 不得再登记 pending。"""
    runtime = web_game
    runtime._write_queue.seal()

    events = list(runtime.chat_stream("殿上", "边饷如何？"))
    assert events and events[0].get("type") == "error"
    # 新开夜可并发唤起留中案预推；等这些既有写票落定，再核查无泄漏。
    assert runtime._runtime_write_queue().wait_idle()
    assert runtime._runtime_write_queue().inflight_count() == 0
