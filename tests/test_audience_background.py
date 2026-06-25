from __future__ import annotations

import threading
import time

from ming_sim.skills import bind_content as bind_skills_content
from web_app import WebGame


class RunContent:
    event = "RunContent"

    def __init__(self, content: str) -> None:
        self.content = content


class RunOutput:
    def __init__(self, tools=None) -> None:
        self.tools = tools or []
        self.content = None


class ToolExec:
    def __init__(self, tool_name: str, result: str) -> None:
        self.tool_name = tool_name
        self.result = result


class _FakeAgent:
    def __init__(self, tools=None) -> None:
        self.completed = threading.Event()
        self.tools = tools or []

    def run(self, *_args, **_kwargs):
        yield RunContent("臣")
        yield RunContent("遵旨。")
        self.completed.set()
        yield RunOutput(self.tools)


class _EmptyAgent(_FakeAgent):
    def run(self, *_args, **_kwargs):
        self.completed.set()
        yield RunOutput()


class _FakeRegistry:
    def __init__(self, agent: _FakeAgent) -> None:
        self.agent = agent
        self.session_ids = {}

    def get(self, _character):
        return self.agent


class _FakeSession:
    def __init__(self, db, state, content, agent: _FakeAgent) -> None:
        self.db = db
        self.state = state
        self.content = content
        self.registry = _FakeRegistry(agent)
        self.temporary_characters = set()

    def _character(self, minister_name: str):
        return self.content.characters[minister_name]

    def _start_cli_action_intent(self, _character, _message):
        return None

    def _finish_cli_action_intent(self, _future):
        return None

    def apply_cli_conversation_actions(self, *_args, **_kwargs):
        return {"directive": None, "secret_order_id": None, "pending_action_id": 0}

    def pending_count(self) -> int:
        return 0


def _web_game(db, state, content, agent: _FakeAgent) -> WebGame:
    bind_skills_content(content)
    game = WebGame.__new__(WebGame)
    game.session = _FakeSession(db, state, content, agent)
    game.chat_history = {name: [] for name in content.characters}
    game.suggestions_for = lambda _character: []
    return game


def _wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_chat_stream_observer_departure_after_acceptance_still_completes_turn(game):
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "户部钱粮如何？")
    assert next(stream) == {"type": "delta", "content": "臣"}

    stream.close()

    assert agent.completed.wait(1.0), "后台召对应在观察者离开后继续跑完 LLM 流"
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert web_game.chat_history[minister_name] == [
        {"role": "user", "content": "户部钱粮如何？"},
        {"role": "minister", "content": "臣遵旨。"},
    ]
    assert db.can_undo_last_chat_turn(minister_name, state.turn)


def test_background_audience_reply_keeps_drafted_edict_after_observer_departure(game):
    db, state, content = game
    minister_name = "毕自严"
    draft_text = "着户部清核辽饷。"
    agent = _FakeAgent([ToolExec("propose_directive", f"__pending_directive__{draft_text}")])
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "拟一道清核辽饷的旨。")
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    assert _wait_for(lambda: any(
        row["text"] == draft_text
        for row in db.list_directives(state, statuses=("pending", "draft"))
    ))
    assert _wait_for(lambda: db.can_undo_last_chat_turn(minister_name, state.turn))


def test_llm_failure_does_not_leave_half_chat_in_history(game):
    db, state, content = game
    minister_name = "毕自严"
    agent = _EmptyAgent()
    web_game = _web_game(db, state, content, agent)

    events = list(web_game.chat_stream(minister_name, "户部钱粮如何？"))

    assert events[-1]["type"] == "error"
    assert web_game.chat_history[minister_name] == []
    assert db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    row = db.conn.execute("SELECT status FROM chat_turns").fetchone()
    assert row["status"] == "failed"
