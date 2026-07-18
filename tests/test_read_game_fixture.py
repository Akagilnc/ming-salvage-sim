"""轻量只读盘面 fixture 的边界契约。"""

from __future__ import annotations

import sqlite3

import pytest


def test_read_game_exposes_real_opening_board(read_game):
    db, state, content = read_game

    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] > 0
    assert db.conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0] > 0
    assert state is not None
    assert content.characters


def test_read_game_rejects_writes(read_game):
    db, _state, _content = read_game

    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.conn.execute("UPDATE armies SET manpower=0")
    finally:
        db.conn.rollback()

    assert not db.conn.in_transaction
