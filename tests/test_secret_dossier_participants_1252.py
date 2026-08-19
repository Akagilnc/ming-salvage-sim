"""#1252: 密令案卷参与人私密更新 rail（#883 隔离下的私字段+冻结授权）。"""

from __future__ import annotations

import json
import types

import pytest


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
    order_id = db.create_secret_order(
        state, lead, title, body, tags or ["稽核"], deadline_months=3,
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
    from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload

    db, state, _content = game
    lead, order_id, dossier_id = _secret(db, state)
    # Seed an initial roster entry so the read seam has something to show.
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": lead, "tier": "主办", "role": "密访",
    }], state=state)
    grouped = _grouped(db, state, [order_id])

    private = build_extractor_shared_context(
        db, state, "", "", module="personnel_secret", secret_orders=grouped,
    )
    assert "secret_dossier_rosters" in private
    hit = next(
        item for item in private["secret_dossier_rosters"]
        if int(item["dossier_id"]) == dossier_id
    )
    assert hit["participant_roster"][0]["character_id"] == lead
    assert hit["participant_roster"][0]["tier"] == "主办"

    # #883: public modules + simulator never see secret dossier ids.
    public = build_simulator_payload(state, db, "", "")
    assert all(
        int(row["id"]) != dossier_id
        for row in public.get("decree_dossiers") or []
        if isinstance(row, dict) and row.get("id") is not None
    )
    for module in ("issues", "internal", "military_external"):
        ctx = build_extractor_shared_context(
            db, state, "", "", module=module, secret_orders=grouped,
        )
        assert "secret_dossier_rosters" not in ctx
        assert all(
            int(row["id"]) != dossier_id
            for row in ctx.get("decree_dossiers") or []
            if isinstance(row, dict) and row.get("id") is not None
        )
        blob = json.dumps(ctx, ensure_ascii=False)
        assert f'"id": {dossier_id}' not in blob
        assert f'"dossier_id": {dossier_id}' not in blob


def test_s1_public_projection_filter_unchanged(game):
    """不动 #883 list_decree_dossiers_for_simulation 滤除。"""
    db, state, _content = game
    _lead, _order_id, dossier_id = _secret(db, state)
    visible = db.list_decree_dossiers_for_simulation(state.turn)
    assert all(int(row["id"]) != dossier_id for row in visible)
    assert all(str(row.get("action_type") or "") != "secret_order" for row in visible)
