"""#519：同一场景转译的独立交办与按候选 ID 准驳互不污染。"""

from __future__ import annotations

import json

import ming_sim.audience_night as an
from ming_sim.declaration_dispatch import dispatch_declaration


def _actor(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.get_character_status(ch.name)[0] == "active"
        and getattr(ch, "office", "")
    )


def _two_commissions(db, state, name, night_id):
    result = dispatch_declaration(db, state, {"commissions": [
        {"text": "着洪承畴巡抚陕西。", "appointment": {
            "appoint_action": "任命", "name": "洪承畴", "office": "陕西巡抚",
            "region_id": "shaanxi", "mode": "ordinary",
        }},
        {"text": "着户部拨国库银三十万两赈陕西。", "grant": {
            "grant_action": "赈灾", "amount": 30, "account": "国库",
            "target_kind": "region", "target_id": "shaanxi",
        }},
    ]}, minister_name=name, night_id=night_id)
    assert not result.commissions.rejected
    return result


def _pending_pair(db, turn):
    rows = [row for row in db.list_pending_actions(turn)
            if row["kind"] in {"office", "directive"}]
    offices = [row for row in rows if row["kind"] == "office"]
    grants = [row for row in rows if row["kind"] == "directive"]
    assert len(offices) == len(grants) == 1
    return offices[0], grants[0]


def test_one_declaration_stages_independent_office_and_grant(game):
    db, state, content = game
    actor = _actor(db, content)
    _two_commissions(db, state, actor.name, night_id=0)

    office, grant = _pending_pair(db, state.turn)
    assert office["id"] != grant["id"]
    appointment = json.loads(office["payload_json"])
    allocation = json.loads(grant["payload_json"])
    assert appointment["name"] == "洪承畴"
    assert appointment["office"] == "陕西巡抚"
    assert allocation["dossier_action_type"] == "grant_allocation"
    assert allocation["target_id"] == "shaanxi"
    assert allocation["amount"] == 30


def test_one_approved_one_rejected_only_approved_enters_dossiers(game):
    db, state, content = game
    actor = _actor(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    _two_commissions(db, state, actor.name, night_id)
    office, grant = _pending_pair(db, state.turn)

    outcome = dispatch_declaration(db, state, {"promises": [
        {"action_id": int(office["id"]), "decision": "应允"},
        {"action_id": int(grant["id"]), "decision": "拒绝"},
    ]}, minister_name=actor.name, night_id=night_id)
    assert len(outcome.promises.applied) == 2 and not outcome.promises.rejected
    assert int(office["id"]) in {
        int(row["id"]) for row in db.list_night_approved_pending(night_id, kind="office")
    }
    assert int(grant["id"]) not in {int(row["id"]) for row in db.list_pending_actions(state.turn)}

    an.close_night(db, state, night_id=night_id, content=content)
    by_pending = {
        int(row["pending_action_id"]): row for row in db.list_decree_dossiers()
        if row.get("pending_action_id") is not None
    }
    assert int(office["id"]) in by_pending
    assert int(grant["id"]) not in by_pending
