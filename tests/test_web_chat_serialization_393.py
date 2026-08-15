from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import web_app


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
        assert self.allow_finish.wait(1.0), "test timed out waiting to finish fake stream"
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


class _FakeRegistry:
    session_ids = {}

    def __init__(self, agent: _FakeAgent):
        self.agent = agent

    def get(self, character):
        return self.agent


class _FakeSession:
    temporary_characters = set()

    def __init__(self, character, agent: _FakeAgent, state, db):
        self.state = state
        self.db = db
        self.content = SimpleNamespace(characters={character.name: character})
        self.registry = _FakeRegistry(agent)

    def _character(self, minister_name: str):
        return self.content.characters[minister_name]

    def _start_cli_action_intent(self, character, text):
        return None

    def _finish_cli_action_intent(self, future):
        return None

    def apply_cli_conversation_actions(self, *args, **kwargs):
        return {
            "directive": None,
            "secret_order_id": 0,
            "pending_action_id": 0,
            "pending_action_failures": [],
        }

    def _merge_staged_new_secret_order_content(self, *args, **kwargs):
        return None

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

    def persist_minister_reply(self, minister_name: str, turn: int, content: str, chat_turn_id: int):
        # #499 单一事务插入回话+链接+接受（本 stub 复用 append_chat_message 记账，返回其 id）
        return self.append_chat_message(minister_name, turn, "minister", content)

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


def _runtime_for_stream_race():
    allow_finish = threading.Event()
    settlement_attempting = threading.Event()
    settlement_holding = threading.Event()
    character = SimpleNamespace(name="测试大臣")
    agent = _FakeAgent(allow_finish)
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _RecordingDB(settlement_holding)

    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(character, agent, state, db)
    runtime.chat_history = {character.name: []}
    runtime._write_gate = threading.Lock()
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda character: []
    runtime.can_undo_last_chat = lambda minister_name: False

    def settlement():
        settlement_attempting.set()
        with runtime._write_gate:
            settlement_holding.set()
            runtime.state.turn = 2
            time.sleep(0.1)
            settlement_holding.clear()

    return runtime, character.name, allow_finish, settlement_attempting, settlement


def test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn():
    runtime, minister_name, allow_finish, settlement_attempting, settlement = _runtime_for_stream_race()

    stream = runtime.chat_stream(minister_name, "请奏")
    first = next(stream)
    assert first == {"type": "delta", "content": "臣已知悉。"}

    settlement_thread = threading.Thread(target=settlement)
    settlement_thread.start()
    assert settlement_attempting.wait(1.0), "settlement did not attempt to enter the write gate"
    time.sleep(0.02)
    allow_finish.set()

    done = next(stream)
    settlement_thread.join(1.0)

    assert done["type"] == "done"
    assert runtime.db.overlapped_minister_commit is False
    minister_messages = [msg for msg in runtime.db.messages if msg["role"] == "minister"]
    assert minister_messages and minister_messages[-1]["turn"] == 1
    assert runtime.state.turn == 2


def test_identity_setup_failure_closes_durable_turn_and_pending_owner_as_terminal_error():
    runtime, minister_name, _allow_finish, _settlement_attempting, _settlement = _runtime_for_stream_race()
    failed = []
    completed = []
    runtime.db.kv_get = lambda _key: (_ for _ in ()).throw(RuntimeError("identity read failed"))
    runtime._fail_chat_turn_and_reload = lambda turn_id, snapshot: failed.append((turn_id, snapshot))
    runtime._complete_pending_write = lambda: completed.append(True)

    events = list(runtime.chat_stream(minister_name, "请奏"))

    assert events == [{
        "type": "error", "message": "identity read failed",
        "campaign_id": "", "night_id": 0, "chat_turn_id": 7,
    }]
    assert failed == [(7, {})]
    assert completed == [True]


def test_lightweight_stream_seam_reaches_done_without_durable_identity_or_night_signature():
    runtime, minister_name, allow_finish, _settlement_attempting, _settlement = _runtime_for_stream_race()
    stream = runtime.chat_stream(minister_name, "请奏")
    assert next(stream)["type"] == "delta"
    allow_finish.set()
    assert next(stream)["type"] == "done"


def test_chat_stream_sse_waits_for_sync_generator_in_executor(monkeypatch):
    events: list[str] = []

    class _BlockingGame:
        def chat_stream(self, minister_name: str, message: str):
            time.sleep(0.05)
            events.append("stream")
            yield {"type": "done", "payload": {"ok": True}}

    monkeypatch.setattr(web_app, "_require_active_minister", lambda minister_name: None)
    monkeypatch.setattr(web_app, "get_game", lambda: _BlockingGame())

    async def drive_first_event():
        response = await web_app.api_chat_stream("测试大臣", web_app.ChatRequest(message="请奏"))
        iterator = response.body_iterator

        async def tick():
            await asyncio.sleep(0.01)
            events.append("tick")

        first_event, _ = await asyncio.gather(iterator.__anext__(), tick())
        return first_event

    first = asyncio.run(drive_first_event())

    assert events == ["tick", "stream"]
    assert "event: done" in first


def test_stream_prompt_builder_internal_typeerror_is_not_retried_as_legacy_signature():
    """签名兼容须在调用前判定，不能吞掉 production builder 内部 TypeError。"""
    runtime, minister_name, _allow_finish, _settlement_attempting, _settlement = _runtime_for_stream_race()
    calls = []

    def prompt_builder(text, character, *, chat_turn_id=0):
        calls.append((text, character, chat_turn_id))
        raise TypeError("production prompt failure")

    runtime.session._audience_prompt_for_message = prompt_builder

    try:
        runtime._chat_stream_payload(minister_name, "请奏", 7, {}, 1, lambda _delta: None)
    except TypeError as exc:
        assert str(exc) == "production prompt failure"
    else:
        raise AssertionError("prompt builder TypeError should propagate")
    assert len(calls) == 1


def test_streamed_secret_order_preserves_blacklist_through_commit_restore_transfer_and_disclosure(game):
    """Web tool capture must keep explicit secrecy exclusions through the full durable path."""
    db, state, content = game
    assignee = next(c for c in content.characters.values() if c.office_type == "兵部")
    excluded = next(c for c in content.characters.values() if c.office_type == "户部")
    agent = _SecretOrderAgent(
        '__secret_order__{"title":"密查亏空","content":"查户部旧账","assignee":"%s",'
        '"excluded_names":["%s"],"excluded_offices":["户部"]}'
        % (assignee.name, excluded.name)
    )
    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(assignee, agent, state, db)
    runtime.chat_history = {assignee.name: []}
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda character: []
    runtime.can_undo_last_chat = lambda minister_name: False

    payload = runtime._chat_stream_payload(
        assignee.name, "密令如下：查户部旧账", 0, {}, state.turn, lambda _delta: None,
    )

    assert payload["pending_action_id"] > 0
    pending = db.list_pending_actions(state.turn, minister_name=assignee.name)
    assert len(pending) == 1
    assert db.commit_pending_actions(state, minister_name=assignee.name)

    order = db.list_secret_orders()[0]
    assert order["excluded_targets"] == {
        "people": [excluded.name], "offices": ["户部"],
    }
    path = db.path
    db.close()

    from ming_sim.db import GameDB

    fresh_db = GameDB(path, content)
    try:
        restored = fresh_db.load_state()
        fresh_db.set_character_office(excluded.name, "礼部尚书", office_type="礼部")
        fresh_db.record_public_knowledge_event(
            restored, "密查公开", "密查户部旧账已奉明发",
            source_id=f"secret_order:{order['id']}",
        )
        knowledge = fresh_db.get_character_knowledge(restored, excluded.name)
        assert not any(
            item["source_id"] == f"secret_order:{order['id']}"
            for item in knowledge["events"]
        )
        assert not any(
            item["source_id"] == f"secret_order:{order['id']}"
            for item in knowledge["public_events"]
        )
    finally:
        fresh_db.close()


def test_streamed_secret_order_update_pins_held_oral_and_keeps_it_private(game):
    """Web streamed 更新 must preserve message-level secret provenance end to end."""
    db, state, content = game
    active = [c for c in content.characters.values() if c.status == "active"]
    assignee, other = active[:2]
    order_id = db.create_secret_order(
        state, assignee.name, "密查国丈", "初旨：暗访田宅。", [],
    )
    oral = "续密：扩查国丈典当与内库往来，不得走漏。"
    message_id = db.append_chat_message(assignee.name, state.turn, "user", oral)
    agent = _SecretOrderAgent(
        '__secret_action__{"action":"更新","order_id":%d,'
        '"payload":{"title":"密查国丈（扩）","content":"扩查典当与内库往来。"}}'
        % order_id
    )
    runtime = object.__new__(web_app.WebGame)
    runtime.session = _FakeSession(assignee, agent, state, db)
    runtime.chat_history = {assignee.name: []}
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda character: []
    runtime.can_undo_last_chat = lambda minister_name: False

    result = runtime._chat_stream_payload(
        assignee.name, oral, 0, {}, state.turn, lambda _delta: None,
    )

    pending = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result["pending_action_id"],),
    ).fetchone()
    assert json.loads(pending["payload_json"])["origin_chat_message_id"] == message_id
    assert db.commit_pending_actions(
        state, minister_name=assignee.name,
        action_ids={result["pending_action_id"]}, content=content,
    )
    db.release_held_audience_knowledge()
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (message_id,),
    ).fetchone()["knowledge_status"] == "withheld"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{message_id}",),
    ).fetchone()[0] == 0
    other_view = db.get_character_knowledge(state, other.name)
    assert oral not in " ".join(
        item.get("body", "")
        for item in other_view["events"] + other_view.get("public_events", [])
    )


def test_streamed_secret_order_progress_does_not_pin_public_held_message(game):
    """Web streamed 催办/记进展 must not invent secret bloodline."""
    db, state, content = game
    assignee = next(c for c in content.characters.values() if c.status == "active")
    order_id = db.create_secret_order(
        state, assignee.name, "密查国丈", "初旨：暗访田宅。", [],
    )

    for action in ("催办", "记进展"):
        public_text = f"京营操练如何？顺便{action}前令。"
        db.append_chat_message(assignee.name, state.turn, "user", public_text)
        agent = _SecretOrderAgent(
            '__secret_action__{"action":"%s","order_id":%d,"payload":{"note":"照办"}}'
            % (action, order_id)
        )
        runtime = object.__new__(web_app.WebGame)
        runtime.session = _FakeSession(assignee, agent, state, db)
        runtime.chat_history = {assignee.name: []}
        runtime.directive_rows = lambda: []
        runtime.directive_payload = lambda row: row
        runtime.suggestions_for = lambda character: []
        runtime.can_undo_last_chat = lambda minister_name: False

        result = runtime._chat_stream_payload(
            assignee.name, public_text, 0, {}, state.turn, lambda _delta: None,
        )
        pending = db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?",
            (result["pending_action_id"],),
        ).fetchone()
        assert "origin_chat_message_id" not in json.loads(pending["payload_json"])
