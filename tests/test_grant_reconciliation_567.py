"""#567 S12 按月对账与押解折损（#461 兑现）。

Seams:
- list_monthly_grant_reconciliation_targets / record_monthly_grant_reconciliations
- clamp_grant_arrival_amount（护行界严于无护行）
- list_dossier_reconciliations（被护案卷×回合键控，restore 无损）
- settle_with_delta 月度节拍写入
- dossier_executions 适配器经 merge_execution_note 合并对账说明（S10 单写）
- 不改 economy_moves / 国库二次扣
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issue_engine
from ming_sim.db import GameDB
from ming_sim.decree import settle_with_delta
from tests.dossier_test_helpers import create_test_secret_order


ORDERED = 30  # 北极星三路各三十万两量级（引擎以「两」为单位的整数面值）


def _actor(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _in_transit_grant(db, state, *, amount=ORDERED, text="拨银押解", target_id="shaanxi"):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount + 50)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text=text,
        target_kind="region",
        target_id=target_id,
        payload={
            "account": "内库",
            "amount": amount,
            "execution_surface": "in_transit",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    return dossier_id


def _escort_order(db, state, grant_ids, *, tags=None):
    """密令案卷（新）→ 护卫/稽核 指向既有拨饷案卷（旧）。"""
    order_id = create_test_secret_order(db,
        state, _actor(db), "护行饷银", "沿途按月稽核",
        tags or ["护行"], deadline_months=4,
    )
    escort_dossier = db.get_dossier_for_secret_order(order_id)
    escort_id = int(escort_dossier["id"])
    # 关联要求新→旧：密令案卷 id 须大于被护拨饷 id
    links = [
        {
            "target_dossier_id": int(gid),
            "relation_type": "护卫",
            "note": f"护送案卷{gid}",
        }
        for gid in grant_ids
    ]
    db.add_dossier_links(escort_id, links)
    return order_id, escort_id


def _settle(db, state, content, *, reconciliations=None, progress=None, narrative="本月邸报"):
    extracted = {}
    if reconciliations is not None:
        extracted["dossier_reconciliations"] = reconciliations
    if progress is not None:
        extracted["dossier_progress_reports"] = progress
    settle_with_delta(
        state, db, extracted, before_turn=state.turn, content=content, narrative=narrative,
    )


def test_escorted_arrival_clamp_strictly_beats_bare(game):
    """同批三路：有护行折损口径优于无护行（北极星多救七万两量级可复现）。"""
    from ming_sim.db import clamp_grant_arrival_amount, grant_arrival_bounds

    bare_lo, bare_hi = grant_arrival_bounds(ORDERED, escorted=False)
    escort_lo, escort_hi = grant_arrival_bounds(ORDERED, escorted=True)
    assert bare_hi < escort_lo  # 界不相交，护行严格更优
    assert bare_lo == 15 and bare_hi == 18
    assert escort_lo == 22 and escort_hi == 25
    # 中位差 = 7（三十万量级下「多救七万两」）
    bare_mid = (bare_lo + bare_hi) // 2
    escort_mid = (escort_lo + escort_hi) // 2
    assert escort_mid - bare_mid == 7

    db, state, content = game
    g_bare_a = _in_transit_grant(db, state, text="辽东补饷", target_id="liaodong")
    g_bare_b = _in_transit_grant(db, state, text="宣大补饷", target_id="xuan_da")
    g_escort = _in_transit_grant(db, state, text="陕西赈银", target_id="shaanxi")
    _order_id, escort_dossier_id = _escort_order(db, state, [g_escort])

    # 软判故意给越界值：无护行报满分、有护行报零——代码 clamp 后仍护行更优
    _settle(db, state, content, reconciliations=[
        {"dossier_id": g_bare_a, "arrived_amount": ORDERED},
        {"dossier_id": g_bare_b, "arrived_amount": ORDERED},
        {"dossier_id": g_escort, "arrived_amount": 0},
    ], progress=[{
        "dossier_id": escort_dossier_id,
        "progress_band": "在途",
        "memorial_text": "护行路按月核验",
    }])

    bare_a = db.list_dossier_reconciliations(g_bare_a)[-1]
    bare_b = db.list_dossier_reconciliations(g_bare_b)[-1]
    escorted = db.list_dossier_reconciliations(g_escort)[-1]
    assert bare_a["arrived_amount"] == bare_hi
    assert bare_b["arrived_amount"] == bare_hi
    assert escorted["arrived_amount"] == escort_lo
    assert escorted["loss_amount"] < bare_a["loss_amount"]
    assert escorted["escorted"] is True
    assert bare_a["escorted"] is False
    # clamp 纯函数与落库一致
    assert clamp_grant_arrival_amount(ORDERED, ORDERED, escorted=False) == bare_hi
    assert clamp_grant_arrival_amount(ORDERED, 0, escorted=True) == escort_lo


def test_clamp_mutation_keeps_every_value_inside_band(game):
    """折损/实抵永在 clamp 界内——越界提案被咬回。"""
    from ming_sim.db import clamp_grant_arrival_amount, grant_arrival_bounds

    for ordered in (1, 10, 30, 100, 300000):
        for escorted in (False, True):
            lo, hi = grant_arrival_bounds(ordered, escorted=escorted)
            assert 0 <= lo <= hi <= ordered
            for proposed in (-50, 0, lo - 1, lo, (lo + hi) // 2, hi, hi + 1, ordered, ordered * 2):
                got = clamp_grant_arrival_amount(ordered, proposed, escorted=escorted)
                assert lo <= got <= hi

    db, state, content = game
    gid = _in_transit_grant(db, state)
    _settle(db, state, content, reconciliations=[
        {"dossier_id": gid, "arrived_amount": -100},
    ])
    row = db.list_dossier_reconciliations(gid)[-1]
    lo, hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert lo <= row["arrived_amount"] <= hi
    assert row["loss_amount"] == ORDERED - row["arrived_amount"]
    assert row["loss_amount"] >= 0


def test_per_route_storage_restore_and_escort_split(game):
    """机械差额逐路落被护侧；有护行另走 #566 进展，无护行不产密奏。"""
    db, state, content = game
    bare = _in_transit_grant(db, state, text="无护行路", target_id="liaodong")
    escorted_grant = _in_transit_grant(db, state, text="有护行路", target_id="shaanxi")
    order_id, escort_dossier_id = _escort_order(db, state, [escorted_grant])

    turn = state.turn
    _settle(db, state, content, reconciliations=[
        {"dossier_id": bare, "arrived_amount": 16},
        {"dossier_id": escorted_grant, "arrived_amount": 24},
    ], progress=[{
        "dossier_id": escort_dossier_id,
        "progress_band": "在途核验",
        "memorial_text": "护行路已核关防，实银可期",
    }])

    bare_rows = db.list_dossier_reconciliations(bare)
    escort_rows = db.list_dossier_reconciliations(escorted_grant)
    assert len(bare_rows) == 1 and bare_rows[0]["turn"] == turn
    assert len(escort_rows) == 1 and escort_rows[0]["turn"] == turn
    assert bare_rows[0]["escorted"] is False
    assert escort_rows[0]["escorted"] is True
    assert escort_rows[0]["escort_source_dossier_id"] == escort_dossier_id

    # 无护行：不对拨饷案卷写进展；有护行：进展挂密令案卷（#566 容器）
    assert db.list_dossier_progress(bare) == []
    assert db.list_dossier_progress(escorted_grant) == []
    progress = db.list_dossier_progress(escort_dossier_id)
    assert len(progress) == 1
    assert "护行路已核关防" in progress[0]["memorial_text"]

    # restore 逐路无损
    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    assert reopened.list_dossier_reconciliations(bare) == bare_rows
    assert reopened.list_dossier_reconciliations(escorted_grant) == escort_rows
    assert reopened.list_dossier_progress(escort_dossier_id) == progress
    stored = reopened.conn.execute(
        "SELECT dossier_progress_json FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    assert json.loads(stored["dossier_progress_json"]) == progress
    reopened.close()


def test_close_merges_recon_note_without_second_treasury_debit(game):
    """S10 结案同源读对账并 merge_execution_note；不二次扣库、不改原流水。"""
    db, state, content = game
    before_inner = int(state.metrics["内库"])
    gid = _in_transit_grant(db, state, amount=ORDERED)
    after_grant_inner = int(state.metrics["内库"])
    assert after_grant_inner == before_inner - ORDERED
    moves_before = db.list_economy_moves_for_dossier(gid)

    _settle(db, state, content, reconciliations=[
        {"dossier_id": gid, "arrived_amount": 16},
    ])
    assert int(state.metrics["内库"]) == after_grant_inner
    assert db.list_economy_moves_for_dossier(gid) == moves_before

    result = issue_engine.apply_score_extraction(
        db, state,
        {"dossier_executions": [{
            "dossier_id": gid,
            "outcome": "fulfilled",
            "note": "赈银押解到达",
        }]},
        content=content,
    )
    assert result["dossier_executions"] == [{"dossier_id": gid, "outcome": "fulfilled"}]
    closed = db.get_decree_dossier(gid)
    assert closed["status"] == "closed"
    note = closed["execution_note"]
    assert "赈银押解到达" in note
    assert "应解30两" in note
    assert "实抵16两" in note
    # 仍无二次扣库
    assert int(state.metrics["内库"]) == after_grant_inner
    assert db.list_economy_moves_for_dossier(gid) == moves_before


def test_missing_soft_judge_uses_band_midpoint(game):
    """无软判提案时仍逐路落机械中位（无护行也可供 S10 读）。"""
    from ming_sim.db import grant_arrival_bounds

    db, state, content = game
    bare = _in_transit_grant(db, state)
    _settle(db, state, content, reconciliations=[])
    row = db.list_dossier_reconciliations(bare)[-1]
    lo, hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert row["arrived_amount"] == (lo + hi) // 2


def test_underfunded_closed_grants_excluded_from_monthly_targets(game):
    """成案当回合不足额 failed+close 者不进月度对账扫描面。"""
    db, state, _content = game
    state.metrics["内库"] = 0
    db.conn.execute("UPDATE metrics SET value=0 WHERE key='内库'")
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="内帑无银",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "内库", "amount": 10,
            "execution_surface": "in_transit",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    targets = db.list_monthly_grant_reconciliation_targets()
    assert dossier_id not in {int(t["dossier_id"]) for t in targets}


def test_issues_context_exposes_recon_for_soft_discount(game):
    """赈济/拨付 issue 软判可读对账数据（读账演化缝）。"""
    from ming_sim.simulation import build_extractor_shared_context

    db, state, content = game
    gid = _in_transit_grant(db, state)
    _settle(db, state, content, reconciliations=[
        {"dossier_id": gid, "arrived_amount": 16},
    ])
    ctx = build_extractor_shared_context(
        db, state, "", "", module="issues"
    )
    assert "grant_reconciliations" in ctx
    hit = next(r for r in ctx["grant_reconciliations"] if r["dossier_id"] == gid)
    assert hit["arrived_amount"] == 16
    assert hit["ordered_amount"] == ORDERED
    assert hit["loss_amount"] == ORDERED - 16


@pytest.mark.parametrize(
    "bad",
    [
        # DELTA_SCHEMA:253 五 raise 面
        "not-a-list",
        lambda gid: [{"dossier_id": 999999, "arrived_amount": 16}],
        lambda gid: [
            {"dossier_id": gid, "arrived_amount": 16},
            {"dossier_id": gid, "arrived_amount": 17},
        ],
        lambda gid: [{"dossier_id": gid}],
        lambda gid: [{"dossier_id": gid, "note": "无量"}],
        # 量字段值非法：arrived / loss 同闸同拒
        lambda gid: [{"dossier_id": gid, "arrived_amount": None}],
        lambda gid: [{"dossier_id": gid, "arrived_amount": True}],
        lambda gid: [{"dossier_id": gid, "arrived_amount": 1.5}],
        lambda gid: [{"dossier_id": gid, "arrived_amount": "十六"}],
        lambda gid: [{"dossier_id": gid, "loss_amount": None}],
        lambda gid: [{"dossier_id": gid, "loss_amount": True}],
        lambda gid: [{"dossier_id": gid, "loss_amount": 2.5}],
        lambda gid: [{"dossier_id": gid, "loss_amount": "折半"}],
        lambda gid: ["not-a-dict"],
        lambda gid: [{"dossier_id": True, "arrived_amount": 16}],
        lambda gid: [{"dossier_id": 0, "arrived_amount": 16}],
    ],
    ids=[
        "non_list",
        "unknown_or_not_in_transit",
        "duplicate",
        "missing_amount",
        "missing_amount_note_only",
        "arrived_null",
        "arrived_bool",
        "arrived_float",
        "arrived_non_numeric_str",
        "loss_null",
        "loss_bool",
        "loss_float",
        "loss_non_numeric_str",
        "item_not_dict",
        "dossier_id_bool",
        "dossier_id_zero",
    ],
)
def test_recon_proposals_fail_loud_symmetric_quantity_gate(game, bad):
    """对账提案 fail-loud：五 raise 面 + arrived/loss 量字段同口径拒。"""
    db, state, _content = game
    gid = _in_transit_grant(db, state)
    generated = bad if not callable(bad) else bad(gid)
    with pytest.raises(ValueError):
        db.record_monthly_grant_reconciliations(state.turn, generated)
    assert db.list_dossier_reconciliations(gid) == []
