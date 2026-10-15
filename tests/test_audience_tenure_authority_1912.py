"""#1912 召对声明补任别与授收权：真实入口成案、生效、打回不落、重开接续。

材料可读性由生产侧 character_context_with_db 挂接 appointment_tenure_context /
held_authority_context 承担；本文件只钉结构化账本与生命周期，不锁呈现措辞。
"""

from __future__ import annotations

import json

from ming_sim.audience_translate import build_c0_declaration_shape
from ming_sim.db import GameDB
from ming_sim.models import Character
from ming_sim.settlement.dossier import apply_dossier_promulgation, apply_dossier_verdicts
from ming_sim.supervision import character_tenure
from tests.readback_helpers import active_character_name as _minister
from tests.test_audience_translate_1837_reopen import _close_offline, _scene_declaration


def _add_white_body(db, state, content, name: str) -> None:
    person = Character(
        name=name, office="白身", office_type="布衣", faction="中立",
        aliases=[], personal_skills=[], loyalty=50, ability=50, integrity=50,
        courage=50, style="", power_id="ming",
    )
    db.add_character(state, person)
    content.characters[name] = person


def _pending_payload(db, pending_id: int) -> dict:
    row = db.conn.execute(
        "SELECT payload_json, status, night_approved FROM pending_actions WHERE id=?",
        (int(pending_id),),
    ).fetchone()
    return {
        **json.loads(str(row["payload_json"] or "{}")),
        "_status": row["status"],
        "_night_approved": int(row["night_approved"] or 0),
    }


def _dossier_for_pending(db, pending_id: int) -> dict:
    return next(
        row for row in db.dossiers.list_dossiers()
        if row["pending_action_id"] == pending_id
    )


def _latest_pending(db, *, kind: str | None = None) -> int:
    sql = "SELECT id FROM pending_actions WHERE status='pending'"
    params: list[object] = []
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    sql += " ORDER BY id DESC LIMIT 1"
    row = db.conn.execute(sql, params).fetchone()
    assert row is not None
    return int(row["id"])


def _scene_commission(db, state, content, monkeypatch, declaration, *, minister, words):
    return _scene_declaration(
        db, state, content, monkeypatch, words, declaration,
        minister_name=minister,
    )


def _approve_pending(db, state, content, monkeypatch, pending_id: int, *, minister):
    return _scene_declaration(
        db, state, content, monkeypatch, "准。",
        {"promises": [{"action_id": int(pending_id), "decision": "应允"}]},
        minister_name=minister,
    )


def _close_current_night(db, state, content):
    night = db.conn.execute(
        "SELECT id FROM audience_nights WHERE status!='closed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert night is not None
    return _close_offline(db, state, content, int(night["id"]))


def _office_tenure(db, name: str) -> str:
    row = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (name,),
    ).fetchone()
    assert row is not None
    return str(row["appointment_tenure"])


def _active_privileges(db, state, holder: str) -> list[str]:
    return [
        str(row["privilege"])
        for row in db.characters.list_active_authorities(
            int(state.turn), holder_id=holder,
        )
    ]


def test_c0_shape_exposes_tenure_and_authority_slots():
    shape = build_c0_declaration_shape()
    assert '"任别"' in shape
    assert '"authorization"' in shape
    assert '"revoke_authority"' in shape
    assert "尚方剑密授" in shape


def test_acting_appointment_real_entry_lands_tenure_and_restore(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    appointee = "户部验收甲"
    _add_white_body(db, state, content, appointee)

    _scene_commission(
        db, state, content, monkeypatch,
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
        minister=minister,
        words="着户部验收甲署理户部右侍郎。",
    )
    pending_id = _latest_pending(db, kind="office")
    staged = _pending_payload(db, pending_id)
    assert staged.get("任别") == "署理"
    assert staged["_night_approved"] == 0

    _approve_pending(db, state, content, monkeypatch, pending_id, minister=minister)
    assert _pending_payload(db, pending_id)["_night_approved"] == 1

    _close_current_night(db, state, content)
    dossier = _dossier_for_pending(db, pending_id)
    assert json.loads(str(dossier["payload_json"] or "{}")).get("任别") == "署理"

    apply_dossier_promulgation(
        db, state, int(dossier["id"]), "promulgated", content=content,
    )
    assert _office_tenure(db, appointee) == "署理"
    assert character_tenure(db, appointee) == "署理"

    # 同职改真除：须再成案，不得被无动作吞掉（ADR 0064）。
    _scene_commission(
        db, state, content, monkeypatch,
        {
            "commissions": [{
                "text": "着实授户部右侍郎",
                "appointment": {
                    "name": appointee,
                    "office": "户部右侍郎",
                    "appoint_action": "任命",
                    "任别": "真除",
                },
            }],
        },
        minister=minister,
        words="着户部验收甲实授户部右侍郎。",
    )
    convert_id = _latest_pending(db, kind="office")
    assert convert_id != pending_id
    assert _pending_payload(db, convert_id).get("任别") == "真除"
    _approve_pending(db, state, content, monkeypatch, convert_id, minister=minister)
    _close_current_night(db, state, content)
    convert_dossier = _dossier_for_pending(db, convert_id)
    apply_dossier_promulgation(
        db, state, int(convert_dossier["id"]), "promulgated", content=content,
    )
    assert _office_tenure(db, appointee) == "真除"
    assert character_tenure(db, appointee) == "真除"

    db_path = db.path
    db.conn.close()
    restored = GameDB(db_path, content)
    assert restored.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (appointee,),
    ).fetchone()["appointment_tenure"] == "真除"
    assert character_tenure(restored, appointee) == "真除"


def test_grant_revoke_authority_real_entry_and_region_scope(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    holder = "持剑验收乙"
    _add_white_body(db, state, content, holder)

    _scene_commission(
        db, state, content, monkeypatch,
        {
            "commissions": [{
                "text": "赐尚方剑，许便宜行事",
                "authorization": {
                    "name": holder,
                    "privilege": "尚方剑密授",
                },
            }],
        },
        minister=minister,
        words="赐持剑验收乙尚方剑。",
    )
    grant_id = _latest_pending(db, kind="directive")
    grant_payload = _pending_payload(db, grant_id)
    assert grant_payload.get("dossier_action_type") == "authorization"
    assert grant_payload.get("privilege") == "尚方剑密授"
    assert grant_payload.get("locality_scope") == "none"
    _approve_pending(db, state, content, monkeypatch, grant_id, minister=minister)
    _close_current_night(db, state, content)
    grant_dossier = _dossier_for_pending(db, grant_id)
    assert grant_dossier["action_type"] == "authorization"
    apply_dossier_promulgation(
        db, state, int(grant_dossier["id"]), "promulgated", content=content,
    )
    held = db.characters.list_active_authorities(int(state.turn), holder_id=holder)
    assert len(held) == 1
    assert held[0]["privilege"] == "尚方剑密授"
    assert _active_privileges(db, state, holder) == ["尚方剑密授"]

    # 省域专差：须带 locality_scope=single，收夜可成案。
    _scene_commission(
        db, state, content, monkeypatch,
        {
            "commissions": [{
                "text": "着专差督办陕西军务",
                "authorization": {
                    "name": holder,
                    "privilege": "专差督办",
                    "target_kind": "region",
                    "target_id": "shaanxi",
                },
            }],
        },
        minister=minister,
        words="着持剑验收乙专差督办陕西军务。",
    )
    region_id = _latest_pending(db, kind="directive")
    region_payload = _pending_payload(db, region_id)
    assert region_payload.get("target_kind") == "region"
    assert region_payload.get("target_id") == "shaanxi"
    assert region_payload.get("locality_scope") == "single"
    assert region_payload.get("scope") == "region:shaanxi"
    _approve_pending(db, state, content, monkeypatch, region_id, minister=minister)
    _close_current_night(db, state, content)
    region_dossier = _dossier_for_pending(db, region_id)
    assert region_dossier["action_type"] == "authorization"
    apply_dossier_promulgation(
        db, state, int(region_dossier["id"]), "promulgated", content=content,
    )
    assert set(_active_privileges(db, state, holder)) == {"尚方剑密授", "专差督办"}

    _scene_commission(
        db, state, content, monkeypatch,
        {
            "commissions": [{
                "text": "收回尚方剑",
                "revoke_authority": {
                    "name": holder,
                    "privilege": "尚方剑密授",
                },
            }],
        },
        minister=minister,
        words="收回持剑验收乙尚方剑。",
    )
    revoke_id = _latest_pending(db, kind="directive")
    revoke_payload = _pending_payload(db, revoke_id)
    assert revoke_payload.get("dossier_action_type") == "revoke_authority"
    assert int(revoke_payload.get("authority_id") or 0) == int(held[0]["id"])
    _approve_pending(db, state, content, monkeypatch, revoke_id, minister=minister)
    _close_current_night(db, state, content)
    apply_dossier_promulgation(
        db, state, int(_dossier_for_pending(db, revoke_id)["id"]),
        "promulgated", content=content,
    )
    assert _active_privileges(db, state, holder) == ["专差督办"]

    db_path = db.path
    db.conn.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    assert [
        str(row["privilege"])
        for row in restored.characters.list_active_authorities(
            int(restored_state.turn), holder_id=holder,
        )
    ] == ["专差督办"]


def test_rejected_authorization_does_not_land_held_privilege(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    holder = "打回授权丙"
    _add_white_body(db, state, content, holder)

    _scene_commission(
        db, state, content, monkeypatch,
        {
            "commissions": [{
                "text": "赐便宜行事",
                "authorization": {
                    "name": holder,
                    "privilege": "便宜行事",
                },
            }],
        },
        minister=minister,
        words="赐打回授权丙便宜行事。",
    )
    pending_id = _latest_pending(db, kind="directive")
    _approve_pending(db, state, content, monkeypatch, pending_id, minister=minister)
    _close_current_night(db, state, content)
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
    assert _active_privileges(db, state, holder) == []
