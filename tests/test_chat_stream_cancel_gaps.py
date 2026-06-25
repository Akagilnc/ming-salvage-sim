"""Gap coverage for fail_incomplete_chat_turn and api_chat_stream normal path.

Covers branches left uncovered by test_chat_stream_cancel.py:
  B-db1  nonexistent turn → {}
  B-db2  already-completed turn (minister_message_id set) → no-op, no failed_now
  B-db5  active turn with no user_message_id → marks failed, no DELETE needed
  B-db6  race: turn already failed by the time of the UPDATE → rowcount=0, no failed_now
  B-wa6  api_chat_stream normal completion (no disconnect) → yields all events, closes stream
"""
from __future__ import annotations

import asyncio
import types
from types import SimpleNamespace

import pytest

import web_app
from web_app import ChatRequest, WebGame


# ---------------------------------------------------------------------------
# DB-layer gaps (GameDB.fail_incomplete_chat_turn)
# ---------------------------------------------------------------------------

def test_fail_nonexistent_turn_returns_empty(game):
    """B-db1: nonexistent chat_turn_id → {} (contract: no error, caller sees no-op)."""
    db, state, _ = game
    result = db.fail_incomplete_chat_turn(99999)
    assert result == {}


def test_fail_completed_turn_is_noop(game):
    """B-db2: turn already has minister_message_id (reply done) → returns turn_row, no failed_now."""
    db, state, _ = game
    minister_name = "测试大臣"
    user_id = db.append_chat_message(minister_name, state.turn, "user", "奏")
    turn_id = db.create_chat_turn(state, minister_name, "test-session", 0)
    db.update_chat_turn_messages(turn_id, user_message_id=user_id)
    minister_id = db.append_chat_message(minister_name, state.turn, "minister", "臣知")
    db.update_chat_turn_messages(turn_id, minister_message_id=minister_id)

    result = db.fail_incomplete_chat_turn(turn_id)

    assert result.get("status") == "active"
    assert "failed_now" not in result
    # DB and message rows must be untouched
    row = db.conn.execute("SELECT status FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    assert row["status"] == "active"
    msgs = db.conn.execute("SELECT id FROM chat_messages").fetchall()
    assert len(msgs) == 2


def test_fail_completed_turn_with_zero_minister_message_id_is_noop(game):
    """#380 cmr (gemini): the read-guard must use `is not None`, not truthiness — a
    completed turn whose minister_message_id is 0 must be treated as done (no failed_now,
    no transition), consistent with the user_message_id guard fix."""
    db, state, _ = game
    minister_name = "测试大臣"
    user_id = db.append_chat_message(minister_name, state.turn, "user", "奏")
    turn_id = db.create_chat_turn(state, minister_name, "test-session", 0)
    db.update_chat_turn_messages(turn_id, user_message_id=user_id)
    # Force minister_message_id = 0 (a valid "reply done" id under a 0-based scheme):
    # truthiness would mis-read this as "no reply yet" and try to fail the turn.
    db.conn.execute(
        "UPDATE chat_turns SET minister_message_id = 0 WHERE id = ?", (turn_id,)
    )
    db.conn.commit()

    result = db.fail_incomplete_chat_turn(turn_id)

    assert "failed_now" not in result, "completed turn (minister_message_id=0) must not be failed"
    row = db.conn.execute("SELECT status FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    assert row["status"] == "active", "completed turn must stay active, not be marked failed"
    # the user prompt message must NOT be deleted
    msgs = db.conn.execute("SELECT id FROM chat_messages").fetchall()
    assert len(msgs) == 1


def test_fail_turn_with_no_user_message_id_marks_failed(game):
    """B-db5: turn is active but user_message_id is NULL (created before message append)
    → still transitions to failed; no DELETE of chat_messages needed."""
    db, state, _ = game
    minister_name = "测试大臣"
    turn_id = db.create_chat_turn(state, minister_name, "test-session", 0)
    # no update_chat_turn_messages → user_message_id stays NULL

    result = db.fail_incomplete_chat_turn(turn_id)

    assert result.get("failed_now") is True
    assert result.get("status") == "failed"
    row = db.conn.execute("SELECT status FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    assert row["status"] == "failed"
    # No messages were inserted, none deleted
    msgs = db.conn.execute("SELECT id FROM chat_messages").fetchall()
    assert msgs == []


def test_fail_turn_race_condition_returns_no_failed_now(game):
    """B-db6: turn is active at SELECT time but is concurrently completed before the UPDATE.
    The WHERE guard (status='active' AND minister_message_id IS NULL) returns rowcount=0;
    the method must return the stale turn_row without failed_now, never deleting messages."""
    db, state, _ = game
    minister_name = "测试大臣"
    user_id = db.append_chat_message(minister_name, state.turn, "user", "奏")
    turn_id = db.create_chat_turn(state, minister_name, "test-session", 0)
    db.update_chat_turn_messages(turn_id, user_message_id=user_id)

    # Simulate the race: another path completes the turn (sets minister_message_id)
    # BEFORE fail_incomplete_chat_turn's UPDATE fires. We patch conn.execute to inject
    # this side effect right when the UPDATE is issued.
    original_execute = db.conn.execute
    _patched_once = [False]

    def _inject_race(sql, params=()):
        if not _patched_once[0] and sql.startswith("UPDATE chat_turns SET status = 'failed'"):
            _patched_once[0] = True
            # Complete the turn so the UPDATE's WHERE clause finds nothing
            minister_id = db.conn.execute(
                "INSERT INTO chat_messages (minister_name, turn, role, content) VALUES (?, ?, ?, ?)",
                (minister_name, state.turn, "minister", "臣已答"),
            ).lastrowid
            db.conn.execute(
                "UPDATE chat_turns SET minister_message_id = ? WHERE id = ?",
                (minister_id, turn_id),
            )
            db.conn.commit()
        return original_execute(sql, params)

    db.conn.execute = _inject_race
    try:
        result = db.fail_incomplete_chat_turn(turn_id)
    finally:
        db.conn.execute = original_execute

    assert "failed_now" not in result
    # The turn must still be active (race-completing turn kept it that way)
    row = db.conn.execute("SELECT status FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    assert row["status"] == "active"
    # The user message must NOT have been deleted (guard fired correctly)
    msgs = db.conn.execute("SELECT id FROM chat_messages WHERE role = 'user'").fetchall()
    assert len(msgs) == 1


# ---------------------------------------------------------------------------
# web_app.py — api_chat_stream normal completion (B-wa6)
# ---------------------------------------------------------------------------

class _NormalEvent:
    event = "RunContent"
    content = "臣以为可。"


class _DoneStream:
    """Yields one delta and then finishes normally (no disconnect, no error)."""

    def __init__(self):
        self._closed = False
        self._items = [
            {"type": "delta", "content": "臣以为可。"},
            {"type": "done", "payload": {"summary": "ok"}},
        ]
        self._gen = self._make_gen()

    def _make_gen(self):
        for item in self._items:
            yield item

    def __iter__(self):
        return self._gen

    def __next__(self):
        return next(self._gen)

    def close(self):
        self._closed = True
        self._gen.close()


class _NeverDisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_api_chat_stream_normal_completion_yields_all_events(game, monkeypatch):
    """B-wa6: client stays connected through the full response → all SSE events yielded,
    stream.close() called in finally even on normal exit."""
    db, state, content = game
    minister_name = "测试大臣"

    web_game = WebGame.__new__(WebGame)
    web_game.chat_history = {minister_name: []}

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda *_a, **_k: None)

    # Patch chat_stream at the WebGame method level so stream.close() is trackable
    tracked_stream = _DoneStream()

    monkeypatch.setattr(web_game, "chat_stream", lambda name, msg: tracked_stream)

    async def drive():
        resp = await web_app.api_chat_stream(
            minister_name, ChatRequest(message="请言"), _NeverDisconnectedRequest()
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(drive())

    # At least one delta and the done event must be present
    assert any("delta" in c for c in chunks), f"expected delta in {chunks}"
    assert any("done" in c for c in chunks), f"expected done in {chunks}"
    # stream.close() must have been called (finally block)
    assert tracked_stream._closed
