from __future__ import annotations

import asyncio
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
        return {"directive": None, "secret_order_id": 0, "pending_action_id": 0}

    def pending_count(self):
        return 0


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

    def record_chat_turn_rollback_diffs(self, *args, **kwargs):
        return None

    def get_last_active_chat_turn(self, minister_name: str, turn: int):
        return None


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
