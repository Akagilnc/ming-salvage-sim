"""#389 / #1897：事件亲裁选择→事件的绑定以权威候选快照的显式 id 为真源。

回显 id 只有确属本回合候选才采信；缺 id / off-snapshot id 解绑。
呈现标题不得补造或重绑 event_id（#1897 K2 / ADR0142 / #1900 J20）。
"""

import pytest

from ming_sim.models import TurnPhase
from ming_sim.session import GameSession


@pytest.mark.parametrize(("echo", "title", "candidates", "expected"), [
    ("candidate", "另一标题", [{"id": "candidate", "title": "裁断"}], "candidate"),
    ("off-snapshot", "裁断", [{"id": "candidate", "title": "裁断"}], None),
    ("off-snapshot", "不相干", [{"id": "candidate", "title": "裁断"}], None),
    (None, "裁断", [{"id": "candidate", "title": "裁断"}], ""),
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


@pytest.mark.parametrize("simulator_payload", [
    None,           # 无 resolve_context
    {"other": 1},   # 有 context 但无 candidate_events
])
def test_no_snapshot_at_player_prewrite_keeps_echo(game, simulator_payload):
    """无快照独立输入类：经真实 player-prewrite 入口，回显 event_id 原样保留。"""
    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    db.save_pending_decisions(state.turn, [
        {"title": "t", "event_id": "x", "options": [{"label": "留", "hint": "候旨"}]},
    ])
    if simulator_payload is not None:
        db.save_resolve_context(state.turn, "诏", simulator_payload)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    key = db.list_rescript_desk(state.turn)[0]["decision_key"]

    prepared = session.prepare_rescript_prewrite([
        {"decision_key": key, "label": "留", "note": "暂留"},
    ])

    assert prepared["batch"].items[0].row.get("event_id") == "x"
    assert db.list_pending_decisions(state.turn)[0]["status"] == "pending"
