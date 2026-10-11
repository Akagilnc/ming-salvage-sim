"""Stored JSON decode failures leave the real DB read entry instead of becoming empty decisions."""

import json

import pytest


def test_pending_decisions_corrupt_options_json_fails_loud(game):
    db, _state, _content = game
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, '', 'pending')",
        (999, 0, "测试抉择", "", "{不是合法JSON"),
    )
    db.conn.commit()

    with pytest.raises(json.JSONDecodeError) as failure:
        db.list_pending_decisions(999)
    assert failure.value.doc == "{不是合法JSON"
    assert failure.value.pos == 1
