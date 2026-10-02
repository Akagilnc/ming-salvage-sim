"""Candidate authority is enforced when the player submits the rescript desk."""

import pytest

from ming_sim.models import TurnPhase
from ming_sim.session import GameSession


@pytest.mark.parametrize(("echo", "title", "candidates", "expected"), [
    (None, "裁断", [{"id": "candidate", "title": "裁断"}], "candidate"),
    ("candidate", "另一标题", [{"id": "candidate", "title": "裁断"}], "candidate"),
    ("off-snapshot", "裁断", [{"id": "candidate", "title": "裁断"}], "candidate"),
    ("off-snapshot", "不相干", [{"id": "candidate", "title": "裁断"}], None),
    (None, "同名", [{"id": "a", "title": "同名"}, {"id": "b", "title": "同名"}], ""),
])
def test_candidate_binding_at_player_prewrite(game, echo, title, candidates, expected):
    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    row = {"title": title, "options": [{"label": "留", "hint": "候旨"}]}
    if echo is not None:
        row["event_id"] = echo
    db.save_pending_decisions(state.turn, [row])
    db.save_resolve_context(state.turn, "诏", {"candidate_events": candidates})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    key = db.list_rescript_desk(state.turn)[0]["decision_key"]

    triggers_before = db.conn.execute("SELECT * FROM event_triggers").fetchall()
    prepared = session.prepare_rescript_prewrite([
        {"decision_key": key, "label": "留", "note": "暂留"},
    ])

    assert prepared["batch"].items[0].row.get("event_id") == expected
    assert db.list_pending_decisions(state.turn)[0]["status"] == "pending"
    assert db.conn.execute("SELECT * FROM event_triggers").fetchall() == triggers_before
