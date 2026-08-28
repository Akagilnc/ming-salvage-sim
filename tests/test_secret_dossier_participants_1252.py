"""#1252: 密令案卷参与人私密更新 rail（#883 隔离下的私字段+冻结授权）。"""

from __future__ import annotations

import json
import types

import pytest

from tests.conftest import with_monthly_reports


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




def test_s1_public_projection_filter_unchanged(game):
    """不动 #883 list_decree_dossiers_for_simulation 滤除。"""
    db, state, _content = game
    _lead, _order_id, dossier_id = _secret(db, state)
    visible = db.list_decree_dossiers_for_simulation(state.turn)
    assert all(int(row["id"]) != dossier_id for row in visible)
    assert all(str(row.get("action_type") or "") != "secret_order" for row in visible)


# ── S2: 私字段 + 冻结授权 + apply ───────────────────────────




def test_s2_tracer_613_565_readers_see_appended_roster(game):
    """② 同一 tracer 尾断言 #613/#565 读端可见追加参与人。"""
    import ming_sim.issues as issue_engine
    from ming_sim.decree import execution_side_read_fields
    from ming_sim.participant_roster import project_execution_liability_parties
    from tests.test_authority_ledger_611 import _grant

    db, state, content = game
    lead, worker = _people(db, 2)
    order_id = db.create_secret_order(
        state, lead, "密查仓胥", "暗访通州仓", ["稽核"], deadline_months=3,
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": lead, "tier": "主办", "role": "密访",
    }], state=state)
    dossier_before = db.get_decree_dossier(dossier_id)
    # Grant authority to worker on this secret scope so #613 projection can hit
    # once worker is on the roster (actors = executor ∪ 主办/协办).
    auth_id = _grant(
        db, state, content, worker, "专差督办",
        f"secret_order:{order_id}", dossier_before,
    )

    result = issue_engine.apply_score_extraction(db, state, {
        "secret_dossier_participants": [{
            "dossier_id": dossier_id,
            "character_id": worker,
            "tier": "协办",
            "role": "随员",
            "delegator_id": lead,
        }],
    }, secret_dossier_ids_at_input={dossier_id})
    assert result["secret_dossier_participants"][0].get("rejected") is not True

    dossier = db.get_decree_dossier(dossier_id)
    # #565: roster is the liability source; 主办 lead is primary.
    parties = project_execution_liability_parties(dossier["participant_roster"])
    assert any(p.get("character_id") == lead for p in parties)
    # 协办 worker is on durable roster (565 read seam).
    assert any(
        row.get("character_id") == worker and row.get("tier") == "协办"
        for row in dossier["participant_roster"]
    )
    # #613 held_authorities: character executor ∪ roster 主办/协办
    side = execution_side_read_fields(db, state, dossier)
    held_holders = {item["holder_id"] for item in side["held_authorities"]}
    assert worker in held_holders
    assert str(auth_id) in side["authorization_ids"]


def test_s2_public_dossier_participants_still_rejects_secret_id(game):
    """③ 公共 dossier_participants 对密令 id 仍拒（571:389 不得放松）。"""
    import ming_sim.issues as issue_engine

    db, state, _content = game
    lead, worker = _people(db, 2)
    order_id = db.create_secret_order(
        state, lead, "密查仓胥", "暗访通州仓", ["稽核"], deadline_months=3,
    )
    secret_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    public_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar-1252",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_participants": [{
            "dossier_id": secret_id, "character_id": worker,
            "tier": "协办", "delegator_id": lead,
        }],
    }, dossier_ids_at_input={public_id})  # frozen public set — secret not in it
    assert result["dossier_participants"][0]["rejected"] is True
    assert len(db.get_decree_dossier(secret_id)["participant_roster"]) == 0


def test_s2_private_field_rejects_non_batch_and_public_ids(game):
    """④ 私字段对非本批密令 id 及公共案卷 id 拒。"""
    import ming_sim.issues as issue_engine

    db, state, _content = game
    lead, worker = _people(db, 2)
    _o1, batch_id = _secret(db, state, title="本批密令")[1:]
    # second secret not in auth set
    _lead2, _o2, other_secret = _secret(db, state, title="他批密令", body="另案")
    # seed lead on both so append shape is valid if auth were open
    for did in (batch_id, other_secret):
        d = db.get_decree_dossier(did)
        minister = str(d["executor_id"])
        db.append_decree_dossier_participants(did, [{
            "character_id": minister, "tier": "主办", "role": "承办",
        }], state=state)
    public_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="pub-1252",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    batch_lead = str(db.get_decree_dossier(batch_id)["executor_id"])
    other_lead = str(db.get_decree_dossier(other_secret)["executor_id"])
    result = issue_engine.apply_score_extraction(db, state, {
        "secret_dossier_participants": [
            {
                "dossier_id": other_secret, "character_id": worker,
                "tier": "协办", "delegator_id": other_lead,
            },
            {
                "dossier_id": public_id, "character_id": worker,
                "tier": "协办", "delegator_id": lead,
            },
            {
                "dossier_id": batch_id, "character_id": worker,
                "tier": "协办", "delegator_id": batch_lead,
            },
        ],
    }, secret_dossier_ids_at_input={batch_id})
    rows = result["secret_dossier_participants"]
    assert rows[0]["rejected"] is True
    assert rows[1]["rejected"] is True
    assert rows[2].get("rejected") is not True
    assert rows[2]["character_id"] == worker


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


def test_s2_driver_persists_secret_orders_and_freezes_secret_authority(game, monkeypatch):
    """driver 同口径 DB 查询并 persist secret_orders，替掉 secret_orders=[]。"""
    import driver

    db, state, content = game
    lead, worker = _people(db, 2)
    order_id = db.create_secret_order(
        state, lead, "密查仓胥", "暗访通州仓", ["稽核"], deadline_months=3,
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": lead, "tier": "主办", "role": "密访",
    }], state=state)

    monkeypatch.setattr(
        driver, "settle_with_delta",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash after ready")),
    )
    with pytest.raises(RuntimeError, match="crash after ready"):
        driver.run_prepare(db, state, content)
        driver.run_settle(db, state, content, {
            "secret_dossier_participants": [{
                "dossier_id": dossier_id, "character_id": worker,
                "tier": "协办", "delegator_id": lead,
            }],
        })
    ctx = db.get_resolve_context(state.turn)
    assert isinstance(ctx["secret_orders"], dict)
    # Frozen secret_orders must carry the real order so recovery can re-derive.
    from ming_sim.settlement_payload import iter_secret_order_ids
    assert order_id in iter_secret_order_ids(ctx["secret_orders"])


# ── S3: prompt 正向特征化 + DELTA_SCHEMA ─────────────────────


def test_s3_prompt_characterizes_secret_dossier_participants():
    """personnel_secret prompt 正向声明私字段与读缝（字段名最弱存在性）。"""
    from pathlib import Path

    prompt = Path("content/prompts/score_extractor_personnel_secret.md").read_text(
        encoding="utf-8",
    )
    assert "secret_dossier_participants" in prompt
    assert "secret_dossier_rosters" in prompt


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
