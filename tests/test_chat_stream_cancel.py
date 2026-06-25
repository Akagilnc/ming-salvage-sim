from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import web_app
from web_app import ChatRequest, WebGame


class _Event:
    event = "RunContent"
    content = "臣在。"


class _Agent:
    def run(self, *_args, **_kwargs):
        yield _Event()
        raise AssertionError("stream should have been closed after first token")


class _Registry:
    session_ids = {"测试大臣": "minister-test"}

    def get(self, _character):
        return _Agent()


class _Session:
    temporary_characters = {}
    registry = _Registry()

    def __init__(self, db, state, content, character):
        self.db = db
        self.state = state
        self.content = content
        self._character_obj = character

    def _character(self, _minister_name):
        return self._character_obj


def _chat_rows(db):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT minister_name, role, content FROM chat_messages ORDER BY id"
        ).fetchall()
    ]


def _turn_rows(db):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT id, status, user_message_id, minister_message_id FROM chat_turns ORDER BY id"
        ).fetchall()
    ]


def test_closing_chat_stream_marks_turn_failed_and_removes_user_message(game):
    db, state, content = game
    minister_name = "测试大臣"
    character = SimpleNamespace(name=minister_name, office_type="cabinet")
    content.characters[minister_name] = character

    web_game = WebGame.__new__(WebGame)
    web_game.session = _Session(db, state, content, character)
    web_game.chat_history = {minister_name: []}

    stream = web_game.chat_stream(minister_name, "请说要事")
    assert next(stream) == {"type": "delta", "content": "臣在。"}

    stream.close()

    assert _turn_rows(db) == [
        {
            "id": 1,
            "status": "failed",
            "user_message_id": 1,
            "minister_message_id": None,
        }
    ]
    assert _chat_rows(db) == []
    assert web_game.chat_history[minister_name] == []


def test_cancel_at_done_of_completed_turn_keeps_history_and_messages(game):
    """A cancel that lands AFTER the reply completed (e.g. client disconnects at the
    `done` yield) must NOT nuke the in-memory history of the now-completed turn — the
    db guard already refuses to fail it, and the web layer must mirror that guard."""
    db, state, content = game
    minister_name = "测试大臣"

    web_game = WebGame.__new__(WebGame)
    web_game.session = _Session(db, state, content, SimpleNamespace(name=minister_name))
    web_game.chat_history = {minister_name: []}

    user_id = db.append_chat_message(minister_name, state.turn, "user", "请说要事")
    turn_id = db.create_chat_turn(state, minister_name, "minister-test", 0)
    db.update_chat_turn_messages(turn_id, user_message_id=user_id)
    minister_id = db.append_chat_message(minister_name, state.turn, "minister", "臣以为……")
    db.update_chat_turn_messages(turn_id, minister_message_id=minister_id)
    web_game.chat_history[minister_name] = [
        {"role": "user", "content": "请说要事"},
        {"role": "minister", "content": "臣以为……"},
    ]

    web_game._fail_incomplete_chat_turn(minister_name, turn_id, "请说要事")

    assert _turn_rows(db) == [
        {
            "id": turn_id,
            "status": "active",
            "user_message_id": user_id,
            "minister_message_id": minister_id,
        }
    ]
    assert _chat_rows(db) == [
        {"minister_name": minister_name, "role": "user", "content": "请说要事"},
        {"minister_name": minister_name, "role": "minister", "content": "臣以为……"},
    ]
    assert web_game.chat_history[minister_name] == [
        {"role": "user", "content": "请说要事"},
        {"role": "minister", "content": "臣以为……"},
    ]


class _MultiEvent:
    def __init__(self, content: str):
        self.event = "RunContent"
        self.content = content


class _MultiAgent:
    def run(self, *_args, **_kwargs):
        yield _MultiEvent("臣")
        yield _MultiEvent("在。")
        raise AssertionError("stream should have been closed after client disconnect")


class _MultiRegistry:
    session_ids = {"测试大臣": "minister-test"}

    def get(self, _character):
        return _MultiAgent()


class _MultiSession(_Session):
    registry = _MultiRegistry()


class _DisconnectingRequest:
    """Fake Starlette Request: is_disconnected() trips to True after `trip_after` calls."""

    def __init__(self, trip_after: int):
        self._calls = 0
        self._trip_after = trip_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._trip_after


def test_api_chat_stream_detects_client_disconnect_and_fails_turn(game, monkeypatch):
    """The SSE endpoint must poll is_disconnected(), turn a mid-stream disconnect into a
    cancellation that reaches chat_stream's cancel handler, and so fail the in-flight turn
    + drop its durable user prompt (C5 wired end-to-end, not just the generator layer)."""
    db, state, content = game
    minister_name = "测试大臣"
    character = SimpleNamespace(name=minister_name, office_type="cabinet")
    content.characters[minister_name] = character

    web_game = WebGame.__new__(WebGame)
    web_game.session = _MultiSession(db, state, content, character)
    web_game.chat_history = {minister_name: []}

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda *_a, **_k: None)

    # is_disconnected() cadence: call#1 = pre-loop check, call#2 = after first delta,
    # call#3 = after second delta. trip_after=2 keeps the original intent (first delta
    # delivered, THEN a mid-stream disconnect) under the added pre-loop probe.
    fake_request = _DisconnectingRequest(trip_after=2)

    async def drive():
        resp = await web_app.api_chat_stream(
            minister_name, ChatRequest(message="请说要事"), fake_request
        )
        chunks = []
        with pytest.raises(asyncio.CancelledError):
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(drive())

    assert any("臣" in chunk for chunk in chunks)  # first delta was delivered pre-disconnect
    assert _turn_rows(db) == [
        {"id": 1, "status": "failed", "user_message_id": 1, "minister_message_id": None}
    ]
    assert _chat_rows(db) == []
    assert web_game.chat_history[minister_name] == []


class _PreLoopAgent:
    """Agent whose run() must NOT be consumed when the client is already gone."""

    consumed = False

    def run(self, *_args, **_kwargs):
        type(self).consumed = True
        yield _Event()


class _PreLoopRegistry:
    session_ids = {"测试大臣": "minister-test"}

    def get(self, _character):
        return _PreLoopAgent()


class _PreLoopSession(_Session):
    registry = _PreLoopRegistry()


def test_api_chat_stream_preloop_disconnect_cancels_before_first_read(game, monkeypatch):
    """#380 cmr: a client already gone before the first blocking read is cancelled at the
    pre-loop probe — no delta is yielded and the synchronous LLM stream is never consumed
    (so no model call is entered for a gone client). Because the chat_stream generator body
    hasn't started, no chat_turn exists to fail. (Partial mitigation of codex P2; the
    mid-first-token disconnect is the deferred blocking-read case.)"""
    db, state, content = game
    minister_name = "测试大臣"
    character = SimpleNamespace(name=minister_name, office_type="cabinet")
    content.characters[minister_name] = character
    _PreLoopAgent.consumed = False

    web_game = WebGame.__new__(WebGame)
    web_game.session = _PreLoopSession(db, state, content, character)
    web_game.chat_history = {minister_name: []}

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda *_a, **_k: None)

    # trip_after=0: the very first is_disconnected() (the pre-loop check) returns True.
    fake_request = _DisconnectingRequest(trip_after=0)

    async def drive():
        resp = await web_app.api_chat_stream(
            minister_name, ChatRequest(message="请说要事"), fake_request
        )
        chunks = []
        with pytest.raises(asyncio.CancelledError):
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(drive())

    assert chunks == [], "no delta should be yielded for an already-disconnected client"
    assert _PreLoopAgent.consumed is False, "LLM stream must not be entered for a gone client"
    # generator never started → no durable turn/message rows created
    assert _turn_rows(db) == []
    assert _chat_rows(db) == []
    assert web_game.chat_history[minister_name] == []


def test_api_chat_stream_close_guard_tolerates_non_closeable_stream(game, monkeypatch):
    """#380 gemini: the finally-block close must not raise if chat_stream is swapped for
    an iterator/list lacking .close() — the AttributeError would mask the real outcome."""
    db, state, content = game
    minister_name = "测试大臣"
    character = SimpleNamespace(name=minister_name, office_type="cabinet")
    content.characters[minister_name] = character

    web_game = WebGame.__new__(WebGame)
    web_game.session = _Session(db, state, content, character)
    web_game.chat_history = {minister_name: []}

    # Plain list iterator: no .close() attribute at all.
    def fake_chat_stream(_name, _msg):
        return iter([{"type": "done", "payload": {"answer": "臣在。"}}])

    web_game.chat_stream = fake_chat_stream  # type: ignore[assignment]

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda *_a, **_k: None)

    fake_request = _DisconnectingRequest(trip_after=99)  # never disconnects

    async def drive():
        resp = await web_app.api_chat_stream(
            minister_name, ChatRequest(message="请说要事"), fake_request
        )
        chunks = []
        async for chunk in resp.body_iterator:  # must NOT raise AttributeError in finally
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(drive())
    assert any("done" in chunk for chunk in chunks)


# ---------------------------------------------------------------------------
# #380 cmr r2 (codex P2): a cancel at the done boundary must NOT orphan a tool
# side-effect (DB write) — the rollback diffs are recorded BEFORE the done yield,
# minister_message_id is set BEFORE the done yield, so fail_incomplete no-ops and
# the completed turn stays fully recoverable. A cancel mid-stream (before the tool
# block runs) writes nothing at all. Either way: never a committed-but-unrecoverable row.
# ---------------------------------------------------------------------------


class _DirectiveDelta:
    event = "RunContent"
    content = "臣拟一道旨。"


class _DirectiveTool:
    tool_name = "propose_directive"
    result = "__pending_directive__赈济陕西灾民"
    arguments: dict = {}


class _DirectiveRunOutput:
    """RunOutput-typed event carrying a propose_directive tool result."""

    event = "RunCompleted"
    content = None
    tools = [_DirectiveTool()]


# rename the class so type(event).__name__ matches the web_app check ("RunOutput"/"RunCompletedEvent")
_DirectiveRunOutput.__name__ = "RunOutput"
_DirectiveRunOutput.__qualname__ = "RunOutput"


class _DirectiveAgent:
    def run(self, *_args, **_kwargs):
        yield _DirectiveDelta()
        yield _DirectiveRunOutput()


class _DirectiveRegistry:
    session_ids = {"测试大臣": "minister-test"}

    def get(self, _character):
        return _DirectiveAgent()


def _make_directive_session(db, state, content, character):
    """A _Session whose registry returns the directive-writing agent, plus the
    real apply_cli_conversation_actions / _proposal_blocked surface chat_stream needs."""
    sess = _Session(db, state, content, character)
    sess.registry = _DirectiveRegistry()
    sess.apply_cli_conversation_actions = lambda *a, **k: {
        "directive": None, "secret_order_id": 0, "pending_action_id": 0,
    }
    sess.pending_count = lambda: 0
    return sess


def _directive_rows(db):
    return [dict(r) for r in db.conn.execute(
        "SELECT id, text, status FROM turn_directives ORDER BY id"
    ).fetchall()]


def test_cancel_at_done_keeps_tool_side_effect_recoverable(game, monkeypatch):
    """Cancel fires at the done boundary (after the post-stream tool block + rollback-record
    + _chat_payload all ran). minister_message_id is set → fail_incomplete no-ops → the turn
    stays completed and the directive write is intact and rollback-recorded (recoverable)."""
    db, state, content = game
    minister_name = "测试大臣"
    character = SimpleNamespace(name=minister_name, office_type="cabinet")
    content.characters[minister_name] = character

    web_game = WebGame.__new__(WebGame)
    web_game.session = _make_directive_session(db, state, content, character)
    web_game.session._proposal_blocked = staticmethod(lambda _s: False)
    web_game.chat_history = {minister_name: []}
    # WebGame helpers _chat_payload uses:
    web_game.directive_rows = lambda: _directive_rows(db)
    web_game.directive_payload = lambda row: row
    web_game.can_undo_last_chat = lambda _n: False
    web_game.suggestions_for = lambda _c: []

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app.GameSession, "_proposal_blocked", staticmethod(lambda _s: False), raising=False)

    # cadence: #1 pre-loop(F), #2 before delta(F)→deliver, #3 before done(T)→cancel at done boundary
    fake_request = _DisconnectingRequest(trip_after=2)

    async def drive():
        resp = await web_app.api_chat_stream(
            minister_name, ChatRequest(message="请说要事"), fake_request
        )
        chunks = []
        with pytest.raises(asyncio.CancelledError):
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
        return chunks

    asyncio.run(drive())

    # The directive the tool wrote during the stream must NOT be orphaned: it is present
    # AND the turn it belongs to is completed (minister_message_id set), so undo can revert it.
    dirs = _directive_rows(db)
    assert len(dirs) == 1, f"directive write should survive as a recoverable row, got {dirs}"
    turns = _turn_rows(db)
    assert len(turns) == 1
    assert turns[0]["minister_message_id"] is not None, "turn completed → not failed → side effect recoverable"
    assert turns[0]["status"] == "active", "completed turn must not be marked failed by the cancel"
    # rollback diffs were recorded for the turn (so undo_last_chat can revert the directive)
    items = db.conn.execute(
        "SELECT COUNT(*) AS n FROM chat_turn_rollback_items WHERE chat_turn_id=?",
        (turns[0]["id"],),
    ).fetchone()
    assert items["n"] >= 1, "rollback diffs must be recorded before the done yield"


def test_cancel_mid_stream_writes_no_tool_side_effect(game, monkeypatch):
    """Mirror of the recoverability test from the other side: a cancel that lands DURING
    streaming (before the post-stream tool block runs) writes no directive at all — the
    turn is failed and its user prompt dropped, with zero orphaned side-effect rows.
    Together these two tests close codex r2: there is no suspension point between a tool
    DB write and _record_chat_rollback_items, so a side effect is never committed-but-lost."""
    db, state, content = game
    minister_name = "测试大臣"
    character = SimpleNamespace(name=minister_name, office_type="cabinet")
    content.characters[minister_name] = character

    web_game = WebGame.__new__(WebGame)
    web_game.session = _make_directive_session(db, state, content, character)
    web_game.chat_history = {minister_name: []}
    web_game.directive_rows = lambda: _directive_rows(db)
    web_game.directive_payload = lambda row: row
    web_game.can_undo_last_chat = lambda _n: False
    web_game.suggestions_for = lambda _c: []

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda *_a, **_k: None)

    # cadence: #1 pre-loop(F), #2 before the first delta(T) → cancel mid-stream, before the
    # RunOutput is even consumed, so the propose_directive tool block never runs.
    fake_request = _DisconnectingRequest(trip_after=1)

    async def drive():
        resp = await web_app.api_chat_stream(
            minister_name, ChatRequest(message="请说要事"), fake_request
        )
        with pytest.raises(asyncio.CancelledError):
            async for _chunk in resp.body_iterator:
                pass

    asyncio.run(drive())

    assert _directive_rows(db) == [], "no tool side effect should be written on a mid-stream cancel"
    assert _turn_rows(db) == [
        {"id": 1, "status": "failed", "user_message_id": 1, "minister_message_id": None}
    ]
    assert _chat_rows(db) == []
