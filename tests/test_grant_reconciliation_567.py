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


def test_recon_proposals_non_list_still_fail_loud(game):
    """整段非 list 不可拆项 → 仍 fail-loud（0015-D7 前提是可拆 section）。"""
    db, state, _content = game
    gid = _in_transit_grant(db, state)
    with pytest.raises(ValueError, match="对账提案须为列表"):
        db.record_monthly_grant_reconciliations(state.turn, "not-a-list")
    assert db.list_dossier_reconciliations(gid) == []


@pytest.mark.parametrize(
    "bad, category",
    [
        (lambda gid: [{"dossier_id": 999999, "arrived_amount": 16}], "missing_ref"),
        (lambda gid: [{"dossier_id": gid}], "missing_field"),
        (lambda gid: [{"dossier_id": gid, "note": "无量"}], "missing_field"),
        (lambda gid: [{"dossier_id": gid, "arrived_amount": None}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "arrived_amount": True}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "arrived_amount": 1.5}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "arrived_amount": "十六"}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "loss_amount": None}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "loss_amount": True}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "loss_amount": 2.5}], "invalid_enum"),
        (lambda gid: [{"dossier_id": gid, "loss_amount": "折半"}], "invalid_enum"),
        (lambda gid: ["not-a-dict"], "invalid_shape"),
        (lambda gid: [{"dossier_id": True, "arrived_amount": 16}], "invalid_enum"),
        (lambda gid: [{"dossier_id": 0, "arrived_amount": 16}], "invalid_enum"),
    ],
    ids=[
        "unknown_or_not_in_transit",
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
def test_recon_bad_item_rejected_target_gets_midpoint(game, bad, category):
    """#1745：坏提案逐项拒收；在途目标仍落机械中位（坏提案不进 supplied）。"""
    import json

    from ming_sim.applier import Provenance, RejectionCollector
    from ming_sim.db import grant_arrival_bounds

    db, state, _content = game
    gid = _in_transit_grant(db, state)
    generated = bad(gid)
    collector = RejectionCollector()
    reports = db.record_monthly_grant_reconciliations(
        state.turn, generated,
        rejection_collector=collector, source=Provenance.player_decree,
    )
    collector.flush_to_db(db)
    assert len(reports) == 1 and reports[0]["dossier_id"] == gid
    lo, hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert reports[0]["arrived_amount"] == (lo + hi) // 2
    # 每个坏项恰一条拒收（本参数化每案 generated 恰 1 项）
    assert len(generated) == 1
    rej = list(db.conn.execute(
        "SELECT section, category, source, reason, item_json "
        "FROM rejection_reports ORDER BY id"
    ).fetchall())
    assert len(rej) == 1
    assert rej[0]["section"] == "dossier_reconciliations"
    assert rej[0]["category"] == category
    assert rej[0]["source"] == Provenance.player_decree.value
    assert str(rej[0]["reason"] or "").strip()  # 非空；不钉措辞
    item = json.loads(rej[0]["item_json"])
    raw = generated[0]
    if isinstance(raw, dict):
        assert item.get("dossier_id", raw.get("dossier_id")) == raw.get("dossier_id")
    else:
        assert item == {"raw_value": raw}


def test_recon_both_amount_fields_rejected_no_guess(game):
    """#1745：arrived_amount 与 loss_amount 同在 → invalid_enum 拒收，不静默优先其一。"""
    import json

    from ming_sim.applier import Provenance
    from ming_sim.db import grant_arrival_bounds

    db, state, _content = game
    gid = _in_transit_grant(db, state)
    both = {
        "dossier_id": gid,
        "arrived_amount": 16,
        "loss_amount": 5,
    }
    reports = db.record_monthly_grant_reconciliations(
        state.turn, [both], source=Provenance.player_decree,
    )
    # 坏项不进 supplied → 目标仍落中位（非 16、非 ordered-5）
    assert len(reports) == 1 and reports[0]["dossier_id"] == gid
    lo, hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert reports[0]["arrived_amount"] == (lo + hi) // 2
    rej = list(db.conn.execute(
        "SELECT category, item_json, reason FROM rejection_reports "
        "WHERE section='dossier_reconciliations'"
    ).fetchall())
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert str(rej[0]["reason"] or "").strip()
    item = json.loads(rej[0]["item_json"])
    assert "arrived_amount" in item and "loss_amount" in item
    assert item["dossier_id"] == gid


def test_recon_duplicate_keeps_first_rejects_second(game):
    """#1745：重复案卷——首份落账，次份 invalid_enum 拒收。"""
    from ming_sim.applier import Provenance, RejectionCollector

    db, state, _content = game
    gid = _in_transit_grant(db, state)
    collector = RejectionCollector()
    reports = db.record_monthly_grant_reconciliations(
        state.turn,
        [
            {"dossier_id": gid, "arrived_amount": 16},
            {"dossier_id": gid, "arrived_amount": 17},
        ],
        rejection_collector=collector, source=Provenance.system_simulation,
    )
    collector.flush_to_db(db)
    assert len(reports) == 1
    assert reports[0]["arrived_amount"] == 16
    rej = list(db.conn.execute(
        "SELECT category, reason, source FROM rejection_reports"
    ).fetchall())
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert str(rej[0]["reason"] or "").strip()
    assert rej[0]["source"] == Provenance.system_simulation.value


def test_1745_two_bad_one_good_exact_rejection_cardinality(game):
    """#1745：两坏一好——好项落账，坏项各恰一条 missing_ref，不多不少。"""
    import json

    from ming_sim.applier import Provenance

    db, state, _content = game
    good = _in_transit_grant(db, state)
    bad_a = {"dossier_id": 88881, "arrived_amount": 1}
    bad_b = {"dossier_id": 88882, "arrived_amount": 2}
    # 直调无 collector → 自有 flush，拒收仍 durable（失败诚实）
    reports = db.record_monthly_grant_reconciliations(
        state.turn,
        [bad_a, {"dossier_id": good, "arrived_amount": 16}, bad_b],
        source=Provenance.player_decree,
    )
    assert len(reports) == 1
    assert reports[0]["dossier_id"] == good
    assert reports[0]["arrived_amount"] == 16
    rej = list(db.conn.execute(
        "SELECT category, source, reason, item_json FROM rejection_reports "
        "WHERE section='dossier_reconciliations' ORDER BY id"
    ).fetchall())
    assert len(rej) == 2
    assert {r["category"] for r in rej} == {"missing_ref"}
    assert all(r["source"] == Provenance.player_decree.value for r in rej)
    assert all(str(r["reason"] or "").strip() for r in rej)
    got_ids = {json.loads(r["item_json"])["dossier_id"] for r in rej}
    assert got_ids == {88881, 88882}


def test_1745_empty_targets_two_bad_no_recon_rows(game):
    """#1745：无目标 + 两坏项 → 恰两条 missing_ref，零 recon 行。"""
    import json

    from ming_sim.applier import Provenance

    db, state, _content = game
    assert db.list_monthly_grant_reconciliation_targets() == []
    reports = db.record_monthly_grant_reconciliations(
        state.turn,
        [
            {"dossier_id": 7001, "arrived_amount": 3},
            {"dossier_id": 7002, "loss_amount": 4},
        ],
        source=Provenance.player_decree,
    )
    assert reports == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossier_reconciliations"
    ).fetchone()["n"] == 0
    rej = list(db.conn.execute(
        "SELECT category, item_json FROM rejection_reports "
        "WHERE section='dossier_reconciliations' ORDER BY id"
    ).fetchall())
    assert len(rej) == 2
    assert all(r["category"] == "missing_ref" for r in rej)
    assert {json.loads(r["item_json"])["dossier_id"] for r in rej} == {7001, 7002}


def test_1745_empty_targets_bad_recon_settle_advances(game):
    """#1745 A1：无在途拨帑 + dossier_reconciliations → 逐项拒收，settle 推进，不 abort。

    真回路：settle_with_delta 注入含坏引用的 delta；账本无在途目标。
    验收：月份推进、拒收四字段落库、不落假 recon 行、不抛 SettlementAbort。
    """
    import json

    from ming_sim.applier import Provenance
    from ming_sim.exceptions import SettlementAbort
    from ming_sim.models import TurnPhase

    db, state, content = game
    turn_before = int(state.turn)
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    db.conn.commit()
    assert db.list_monthly_grant_reconciliation_targets() == []

    bad_item = {"dossier_id": 99999, "arrived_amount": 10, "note": "内帑济辽对账"}
    try:
        settle_with_delta(
            state, db,
            {"dossier_reconciliations": [bad_item]},
            before_turn=turn_before,
            content=content,
            narrative="十一月邸报",
            source=Provenance.player_decree,
        )
    except SettlementAbort:
        pytest.fail("无目标对账提案不得整月 SettlementAbort")

    assert int(state.turn) == turn_before + 1
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossier_reconciliations"
    ).fetchone()["n"] == 0
    rows = list(db.conn.execute(
        "SELECT section, reason, category, source, item_json "
        "FROM rejection_reports WHERE section='dossier_reconciliations'"
    ).fetchall())
    assert len(rows) == 1
    assert rows[0]["category"] == "missing_ref"
    assert rows[0]["source"] == Provenance.player_decree.value
    assert str(rows[0]["reason"] or "").strip()
    item = json.loads(rows[0]["item_json"])
    assert item["dossier_id"] == 99999
    assert item["arrived_amount"] == 10


def test_1745_mixed_good_and_bad_recon_same_atomic(game):
    """#1745 B1：好项落库 + 坏项拒收同 atomic；月份推进。"""
    import json

    from ming_sim.applier import Provenance
    from ming_sim.exceptions import SettlementAbort
    from ming_sim.models import TurnPhase

    db, state, content = game
    good = _in_transit_grant(db, state, text="陕西赈银", target_id="shaanxi")
    turn_before = int(state.turn)
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    db.conn.commit()

    try:
        settle_with_delta(
            state, db,
            {"dossier_reconciliations": [
                {"dossier_id": good, "arrived_amount": 16},
                {"dossier_id": 88888, "arrived_amount": 5},
            ]},
            before_turn=turn_before,
            content=content,
            narrative="mixed",
            source=Provenance.player_decree,
        )
    except SettlementAbort:
        pytest.fail("混合好/坏对账不得整月 abort")

    assert int(state.turn) == turn_before + 1
    row = db.list_dossier_reconciliations(good)[-1]
    assert row["arrived_amount"] == 16
    rej = list(db.conn.execute(
        "SELECT category, item_json, reason FROM rejection_reports "
        "WHERE section='dossier_reconciliations'"
    ).fetchall())
    assert len(rej) == 1
    assert rej[0]["category"] == "missing_ref"
    assert str(rej[0]["reason"] or "").strip()
    assert json.loads(rej[0]["item_json"])["dossier_id"] == 88888


def test_1745_closed_grant_recon_is_missing_ref_not_new_row(game):
    """#1745 B2 合流 A1：已结清目标的提案 → missing_ref，不得新写对账行。"""
    import json

    from ming_sim.applier import Provenance

    db, state, _content = game
    gid = _in_transit_grant(db, state)
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed', execution_outcome='fulfilled' "
        "WHERE id=?",
        (gid,),
    )
    db.conn.commit()
    assert db.list_monthly_grant_reconciliation_targets() == []
    # 无 collector：自有 flush，拒收 durable
    reports = db.record_monthly_grant_reconciliations(
        state.turn,
        [{"dossier_id": gid, "arrived_amount": 16}],
        source=Provenance.player_decree,
    )
    assert reports == []
    assert db.list_dossier_reconciliations(gid) == []
    rej = list(db.conn.execute(
        "SELECT category, item_json, reason FROM rejection_reports"
    ).fetchall())
    assert len(rej) == 1
    assert rej[0]["category"] == "missing_ref"
    assert str(rej[0]["reason"] or "").strip()
    assert json.loads(rej[0]["item_json"])["dossier_id"] == gid
