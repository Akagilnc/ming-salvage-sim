"""#1912 召对声明补任别与授收权：真实入口成案、生效、打回不落、重开接续。

材料可读性由生产侧 character_context_with_db 挂接 appointment_tenure_context /
held_authority_context 承担；本文件只钉结构化账本与生命周期，不锁呈现措辞。
"""

from __future__ import annotations

import json

import pytest

from ming_sim import audience_night as an
from ming_sim.db import GameDB
from ming_sim.models import Character
from ming_sim.session import AudienceAdmission
from tests.readback_helpers import active_character_name as _minister
from tests.test_audience_translate_1837_reopen import (
    _close_offline,
    _player_month,
    _scene_declaration,
)
from tests.test_audience_travel_gating_670 import _session
from tests.test_transit_countdown_668 import MATRIX


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
        "SELECT payload_json, night_approved FROM pending_actions WHERE id=?",
        (int(pending_id),),
    ).fetchone()
    return {
        **json.loads(str(row["payload_json"] or "{}")),
        "_night_approved": int(row["night_approved"] or 0),
    }


def _dossier_for_pending(db, pending_id: int) -> dict:
    return next(
        row for row in db.dossiers.list_dossiers()
        if row["pending_action_id"] == pending_id
    )


def _staged_commission_id(result) -> int:
    """本次交办 id：入口 applied 已给出，不另查最新 pending。"""
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    return int(result.commissions.applied[0]["id"])


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
    """Read persisted appointment_tenure; missing office row must fail (not 真除 fallback)."""
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


def _rejected_verdict(db, *, minister: str) -> dict:
    faction = db.conn.execute("SELECT name FROM factions LIMIT 1").fetchone()["name"]
    return {
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": faction}],
        "gatekeeper_id": minister,
        "reason": "名器不可轻授",
        "criteria_snapshot": {
            "imperial_authority_band": "中等",
            "appointment_tenure": "",
            "authorization_ids": [],
            "endorsement_entry_ids": [],
        },
        "affected_parties": [{
            "kind": "faction", "key": faction,
            "direction": "negative", "intensity": "weak",
        }],
    }


def test_acting_appointment_real_entry_lands_tenure_and_restore(game, monkeypatch):
    """#1912 署理→真除；#1929 开局徐光启起复后仍在南直隶，宣召按权威路程启程。"""
    db, state, content = game
    minister = _minister(db)
    appointee = "徐光启"
    sess = _session(game)
    assert db.characters.row(appointee)["status"] != "active"
    assert not sess.admit_audience(content.characters[appointee]).allowed

    staged_result = _scene_declaration(
        db, state, content, monkeypatch,
        "着徐光启署理户部右侍郎。",
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
    pending_id = _staged_commission_id(staged_result)
    assert staged_result.commissions.applied[0].get("kind") == "office"
    staged = _pending_payload(db, pending_id)
    assert staged.get("任别") == "署理"
    assert staged["_night_approved"] == 0

    _approve_pending(db, state, content, monkeypatch, pending_id, minister=minister)
    assert _pending_payload(db, pending_id)["_night_approved"] == 1

    _close_current_night(db, state, content)
    dossier = _dossier_for_pending(db, pending_id)
    assert json.loads(str(dossier["payload_json"] or "{}")).get("任别") == "署理"

    # 收夜成案后、月链颁布前：仍 offstage，不可宣。
    assert db.characters.row(appointee)["status"] != "active"
    assert not sess.admit_audience(content.characters[appointee]).allowed
    _player_month(db, state, content, monkeypatch, int(dossier["id"]))
    assert _office_tenure(db, appointee) == "署理"
    assert db.characters.row(appointee)["status"] == "active"
    assert sess.consume_audience_admission(
        content.characters[appointee], origin_id="web:1929:xu", state=state,
    ).result is AudienceAdmission.SUMMON_FRESH
    night_id = int(an.list_unsettled_summons(db)[0]["night_id"])
    an.close_night(db, state, night_id=night_id, content=content)
    departed = db.characters.row(appointee)
    assert (departed["location"], departed["transit_to"]) == ("nanzhili", "beizhili")
    assert departed["transit_distance_remaining"] == pytest.approx(
        MATRIX.travel_time("nanzhili", "beizhili"),
    )

    # 同职改真除：须再成案，不得被无动作吞掉（ADR 0064）。
    convert_result = _scene_declaration(
        db, state, content, monkeypatch,
        "着徐光启实授户部右侍郎。",
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
        minister_name=minister,
    )
    convert_id = _staged_commission_id(convert_result)
    assert convert_id != pending_id
    assert convert_result.commissions.applied[0].get("kind") == "office"
    assert _pending_payload(db, convert_id).get("任别") == "真除"
    _approve_pending(db, state, content, monkeypatch, convert_id, minister=minister)
    _close_current_night(db, state, content)
    convert_dossier = _dossier_for_pending(db, convert_id)
    _player_month(db, state, content, monkeypatch, int(convert_dossier["id"]))
    assert _office_tenure(db, appointee) == "真除"

    db_path = db.path
    db.conn.close()
    restored = GameDB(db_path, content)
    assert _office_tenure(restored, appointee) == "真除"


def test_grant_revoke_authority_real_entry_and_region_scope(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    holder = "持剑验收乙"
    _add_white_body(db, state, content, holder)

    grant_result = _scene_declaration(
        db, state, content, monkeypatch,
        "赐持剑验收乙尚方剑。",
        {
            "commissions": [{
                "text": "赐尚方剑，许便宜行事",
                "authorization": {
                    "name": holder,
                    "privilege": "尚方剑密授",
                    "target_kind": "character",
                    "target_id": holder,
                },
            }],
        },
        minister_name=minister,
    )
    grant_id = _staged_commission_id(grant_result)
    assert grant_result.commissions.applied[0].get("kind") == "directive"
    grant_payload = _pending_payload(db, grant_id)
    assert grant_payload.get("dossier_action_type") == "authorization"
    assert grant_payload.get("privilege") == "尚方剑密授"
    assert grant_payload.get("locality_scope") == "none"
    _approve_pending(db, state, content, monkeypatch, grant_id, minister=minister)
    _close_current_night(db, state, content)
    grant_dossier = _dossier_for_pending(db, grant_id)
    assert grant_dossier["action_type"] == "authorization"
    _player_month(db, state, content, monkeypatch, int(grant_dossier["id"]))
    held = db.characters.list_active_authorities(int(state.turn), holder_id=holder)
    assert [str(row["privilege"]) for row in held] == ["尚方剑密授"]

    # 省域专差：须带 locality_scope=single，收夜可成案。
    region_result = _scene_declaration(
        db, state, content, monkeypatch,
        "着持剑验收乙专差督办陕西军务。",
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
        minister_name=minister,
    )
    region_id = _staged_commission_id(region_result)
    assert region_result.commissions.applied[0].get("kind") == "directive"
    region_payload = _pending_payload(db, region_id)
    assert region_payload.get("target_kind") == "region"
    assert region_payload.get("target_id") == "shaanxi"
    assert region_payload.get("locality_scope") == "single"
    assert region_payload.get("scope") == "region:shaanxi"
    _approve_pending(db, state, content, monkeypatch, region_id, minister=minister)
    _close_current_night(db, state, content)
    region_dossier = _dossier_for_pending(db, region_id)
    assert region_dossier["action_type"] == "authorization"
    _player_month(db, state, content, monkeypatch, int(region_dossier["id"]))
    assert set(_active_privileges(db, state, holder)) == {"尚方剑密授", "专差督办"}

    revoke_result = _scene_declaration(
        db, state, content, monkeypatch,
        "收回持剑验收乙尚方剑。",
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
    revoke_id = _staged_commission_id(revoke_result)
    assert revoke_result.commissions.applied[0].get("kind") == "directive"
    revoke_payload = _pending_payload(db, revoke_id)
    assert revoke_payload.get("dossier_action_type") == "revoke_authority"
    assert int(revoke_payload.get("authority_id") or 0) == int(held[0]["id"])
    _approve_pending(db, state, content, monkeypatch, revoke_id, minister=minister)
    _close_current_night(db, state, content)
    _player_month(
        db, state, content, monkeypatch,
        int(_dossier_for_pending(db, revoke_id)["id"]),
    )
    assert _active_privileges(db, state, holder) == ["专差督办"]

    db_path = db.path
    db.conn.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    assert _active_privileges(restored, restored_state, holder) == ["专差督办"]


def test_rejected_authorization_does_not_land_held_privilege(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    holder = "打回授权丙"
    _add_white_body(db, state, content, holder)

    staged_result = _scene_declaration(
        db, state, content, monkeypatch,
        "赐打回授权丙便宜行事。",
        {
            "commissions": [{
                "text": "赐便宜行事",
                "authorization": {
                    "name": holder,
                    "privilege": "便宜行事",
                    "target_kind": "character",
                    "target_id": holder,
                },
            }],
        },
        minister_name=minister,
    )
    pending_id = _staged_commission_id(staged_result)
    assert staged_result.commissions.applied[0].get("kind") == "directive"
    _approve_pending(db, state, content, monkeypatch, pending_id, minister=minister)
    _close_current_night(db, state, content)
    dossier = _dossier_for_pending(db, pending_id)
    result = _player_month(
        db, state, content, monkeypatch, int(dossier["id"]),
        verdict=_rejected_verdict(db, minister=minister),
    )
    assert result.awaiting is True
    assert result.stage == "rescript"
    rejected = db.dossiers.get(int(dossier["id"]))
    assert rejected["promulgation_decision"] == "rejected"
    assert rejected["rescript_pending"] is True
    assert _active_privileges(db, state, holder) == []
