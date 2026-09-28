"""#518 恩赏·拨帑：真实候选、案卷与 ADR 0055 钱粮/叙事效果。

Seams:
- commit_pending_actions（收夜落案卷；国库源不成效果）
- apply_dossier_verdicts / create_decree_dossier（0055：国库判决后落，内帑豁免直落）
- create_fiscal_item / list_fiscal_effects_for_dossier / apply_fixed_period_flows
- person_logs 开放标签；characters.office 不被加衔覆盖
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    candidates_from_classifier_payload,
)
from ming_sim.action_materialize import stage_grant_allocation_candidate
from ming_sim.decree import reload_state_from_db
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.declaration_dispatch import dispatch_declaration
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict




def _active_ming(db, content, *, exclude=""):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )




def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )
















def _scene_grant(db, state, actor):
    result = dispatch_declaration(db, state, {"commissions": [{
        "text": "臣请户部发帑三十万两赈陕西灾民。",
        "grant": {"grant_action": "赈灾", "amount": 30,
                  "account": "国库", "target_kind": "region", "target_id": "shaanxi"},
    }]}, minister_name=actor.name)
    assert result.commissions.rejected == []
    return result.commissions.applied[0]["id"]


def test_scene_grant_stages_then_close_night(game):
    """场景交办暂存拨帑；收夜落案卷后国库仍待判决。"""
    db, state, content = game
    actor = _active_ming(db, content)
    treasury_before = int(state.metrics["国库"])
    pending_id = _scene_grant(db, state, actor)
    assert pending_id
    staged = next(p for p in db.list_pending_actions(state.turn) if int(p["id"]) == pending_id)
    assert json.loads(staged["payload_json"])["locality_scope"] == "single"
    assert int(state.metrics["国库"]) == treasury_before
    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "grant_allocation"
    assert int(state.metrics["国库"]) == treasury_before
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert int(state.metrics["国库"]) == treasury_before - 30








def test_scene_confirm_accept_does_not_spend_treasury(game):
    """应允只过确认闸，不得在判决前扣国库。"""
    db, state, content = game
    actor = _active_ming(db, content)
    treasury_before = int(state.metrics["国库"])
    pending_id = _scene_grant(db, state, actor)
    approved = dispatch_declaration(db, state, {"promises": [{
        "action_id": pending_id, "decision": "应允",
    }]}, minister_name=actor.name)
    assert approved.promises.rejected == []
    assert approved.promises.applied[0]["action_id"] == pending_id
    assert int(state.metrics["国库"]) == treasury_before


def _grant_pending_payloads(db, turn, *, target_id, grant_action):
    rows = []
    for row in db.list_pending_actions(int(turn)):
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "grant_allocation":
            continue
        if str(payload.get("target_id") or "").strip() != target_id:
            continue
        if str(payload.get("grant_action") or "").strip() != grant_action:
            continue
        rows.append((int(row["id"]), payload))
    return rows






def test_explicit_target_candidate_still_updates_named_grant(game):
    """明确结构化修改指向时，仍只更新被点名的那一道拨款候选。"""
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    db, state, content = game
    target = _active_ming(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    first_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=f"赏{target.name}银十万两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=target.name,
        amount=10,
        account="国库",
        cadence="一次性",
    )
    other_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=f"另赏{target.name}银三万两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=target.name,
        amount=3,
        account="国库",
        cadence="一次性",
    )
    assert first_id and other_id and first_id != other_id

    updated_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=f"前道赏银改作每月五万两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=target.name,
        amount=5,
        account="国库",
        cadence="每月",
        target_candidate=str(first_id),
    )
    assert updated_id == first_id

    staged = dict(_grant_pending_payloads(
        db, state.turn, target_id=target.name, grant_action="赏赉",
    ))
    assert set(staged) == {first_id, other_id}
    assert int(staged[first_id].get("amount") or 0) == 5
    assert staged[first_id].get("cadence") == "每月"
    assert int(staged[other_id].get("amount") or 0) == 3
    assert staged[other_id].get("cadence") == "一次性"


def _grant_field_zh(name: str) -> str:
    from ming_sim.action_clusters import cluster_by_kind

    grant = cluster_by_kind("grant_allocation")
    assert grant is not None
    for spec in grant.fields:
        if spec.name == name:
            return spec.zh
    raise AssertionError(f"grant_allocation missing FieldSpec {name!r}")






def test_ordinary_grant_bogus_execution_surface_fails_at_durable(game):
    """#1624：非法非空 execution_surface 经 stage→commit 不得成案。

    修前 stage 洗空后 durable 默认 in_transit 静默落 dossier；修后 pending failed、无案卷。
    """
    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    pending_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text="调银十二万两赈灾。",
        grant_action="赈灾",
        target_kind="region",
        target_id="shaanxi",
        amount=12,
        account="国库",
        execution_surface="bogus_not_a_surface",
    )
    assert pending_id
    result = db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    assert result == []
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()
    assert row["status"] == "failed"
    assert not any(
        d.get("pending_action_id") == pending_id for d in db.list_decree_dossiers()
    )




def test_grant_shape_accepts_integer_string_rejects_bool_float():
    """#1716：grant shape 唯一权威接纳整数字符串；bool/float 仍 fail-loud（#1620）。"""
    import pytest
    from ming_sim.action_materialize import require_grant_allocation_shape

    shaped = require_grant_allocation_shape(
        grant_action="赈灾", amount="8", account="国库",
    )
    assert shaped["amount"] == 8
    assert shaped["account"] == "国库"
    with pytest.raises(ValueError):
        require_grant_allocation_shape(
            grant_action="赈灾", amount=True, account="国库",
        )
    with pytest.raises(ValueError):
        require_grant_allocation_shape(
            grant_action="赈灾", amount=1.5, account="国库",
        )


def test_legacy_grant_allocation_requires_explicit_account(game):
    """#1716：普通/legacy fallback 缺 grant_action 时不得默认国库；空串/None 均拒。"""
    import pytest

    db, _state, _content = game
    base = {
        "dossier_action_type": "grant_allocation",
        "amount": 10,
        "target_kind": "issue",
        "target_id": "relief",
        "execution_surface": "immediate",
    }
    for account in (None, "", "  "):
        payload = dict(base)
        if account is not None:
            payload["account"] = account
        with pytest.raises(ValueError):
            db._normalize_directive_dossier_payload(payload)
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({**base, "grant_action": "无"})
    explicit = db._normalize_directive_dossier_payload({
        **base, "grant_action": "赈灾", "account": "",
    })
    assert explicit["account"] == "国库"
    assert int(explicit["amount"]) == 10
    fallback = db._normalize_directive_dossier_payload({
        **base, "account": "内库",
    })
    assert fallback["account"] == "内库"
    assert int(fallback["amount"]) == 10
    assert str(fallback.get("grant_action") or "") != "赏赉"
