from __future__ import annotations

from types import SimpleNamespace

from web_app import WebGame


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
