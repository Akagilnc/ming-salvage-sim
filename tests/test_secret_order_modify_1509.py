"""#1509：现役场景声明按 typed action_id 修改新建密令候选。"""

import json

from ming_sim.audience_night import open_night
from ming_sim.declaration_dispatch import dispatch_declaration


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()[0])


def _pending_payload(db, action_id):
    return json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()[0])


def test_modify_targets_one_pending_and_preserves_unmentioned_fields(game):
    db, state, _content = game
    actor = _minister(db)
    night = open_night(db, state)
    first = db.stage_pending_action(
        state.turn, "secret_order", "新建", actor,
        {"title": "密察关宁", "content": "密察关宁欠饷", "assignee": actor,
         "tags": ["关宁", "欠饷"], "deadline_months": 3,
         "excluded_names": ["魏忠贤"], "excluded_offices": ["内阁"]},
    )
    second = db.stage_pending_action(
        state.turn, "secret_order", "新建", actor,
        {"title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": actor,
         "tags": ["蒙古"], "deadline_months": 2},
    )
    before_first = _pending_payload(db, first)
    before_second = _pending_payload(db, second)
    modified = dispatch_declaration(db, state, {"promises": [{
        "action_id": second, "decision": "修改", "new_content": "只查饷银去向",
    }]}, minister_name=actor, night_id=int(night["id"]))
    assert modified.promises.rejected == []
    assert modified.promises.applied[0]["action_id"] == second
    assert _pending_payload(db, first) == before_first
    assert _pending_payload(db, second) == {**before_second, "content": "只查饷银去向"}


def test_modify_without_target_or_typed_body_does_not_change_pending(game):
    db, state, _content = game
    actor = _minister(db)
    night = open_night(db, state)
    candidate = db.stage_pending_action(
        state.turn, "secret_order", "新建", actor,
        {"title": "密察关宁", "content": "原正文", "assignee": actor},
    )
    original = _pending_payload(db, candidate)
    for item in (
        {"decision": "修改", "new_content": "另拟正文"},
        {"action_id": candidate, "decision": "修改", "new_content": "   "},
    ):
        result = dispatch_declaration(
            db, state, {"promises": [item]}, minister_name=actor,
            night_id=int(night["id"]),
        )
        assert result.promises.applied == []
        assert result.promises.rejected
        assert _pending_payload(db, candidate) == original
