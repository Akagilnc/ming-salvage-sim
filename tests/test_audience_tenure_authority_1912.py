"""#1912 召对声明补任别与授收权：成案、生效、本人读取、打回不落、重开接续。"""

from __future__ import annotations

import json

import pytest

from ming_sim.audience_translate import build_c0_declaration_shape
from ming_sim.context import character_context_with_db
from ming_sim.db import GameDB
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.models import Character
from ming_sim.settlement.dossier import apply_dossier_promulgation, apply_dossier_verdicts
from tests.readback_helpers import active_character_name as _minister


def _add_white_body(db, state, content, name: str) -> None:
    person = Character(
        name=name, office="白身", office_type="布衣", faction="中立",
        aliases=[], personal_skills=[], loyalty=50, ability=50, integrity=50,
        courage=50, style="", power_id="ming",
    )
    db.add_character(state, person)
    content.characters[name] = person


def _load_character(db, content, name: str) -> Character:
    person = content.characters.get(name)
    if person is not None:
        return person
    row = db.characters.row(name)
    assert row is not None, name
    return Character(
        name=name,
        office=str(row["office"] or ""),
        office_type=str(row["office_type"] or ""),
        faction=str(row["faction"] or "中立"),
        aliases=[],
        personal_skills=[],
        power_id=str(row["power_id"] or "ming"),
    )


def _pending_payload(db, pending_id: int) -> dict:
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (int(pending_id),),
    ).fetchone()
    return json.loads(str(row["payload_json"] or "{}"))


def _dossier_for_pending(db, pending_id: int) -> dict:
    return next(
        row for row in db.dossiers.list_dossiers()
        if row["pending_action_id"] == pending_id
    )


def _promulgate_pending(db, state, content, pending_id: int, *, decision: str = "promulgated"):
    db.commit_pending_actions(state, content=content)
    dossier = _dossier_for_pending(db, pending_id)
    apply_dossier_promulgation(
        db, state, int(dossier["id"]), decision, content=content,
    )
    return db.dossiers.get(int(dossier["id"]))


def test_c0_shape_exposes_tenure_and_authority_slots():
    shape = build_c0_declaration_shape()
    assert "任别" in shape
    assert "authorization" in shape
    assert "revoke_authority" in shape
    assert "尚方剑密授" in shape


def test_acting_appointment_lands_tenure_on_archive_and_materials(game):
    db, state, content = game
    minister = _minister(db)
    appointee = "署理验收甲"
    _add_white_body(db, state, content, appointee)

    result = dispatch_declaration(
        db, state,
        {
            "commissions": [{
                "text": "着署理户部右侍郎",
                "appointment": {
                    "name": appointee,
                    "office": "户部右侍郎",
                    "appoint_action": "任命",
                    "任别": "署理",
                },
            }],
        },
        minister_name=minister,
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    pending_id = int(result.commissions.applied[0]["id"])
    staged = _pending_payload(db, pending_id)
    assert staged.get("任别") == "署理" or staged.get("appointment_tenure") == "署理"

    dossier = _promulgate_pending(db, state, content, pending_id)
    payload = json.loads(str(dossier["payload_json"] or "{}"))
    assert payload.get("任别") == "署理"
    office = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (appointee,),
    ).fetchone()
    assert office is not None
    assert office["appointment_tenure"] == "署理"

    person = _load_character(db, content, appointee)
    materials = character_context_with_db(person, db, turn=int(state.turn))
    assert "署理" in materials

    db_path = db.path
    db.conn.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    office_after = restored.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (appointee,),
    ).fetchone()
    assert office_after["appointment_tenure"] == "署理"
    restored_person = _load_character(restored, content, appointee)
    assert "署理" in character_context_with_db(
        restored_person, restored, turn=int(restored_state.turn),
    )


def test_grant_and_revoke_authority_via_commission_round_trip(game):
    db, state, content = game
    minister = _minister(db)
    holder = "持剑验收乙"
    _add_white_body(db, state, content, holder)

    grant = dispatch_declaration(
        db, state,
        {
            "commissions": [{
                "text": "赐尚方剑，许便宜行事",
                "authorization": {
                    "name": holder,
                    "privilege": "尚方剑密授",
                },
            }],
        },
        minister_name=minister,
    )
    assert grant.commissions.rejected == []
    grant_pending = int(grant.commissions.applied[0]["id"])
    grant_payload = _pending_payload(db, grant_pending)
    assert grant_payload.get("dossier_action_type") == "authorization"
    assert grant_payload.get("privilege") == "尚方剑密授"

    grant_dossier = _promulgate_pending(db, state, content, grant_pending)
    assert grant_dossier["action_type"] == "authorization"
    held = db.characters.list_active_authorities(int(state.turn), holder_id=holder)
    assert len(held) == 1
    assert held[0]["privilege"] == "尚方剑密授"
    person = _load_character(db, content, holder)
    materials = character_context_with_db(person, db, turn=int(state.turn))
    assert "在持授权" in materials
    assert "尚方剑" in materials

    revoke = dispatch_declaration(
        db, state,
        {
            "commissions": [{
                "text": "收回尚方剑",
                "revoke_authority": {
                    "name": holder,
                    "privilege": "尚方剑密授",
                },
            }],
        },
        minister_name=minister,
    )
    assert revoke.commissions.rejected == []
    revoke_pending = int(revoke.commissions.applied[0]["id"])
    revoke_payload = _pending_payload(db, revoke_pending)
    assert revoke_payload.get("dossier_action_type") == "revoke_authority"
    assert int(revoke_payload.get("authority_id") or 0) == int(held[0]["id"])

    _promulgate_pending(db, state, content, revoke_pending)
    assert db.characters.list_active_authorities(int(state.turn), holder_id=holder) == []
    after = character_context_with_db(
        _load_character(db, content, holder), db, turn=int(state.turn),
    )
    assert "在持授权" not in after

    db_path = db.path
    db.conn.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    assert restored.characters.list_active_authorities(
        int(restored_state.turn), holder_id=holder,
    ) == []


def test_rejected_authorization_does_not_land_held_privilege(game):
    db, state, content = game
    minister = _minister(db)
    holder = "打回授权丙"
    _add_white_body(db, state, content, holder)

    result = dispatch_declaration(
        db, state,
        {
            "commissions": [{
                "text": "赐便宜行事",
                "authorization": {
                    "name": holder,
                    "privilege": "便宜行事",
                },
            }],
        },
        minister_name=minister,
    )
    pending_id = int(result.commissions.applied[0]["id"])
    db.commit_pending_actions(state, content=content)
    dossier = _dossier_for_pending(db, pending_id)
    apply_dossier_verdicts(
        db,
        state,
        [{
            "dossier_id": int(dossier["id"]),
            "decision": "rejected",
            "blocked_layer": "six_offices",
            "primary_opponents": [{"kind": "faction", "key": "东林"}],
            "gatekeeper_id": minister,
            "reason": "名器不可轻授",
            "criteria_snapshot": {
                "imperial_authority_band": "中等",
                "appointment_tenure": "",
                "authorization_ids": [],
                "endorsement_entry_ids": [],
            },
            "affected_parties": [{
                "kind": "faction", "key": "东林",
                "direction": "negative", "intensity": "weak",
            }],
        }],
        content=content,
    )
    apply_dossier_promulgation(
        db, state, int(dossier["id"]), "withdrawn", content=content,
    )
    assert db.characters.list_active_authorities(int(state.turn), holder_id=holder) == []
    materials = character_context_with_db(
        _load_character(db, content, holder), db, turn=int(state.turn),
    )
    assert "在持授权" not in materials
