from __future__ import annotations


import pytest
from tests.wait_utils import wait_until
from tests.conftest import wait_for_background_jobs

import asyncio
import threading

import web_app
from tests.wait_utils import _await_condition_or_task
from tests.test_web_audience_night_498 import _FakeAgent
from tests.conftest import stub_scene_agent


pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")


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





def test_nonstream_chat_rejects_when_session_draining(web_game):
    """drain 已开始时 chat 不得再登记 pending。"""
    runtime = web_game
    runtime._write_queue.seal()

    events = list(runtime.chat_stream("殿上", "边饷如何？"))
    assert events and events[0].get("type") == "error"
    # 新开夜可并发唤起留中案预推；等这些既有写票落定，再核查无泄漏。
    assert runtime._runtime_write_queue().wait_idle()
    assert runtime._runtime_write_queue().inflight_count() == 0
