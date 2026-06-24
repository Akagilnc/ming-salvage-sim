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
