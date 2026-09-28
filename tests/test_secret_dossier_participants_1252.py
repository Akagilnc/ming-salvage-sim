"""#1252: 密令案卷参与人私密更新 rail（#883 隔离下的私字段+冻结授权）。"""

from __future__ import annotations

import json

import pytest

from tests.conftest import with_monthly_reports
from tests.dossier_test_helpers import TYPED_COVERT_TASK
from tests.dossier_test_helpers import create_test_secret_order

def _actor(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])

def _people(db, count):
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT ?",
        (int(count),),
    ).fetchall()
    assert len(rows) >= count
    return [str(row["name"]) for row in rows]

def _secret(db, state, *, title="密查漕弊", body="暗访仓胥", tags=None):
    lead = _actor(db)
    order_id = create_test_secret_order(db,
        state, lead, title, body, tags or ["稽核"], deadline_months=3,
        covert_task=TYPED_COVERT_TASK,
    )
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier is not None
    return lead, int(order_id), int(dossier["id"])

def _grouped(db, state, order_ids=None):
    from ming_sim.settlement_payload import (
        group_secret_orders_for_sim,
        _select_secret_orders_for_sim,
    )

    if order_ids is None:
        rows = _select_secret_orders_for_sim(db)
    else:
        wanted = {int(oid) for oid in order_ids}
        rows = [
            row for row in db.list_secret_orders()
            if int(row["id"]) in wanted
        ]
    return group_secret_orders_for_sim(rows)

# ── S1: 私读缝 ──────────────────────────────────────────────

def test_s1_private_rail_exposes_secret_dossier_id_and_roster(game):
    """personnel_secret 私轨为本批密令暴露 dossier_id+participant_roster。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, _content = game
    lead, order_id, dossier_id = _secret(db, state)
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": lead, "tier": "主办", "role": "密访",
    }], state=state)

    public = build_simulator_payload(state, db, "", "")
    assert all(
        int(row["id"]) != dossier_id
        for row in public.get("decree_dossiers") or []
        if isinstance(row, dict) and row.get("id") is not None
    )
    assert str(dossier_id) not in str(public.get("secret_orders") or "")

def test_s1_public_projection_filter_unchanged(game):
    """不动 #883 list_decree_dossiers_for_simulation 滤除。"""
    db, state, _content = game
    _lead, _order_id, dossier_id = _secret(db, state)
    visible = db.list_decree_dossiers_for_simulation(state.turn)
    assert all(int(row["id"]) != dossier_id for row in visible)
    assert all(str(row.get("action_type") or "") != "secret_order" for row in visible)

# ── S2: 私字段 + 冻结授权 + apply ───────────────────────────

def test_s2_secret_field_appends_via_prepare_then_settle(game):
    """真实 prepare+settle 入口可落密令 roster（secret_dossier_participants）。"""
    from tests.section_rejection_helpers import prepare_then_settle
    import ming_sim.issues as issue_engine

    db, state, content = game
    lead, worker = _people(db, 2)
    order_id = create_test_secret_order(db,
        state, lead, "密查仓胥", "暗访通州仓", ["密访"], deadline_months=1,
        covert_task=TYPED_COVERT_TASK,
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": lead, "tier": "主办", "role": "密访",
    }], state=state)

    # 直接走 apply 生产入口：secret 权威显式传入
    result = issue_engine.apply_score_extraction(db, state, {
        "secret_dossier_participants": [{
            "dossier_id": dossier_id,
            "character_id": worker,
            "tier": "协办",
            "role": "随员核账",
            "delegator_id": lead,
        }],
    }, secret_dossier_ids_at_input={dossier_id})
    assert result["secret_dossier_participants"][0].get("rejected") is not True
    roster = db.get_decree_dossier(dossier_id)["participant_roster"]
    assert any(
        row.get("character_id") == worker and row.get("tier") == "协办"
        for row in roster
    )

@pytest.mark.parametrize("authority", [None, set()])
def test_s2_missing_secret_authority_never_rebuilds_from_live_db(game, authority):
    """⑤ 私授权 None/空集不重建。"""
    import ming_sim.issues as issue_engine

    db, state, _content = game
    lead, worker = _people(db, 2)
    _o, dossier_id = _secret(db, state)[1:]
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": lead, "tier": "主办", "role": "密访",
    }], state=state)
    result = issue_engine.apply_score_extraction(db, state, {
        "secret_dossier_participants": [{
            "dossier_id": dossier_id, "character_id": worker,
            "tier": "协办", "delegator_id": lead,
        }],
    }, secret_dossier_ids_at_input=authority)
    assert result["secret_dossier_participants"][0]["rejected"] is True
    assert len(db.get_decree_dossier(dossier_id)["participant_roster"]) == 1

def test_s3_runtime_contract_owns_secret_field():
    """私字段归 personnel_secret：钉 MODULE_FIELDS/EMPTY_EXTRACTION/TOP_LEVEL_ALIASES。"""
    from ming_sim.simulation import (
        EMPTY_EXTRACTION,
        MODULE_FIELDS,
        TOP_LEVEL_ALIASES,
    )

    assert "secret_dossier_participants" in MODULE_FIELDS["personnel_secret"]
    assert "secret_dossier_participants" not in MODULE_FIELDS["issues"]
    assert "secret_dossier_participants" in EMPTY_EXTRACTION
    assert TOP_LEVEL_ALIASES["密令案卷参与人"] == "secret_dossier_participants"
