"""Shared setup seam for rejection-section integration tests."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from tests.conftest import game as _fresh_game_fixture


_MODULE_GAMES = {}


@pytest.fixture(name="game")
def section_game(request, content):
    """Reuse one real seeded game per rejection module, restoring it per case.

    The expensive creation path is exactly the production-faithful ``game``
    fixture from conftest.  SQLite backup and a state deepcopy only
    restore that known-good rendered baseline; every test still dispatches its
    delta through the real ``run_settle``/DB path.
    """
    module = request.module
    cached = _MODULE_GAMES.get(module)
    if cached is None:
        generator = _fresh_game_fixture.__wrapped__(content)
        db, state, game_content = next(generator)
        baseline_db = sqlite3.connect(":memory:")
        db.conn.backup(baseline_db)
        cached = (
            generator,
            db,
            state,
            game_content,
            baseline_db,
            copy.deepcopy(state),
        )
        _MODULE_GAMES[module] = cached

        def close_module_game():
            _MODULE_GAMES.pop(module, None)
            baseline_db.close()
            try:
                next(generator)
            except StopIteration:
                pass

        request.node.parent.addfinalizer(close_module_game)

    _, db, state, game_content, baseline_db, baseline_state = cached
    if db.conn.in_transaction:
        db.conn.rollback()
    baseline_db.backup(db.conn)
    state.__dict__.clear()
    state.__dict__.update(copy.deepcopy(baseline_state.__dict__))
    return db, state, game_content


# Consumer modules import the fixture under the name their existing tests request.
game = section_game


def rejection_rows(db, turn, section=None, *, columns="section, reason, category, source"):
    query = (
        f"SELECT {columns} FROM rejection_reports"
        " WHERE turn=?"
    )
    params = [turn]
    if section is not None:
        query += " AND section=?"
        params.append(section)
    return db.conn.execute(query + " ORDER BY id", params).fetchall()
