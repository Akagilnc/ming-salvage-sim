"""Shared setup seam for rejection-section integration tests."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from ming_sim.db import GameDB
from tests.conftest import game as _fresh_game_fixture


_MODULE_GAMES = {}


@pytest.fixture(name="game")
def section_game(request, content):
    """Reuse one real seeded game per rejection module, restoring it per case.

    The expensive creation path is exactly the production-faithful ``game``
    fixture from conftest.  Each case opens a fresh ``GameDB`` over a copy of
    that known-good SQLite baseline, so Python-side caches remain isolated and
    every test still dispatches through the real ``run_settle``/DB path.
    """
    module = request.module
    cached = _MODULE_GAMES.get(module)
    if cached is None:
        generator = _fresh_game_fixture.__wrapped__(content)
        db, state, game_content = next(generator)
        baseline_fd, baseline_path = tempfile.mkstemp(suffix=".db")
        os.close(baseline_fd)
        baseline_db = sqlite3.connect(baseline_path)
        try:
            db.conn.backup(baseline_db)
        finally:
            baseline_db.close()
        cached = (generator, game_content, baseline_path)
        _MODULE_GAMES[module] = cached

        def close_module_game():
            _MODULE_GAMES.pop(module, None)
            if os.path.exists(baseline_path):
                os.remove(baseline_path)
            try:
                next(generator)
            except StopIteration:
                pass

        request.node.parent.addfinalizer(close_module_game)

    _, game_content, baseline_path = cached
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        shutil.copyfile(baseline_path, path)
        db = GameDB(path, game_content)
        state = db.load_state()
        yield db, state, game_content
    finally:
        if db is not None:
            db.close()
        for candidate in (path, f"{path}_agno.db"):
            if os.path.exists(candidate):
                os.remove(candidate)


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
