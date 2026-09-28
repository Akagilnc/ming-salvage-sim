"""#504：反悔只撤指定的现役暂存；新的真实免职另立候选。"""

from __future__ import annotations

import json

from ming_sim.declaration_dispatch import dispatch_declaration


def _minister(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and getattr(ch, "office", "")
        and db.get_character_status(ch.name)[0] == "active"
    )


def _office_rows(db, turn):
    return [row for row in db.list_pending_actions(turn) if row["kind"] == "office"]


def _appoint(db, state, minister, *, action, office):
    result = dispatch_declaration(db, state, {"commissions": [{
        "text": "任免具奏。",
        "appointment": {"appoint_action": action, "name": minister.name, "office": office},
    }]}, minister_name=minister.name)
    assert not result.commissions.rejected
    return result


def _reject(db, state, minister, action_id):
    return dispatch_declaration(db, state, {"promises": [{
        "action_id": action_id, "decision": "拒绝",
    }]}, minister_name=minister.name).promises


def test_reconsider_dismissal_leaves_incumbent_in_place(game):
    db, state, content = game
    minister = _minister(db, content)
    _appoint(db, state, minister, action="罢免", office=minister.office)
    pending = _office_rows(db, state.turn)
    assert len(pending) == 1

    result = _reject(db, state, minister, int(pending[0]["id"]))

    assert len(result.applied) == 1 and not result.rejected
    assert _office_rows(db, state.turn) == []
    assert db.get_character_status(minister.name)[0] == "active"


def test_reconsider_reassignment_then_dismiss_incumbent(game):
    db, state, content = game
    minister = _minister(db, content)
    new_office = next(o for o in ("陕西巡抚", "蓟辽总督", "钦差督师") if o != minister.office)
    _appoint(db, state, minister, action="任命", office=new_office)
    pending = _office_rows(db, state.turn)
    assert len(pending) == 1

    result = _reject(db, state, minister, int(pending[0]["id"]))
    assert len(result.applied) == 1 and not result.rejected
    _appoint(db, state, minister, action="罢免", office=minister.office)

    remaining = _office_rows(db, state.turn)
    assert len(remaining) == 1 and remaining[0]["action"] == "罢免"
    assert json.loads(remaining[0]["payload_json"])["name"] == minister.name


def test_reconsider_without_candidate_does_not_remove_unrelated_pending(game):
    db, state, content = game
    minister = _minister(db, content)
    _appoint(db, state, minister, action="罢免", office=minister.office)
    pending = _office_rows(db, state.turn)
    assert len(pending) == 1

    result = _reject(db, state, minister, int(pending[0]["id"]) + 100000)

    assert not result.applied and len(result.rejected) == 1
    assert [row["id"] for row in _office_rows(db, state.turn)] == [pending[0]["id"]]
