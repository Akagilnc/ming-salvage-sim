"""#1504 B 包：密令机械实进度 + 到期缺口对账 + 拆 secret_order_closes 真源。

Seams:
- compute_willingness_floor / clamp_fidelity_to_floor（纯函数 golden）
- dossier_actual_progress 实况容器（origin 纪律；≠ dossier_progress_json）
- apply_monthly_covert_actual_progress + settle_due_secret_orders（settle 同 atomic）
- 正反例：已交付→done、缺口→failed；表报背离不翻实账
- secret_order_closes 不再落库结案
- auto_submit 不再翻 pending_review；到期不写玩家模板
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.covert_progress import (
    FACT_LANES_KEY,
    FIDELITY_STATES,
    INVESTIGATION_PROVENANCE_KEY,
    CovertContractError,
    build_covert_task_contract,
    build_secret_covert_effect_briefs,
    build_minister_snapshot,
    clamp_fidelity_to_floor,
    compute_willingness_floor,
    decide_secret_order_settlement,
    monthly_actual_units,
    progress_units_for_state,
    read_covert_task_contract,
    require_covert_task_contract,
    seed_guilt_counts_as_debt,
    target_progress_units,
    apply_monthly_covert_actual_progress,
    investigation_lane_actual_units,
    read_substantiated_legal_reason_code,
    settle_due_secret_orders,
)
from ming_sim.person_archive_contract import PERSON_LEGAL_REASON_CODES
from ming_sim.decree import settle_with_delta
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase
from ming_sim.simulation import (
    build_extractor_shared_context,
    _sanitize_module_output,
)


def _task(*, kind, axes, unit, target, direction=1, investigation_target="", effect_sign=None):
    if investigation_target:
        sign = 1 if effect_sign is None else int(effect_sign)
        return {
            "kind": kind,
            "axes": list(axes),
            "direction": int(direction),
            "investigation_target": investigation_target,
            "delivery": {
                "target_units": float(target),
                "effect_sign": sign,
                "investigation_target": investigation_target,
            },
        }
    identity = {
        "万两": {"purpose": "其它", "category": "密令差务", "account": "内库", "effect_sign": -1},
        "人犯": {"person_action": "处置", "effect_sign": 1},
        "万亩": {"region": "henan", "field": "registered_land", "target": "421", "effect_sign": 1},
    }[unit]
    if effect_sign is not None:
        identity = {**identity, "effect_sign": int(effect_sign)}
    return {
        "kind": kind,
        "axes": list(axes),
        "direction": int(direction),
        "delivery": {"unit": unit, "target_units": float(target), **identity},
    }


def _issue(db, state, name, title, content, *, months, target, kind="查案",
           axes=None, unit="万两", tags=None, investigation_target=""):
    return db.create_secret_order(
        state, name, title, content, tags if tags is not None else [],
        deadline_months=months,
        covert_task=_task(
            kind=kind, axes=axes or ["实务事功"], unit=unit, target=target,
            investigation_target=investigation_target,
        ),
    )


def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters "
        "WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩','未仕') "
        "ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return row["name"]


def _set_axes(db, name, *, loyalty, identity, faction=None, seed_guilt=""):
    if faction is None:
        faction = db.conn.execute(
            "SELECT faction FROM characters WHERE name=?", (name,)
        ).fetchone()["faction"]
    db.conn.execute(
        "UPDATE characters SET loyalty=?, identity=?, seed_guilt=? WHERE name=?",
        (int(loyalty), int(identity), seed_guilt, name),
    )
    if faction:
        db.conn.execute(
            "UPDATE factions SET satisfaction=? WHERE name=?",
            (60, faction),
        )
    db.conn.commit()


def _report(dossier_id, text="本月密奏已达"):
    return {
        "dossier_id": int(dossier_id),
        "progress_band": "在办",
        "memorial_text": text,
    }


def _originate_work(db, state, content, dossier_id, *, delta=-1):
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "内库",
                "delta": int(delta),
                "category": "密令差务",
                "reason": "差务实办开支",
                "origin_ref": f"dossier:{int(dossier_id)}",
            }],
        },
        content=content,
    )


def _delta_work(oid, dossier_id, *, fidelity="忠实", memorial="本月密奏已达", eco=-1, report=True):
    extracted = {
        "economy_moves": [{
            "account": "内库",
            "delta": int(eco),
            "category": "密令差务",
            "reason": "差务实办开支",
            "origin_ref": f"dossier:{int(dossier_id)}",
        }],
        "covert_exec_selections": [{"order_id": int(oid), "fidelity": fidelity}],
    }
    if report:
        extracted["dossier_progress_reports"] = [_report(dossier_id, memorial)]
    return extracted


def _catch_names(db, exclude, n=3):
    rows = db.conn.execute(
        "SELECT name FROM characters "
        "WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩','未仕') AND name!=? "
        "ORDER BY name LIMIT ?",
        (exclude, int(n)),
    ).fetchall()
    names = [str(r["name"]) for r in rows]
    assert len(names) >= int(n)
    return names


def _originate_catches(db, state, content, dossier_id, names):
    apply_score_extraction(
        db, state,
        {
            "人物变更": [
                {
                    "name": name,
                    "动作": "处置",
                    "status": "imprisoned",
                    "reason": "密令缉获",
                    "origin_ref": f"dossier:{int(dossier_id)}",
                }
                for name in names
            ],
        },
        content=content,
    )


# ── 纯函数 golden ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("loyalty", "identity", "satisfaction", "guilt", "expected"),
    [
        (90, 40, 80, "", "忠实"),
        (55, 50, 55, "", "打折"),
        (40, 50, 40, "", "阳奉阴违"),
        (10, 90, 10, "血债", "反噬"),
        # 真实 seed：{"crime":"无"} 清白，不得当血债
        (90, 40, 80, json.dumps({"crime": "无", "severity": "无"}, ensure_ascii=False), "忠实"),
        (90, 40, 80, {"crime": "无", "severity": "无"}, "忠实"),
        # 合法零值：loyalty=0 / identity=0 不得被 or-default 吞掉
        (0, 0, 80, "", "阳奉阴违"),
    ],
)
def test_willingness_floor_golden(loyalty, identity, satisfaction, guilt, expected):
    assert compute_willingness_floor(
        loyalty=loyalty,
        identity=identity,
        satisfaction=satisfaction,
        seed_guilt=guilt,
    ) == expected


def test_seed_guilt_structured_clean_vs_debt():
    assert not seed_guilt_counts_as_debt("")
    assert not seed_guilt_counts_as_debt(None)
    assert not seed_guilt_counts_as_debt({"crime": "无", "severity": "无"})
    assert not seed_guilt_counts_as_debt('{"crime": "无", "severity": "无"}')
    assert seed_guilt_counts_as_debt("血债")
    assert seed_guilt_counts_as_debt({"crime": "交结近侍", "severity": "中"})


def test_build_minister_snapshot_preserves_zero_axes_and_clean_seed(game):
    db, state, _ = game
    name = _minister(db)
    clean = json.dumps({"crime": "无", "severity": "无"}, ensure_ascii=False)
    db.conn.execute(
        "UPDATE characters SET loyalty=0, identity=0, seed_guilt=? WHERE name=?",
        (clean, name),
    )
    db.conn.commit()
    snap = build_minister_snapshot(db, name)
    assert snap["loyalty"] == 0
    assert snap["identity"] == 0
    assert not seed_guilt_counts_as_debt(snap["seed_guilt"])
    # 清白 seed + 零轴：底档不得被虚假血债/or50 抬到忠实
    floor = compute_willingness_floor(
        loyalty=int(snap["loyalty"]),
        identity=int(snap["identity"]),
        satisfaction=int(snap["satisfaction"]),
        seed_guilt=snap["seed_guilt"],
    )
    assert floor != "忠实"


def test_clamp_only_worsens_never_lightens():
    assert clamp_fidelity_to_floor("打折", "忠实") == "打折"
    assert clamp_fidelity_to_floor("打折", "阳奉阴违") == "阳奉阴违"
    assert clamp_fidelity_to_floor("忠实", None) == "忠实"
    assert clamp_fidelity_to_floor("忠实", "bogus") == "忠实"
    # 全序可加重
    for i, floor in enumerate(FIDELITY_STATES):
        for j, sel in enumerate(FIDELITY_STATES):
            out = clamp_fidelity_to_floor(floor, sel)
            assert FIDELITY_STATES.index(out) >= i
            if j >= i:
                assert out == sel


def test_decide_settlement_delivery_gap_bidirectional():
    done = decide_secret_order_settlement({
        "actual_units": 3.0, "target_units": 3.0, "criterion_text": "密查甲",
    })
    assert done["status"] == "done" and done["outcome"] == "fulfilled" and done["delivered"]

    failed = decide_secret_order_settlement({
        "actual_units": 0.5, "target_units": 3.0, "criterion_text": "密查甲",
        "has_reports": True,
    })
    assert failed["status"] == "failed" and not failed["delivered"]
    assert "表报" in failed["note"]
    # 表报不改变 delivered 判定
    bare = decide_secret_order_settlement({
        "actual_units": 0.5, "target_units": 3.0, "has_reports": False,
    })
    assert bare["status"] == "failed"


def test_target_units_min_one_when_due():
    assert target_progress_units(deadline_span=3, due_turn=10) == 3.0
    assert target_progress_units(deadline_span=0, due_turn=5) == 1.0
    assert target_progress_units(deadline_span=6, due_turn=0) == 0.0


def test_task_specific_contract_from_explicit_fields_not_tags():
    audit = build_covert_task_contract(
        deadline_span=3, due_turn=10,
        kind="补发饷银", axes=["既得利益"], direction=1,
        delivery_unit="万两", delivery_target_units=3, effect_sign=-1,
        purpose="其它", category="密令差务", account="内库",
    )
    catch = build_covert_task_contract(
        deadline_span=3, due_turn=10,
        kind="缉获人犯", axes=["实务事功"], direction=1,
        delivery_unit="人犯", delivery_target_units=3, effect_sign=1, person_action="处置",
    )
    assert audit["kind"] == "补发饷银" and audit["axes"] == ["既得利益"]
    assert audit["delivery"]["unit"] == "万两"
    assert audit["delivery"]["target_units"] == 3.0
    assert catch["kind"] == "缉获人犯" and catch["delivery"]["unit"] == "人犯"
    assert catch["delivery"]["target_units"] == 3.0
    with pytest.raises(CovertContractError):
        build_covert_task_contract(
            deadline_span=3, due_turn=10, tags=["辽饷", "兵部", "密查", "稽核"],
        )


@pytest.mark.parametrize(
    ("unit", "identity", "sign"),
    [
        ("万两", {"category": "密令差务", "account": "内库"}, -1),
        ("万两", {"purpose": "其它", "account": "内库"}, -1),
        ("万两", {"purpose": "其它", "category": "密令差务"}, -1),
        ("人犯", {}, 1),
        ("万亩", {"field": "registered_land", "region_target": "421"}, 1),
        ("万亩", {"region": "henan", "region_target": "421"}, 1),
        ("万亩", {"region": "henan", "field": "registered_land"}, 1),
    ],
)
def test_confirmation_rejects_incomplete_delivery_identity(unit, identity, sign):
    with pytest.raises(CovertContractError, match="identity"):
        build_covert_task_contract(
            kind="差务", axes=["实务事功"], direction=1,
            delivery_unit=unit, delivery_target_units=1, effect_sign=sign, **identity,
        )


def test_actual_units_share_originated_quantity():
    assert monthly_actual_units(fidelity="忠实", originated_quantity=5000) == 5000.0
    assert monthly_actual_units(fidelity="打折", originated_quantity=4) == 2.0
    assert monthly_actual_units(fidelity="忠实", originated_quantity=0) == 0.0
    assert monthly_actual_units(fidelity="反噬", originated_quantity=3) == 0.0


def test_confirm_persists_task_specific_contract_absent_before(game):
    db, state, _ = game
    name = _minister(db)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM secret_orders").fetchone()["n"]
    assert before == 0
    oid = _issue(
        db, state, name, "密查辽饷", "不得声张",
        months=3, target=3, kind="补发饷银", axes=["既得利益"], unit="万两",
        tags=["辽饷", "兵部", "密查"],
    )
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract is not None
    assert contract["kind"] == "补发饷银"
    assert contract["axes"] == ["既得利益"]
    assert contract["delivery"]["unit"] == "万两"
    assert contract["delivery"]["target_units"] == 3.0
    catch_id = _issue(
        db, state, name, "缉获私贩", "拿人犯",
        months=2, target=2, kind="缉获人犯", unit="人犯",
        tags=["密查"],
    )
    catch = read_covert_task_contract(db.get_dossier_for_secret_order(catch_id))
    assert catch["kind"] == "缉获人犯"
    assert catch["delivery"]["unit"] == "人犯"
    assert catch["delivery"]["target_units"] == 2.0


def test_actual_progress_container_separate_from_reported_rail(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(db, state, name, "密查国丈", "查周奎私通状", months=3, target=3)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])

    db.record_dossier_actual_progress(
        did, state.turn, units=1.0, fidelity_state="忠实", floor_state="忠实",
        note="实况一笔",
    )
    # 奏报轨另写
    db.record_dossier_progress(
        did, state.turn, "在办", "臣称已有端绪", is_terminal=False,
    )

    actual = db.list_dossier_actual_progress(did)
    reported = db.list_dossier_progress(did)
    assert len(actual) == 1
    assert actual[0]["units"] == 1.0
    assert actual[0]["origin_ref"] == f"dossier:{did}"
    assert db.sum_dossier_actual_progress_units(did) == 1.0
    # 两轨分立
    assert reported[0]["progress_band"] == "在办"
    assert not reported[0]["is_terminal"]
    assert "dossier_progress_json" not in json.dumps(actual, ensure_ascii=False)
    # list_dossier_durable_effects 仍只 economy+fiscal；实进度走并列读口
    durable = db.list_dossier_durable_effects(did)
    assert all("account" in r or "key" in r or "delta" in r for r in durable) or durable == []
    assert db.list_dossier_actual_rail(did)  # 含 actual_progress 行


def test_settle_due_reads_actual_rail_only_report_does_not_flip_verdict(game):
    """窄接缝：settle_due_secret_orders 只读 actual rail；奏报灌满不翻 verdict。

    真入口下表报背离见 test_settle_gap_failed_and_reported_divergence。
    """
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=20, identity=80)
    oid = _issue(db, state, name, "空转密查", "查无实据之案", months=1, target=1)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])
    # 只写奏报，不写实况
    db.record_dossier_progress(
        did, state.turn, "办成", "臣已查明全部", is_terminal=False,
    )
    # 推 due 到当月
    db.conn.execute(
        "UPDATE secret_orders SET due_turn=? WHERE id=?",
        (state.turn, oid),
    )
    db.conn.commit()

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] == 0.0
    closed = db.get_secret_order(oid)
    assert closed["status"] == "failed"


def test_settle_due_keeps_existing_progress_result_over_memorial(game):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=20, identity=80)
    oid = _issue(db, state, name, "空转密查", "查无实据之案", months=1, target=1)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])
    db.update_secret_order_progress(oid, "承办人已报进展时间线", year=state.year, period=state.period)
    before = str(db.get_secret_order(oid)["result"] or "")
    assert before.strip()
    db.record_dossier_progress(
        did, state.turn, "办成", "臣已查明全部", is_terminal=False,
    )
    memorial = str(db.list_dossier_progress(did)[-1]["memorial_text"] or "")
    db.conn.execute(
        "UPDATE secret_orders SET due_turn=? WHERE id=?",
        (state.turn, oid),
    )
    db.conn.commit()

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    closed = db.get_secret_order(oid)
    assert str(closed["result"] or "") == before
    assert row["result"] == before
    assert before != memorial


# ── 月度实进度 + 到期对账 ─────────────────────────────────────────────


def test_monthly_actual_then_delivered_done(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "三月密查", "限期三月查明", months=3, target=3)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    for _ in range(3):
        state.turn += 1
        db.save_state(state)
        _originate_work(db, state, content, did)
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fidelity": "忠实"}],
            commit=True,
        )

    order = db.conn.execute(
        "SELECT due_turn, deadline_span FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert state.turn == int(order["due_turn"])

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done", row
    assert row["delivered"] is True
    assert db.get_secret_order(oid)["status"] == "done"
    dossier = db.get_dossier_for_secret_order(oid)
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "fulfilled"


def test_gap_after_months_failed(game):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=15, identity=85, seed_guilt="旧案")
    oid = _issue(db, state, name, "必败密查", "无人真办", months=2, target=2)
    # 两月反噬/阳奉 → 0 实进度（跳过发令月）
    for _ in range(2):
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(db, state, selections=None, commit=True)
    due = db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"]
    assert state.turn == int(due)

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] < row["target_units"]
    assert db.get_secret_order(oid)["status"] == "failed"


def test_n_month_deadline_yields_exactly_n_ticks(game):
    """N 月期限恰 N 次实进度 tick（发令月排除）。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    n = 3
    oid = _issue(db, state, name, "恰三月", "验窗口", months=n, target=n)
    issued = int(state.turn)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    out0 = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    assert not any(r.get("order_id") == oid and not r.get("skipped") and r.get("units") is not None
                   and not r.get("rejected") for r in out0 if r.get("order_id") == oid and "units" in r)
    assert db.sum_dossier_actual_progress_units(did) == 0.0
    assert all(int(b.get("order_id") or 0) != oid for b in build_secret_covert_effect_briefs(db, turn=state.turn))

    ticks = 0
    for _ in range(n):
        state.turn += 1
        db.save_state(state)
        _originate_work(db, state, content, did)
        out = apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fidelity": "打折"}],
            commit=True,
        )
        row = next(r for r in out if r.get("order_id") == oid)
        assert row.get("units") == 0.5
        ticks += 1
    assert ticks == n
    assert len(db.list_dossier_actual_progress(did)) == n
    assert db.sum_dossier_actual_progress_units(did) == pytest.approx(0.5 * n)
    due = int(db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"])
    assert due == issued + n
    assert state.turn == due


@pytest.mark.parametrize(
    "off_status",
    ["offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"],
)
def test_offstage_minister_no_progress_no_world_effects(game, off_status):
    """扫描资格门：status 非 active 时不写进度/支出（直接写 status，避开 oust 连带关令）。"""
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "离场密令", "不应再办", months=2, target=2)
    # 离开发令月
    state.turn += 1
    db.save_state(state)
    before_neiku = int(state.metrics.get("内库", 0))
    # 直接改 status：令仍 active，专测月度扫描资格门
    db.conn.execute(
        "UPDATE characters SET status=? WHERE name=?", (off_status, name),
    )
    db.conn.commit()
    assert db.get_secret_order(oid)["status"] == "active"
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row.get("skipped") is True
    assert db.sum_dossier_actual_progress_units(did) == 0.0
    assert db.list_dossier_actual_progress(did) == []
    assert int(state.metrics.get("内库", 0)) == before_neiku


def test_missing_minister_row_no_progress(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(db, state, name, "幽灵承办", "人已不在册", months=2, target=2)
    state.turn += 1
    db.save_state(state)
    # 承办名改为不在册（缺行）；保留 FK 指向的原人物行
    db.conn.execute(
        "UPDATE secret_orders SET minister_name=? WHERE id=?",
        ("不存在的承办人_1504", oid),
    )
    db.conn.commit()
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row.get("skipped") is True


def test_mid_month_restore_preserves_actual_progress(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=85, identity=40)
    oid = _issue(db, state, name, "可恢复密查", "查案", months=4, target=4)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 跳过发令月再落笔
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    before = db.list_dossier_actual_progress(did)
    assert len(before) == 1 and before[0]["units"] == 1.0

    path = db.path
    db.close()
    db2 = type(db)(path, content)
    try:
        restored = db2.list_dossier_actual_progress(did)
        assert len(restored) == 1
        assert restored[0]["units"] == 1.0
        assert restored[0]["fidelity_state"] == "忠实"
        assert db2.sum_dossier_actual_progress_units(did) == 1.0
    finally:
        db2.close()


def test_settle_with_delta_wires_monthly_and_due(game):
    """settle_with_delta 同 atomic：当月实况 + 到期对账；closes 字段无效。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    # 单月期限：发令月不计；次月产 1.0 并对账
    oid = _issue(db, state, name, "一月密查", "限期一月", months=1, target=1)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    before = state.turn
    first = _delta_work(oid, did, memorial="查有实据")
    settle_with_delta(state, db, first, before_turn=before, content=content)
    # 发令月 settle：未到期、无实进度（发令月排除）
    order = db.get_secret_order(oid)
    assert order["status"] == "active"
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    # 次月：产 1.0 并到期 → done
    before2 = state.turn
    settle_with_delta(
        state, db,
        _delta_work(oid, did, memorial="查有实据", report=True),
        before_turn=before2,
        content=content,
    )
    order2 = db.get_secret_order(oid)
    assert order2["status"] == "done", order2
    assert db.sum_dossier_actual_progress_units(did) == 1.0


def test_secret_order_closes_field_is_ignored(game):
    db, state, content = game
    name = _minister(db)
    oid = _issue(db, state, name, "旧链密令", "不应被 closes 结", months=3, target=3)
    out = apply_score_extraction(
        db, state,
        {
            "secret_order_closes": [
                {"order_id": oid, "status": "done", "result": "LLM 伪结案"},
            ],
        },
        content=content,
    )
    assert "secret_order_closes" not in out
    assert db.get_secret_order(oid)["status"] == "active"


def test_auto_submit_due_no_longer_flips_pending_review(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(db, state, name, "到期仍在办", "到期对账前保持 active", months=1, target=1)
    due = db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"]
    state.turn = int(due)
    db.save_state(state)

    submitted = db.auto_submit_due_secret_orders(state)
    order = db.get_secret_order(oid)
    assert order["status"] == "active", order
    assert all(item.get("id") != oid or item.get("status") != "pending_review"
               for item in (submitted or [{"id": oid, "status": order["status"]}]))
    dossier = db.get_dossier_for_secret_order(oid)
    payload = json.loads(str(dossier["payload_json"]))
    assert "due_machine" not in payload


def test_judge_selection_cannot_lighten_floor(game):
    db, state, _ = game
    name = _minister(db)
    # 低忠诚 → 底档至少 阳奉/反噬
    _set_axes(db, name, loyalty=20, identity=80, seed_guilt="x")
    oid = _issue(db, state, name, "不可洗白", "底档钳制", months=2, target=2)
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],  # 试图减轻
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["fidelity"] != "忠实"
    assert progress_units_for_state(row["fidelity"]) <= progress_units_for_state(row["floor"])
    assert FIDELITY_STATES.index(row["fidelity"]) >= FIDELITY_STATES.index(row["floor"])


def test_monthly_actual_does_not_invent_generic_world_package(game):
    """月度实况不发明 loyalty/内库/unrest 套餐；交付差务无 origin 则 units=0（不锁查核机械带）。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "空转一月", "无实办", months=1, target=1)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["units"] == 0.0
    assert row.get("originated_quantity") == 0
    after_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert after_loyalty == before_loyalty
    assert int(state.metrics.get("内库", 0)) == before_neiku
    assert db.list_economy_moves_for_dossier(did) == []


def test_settle_originated_effects_drive_actual_and_restore(game):
    """真入口：extractor origin 效果驱动 actual；restore 两轨无损；月度不另改人物。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)

    oid = _issue(db, state, name, "一月实办", "限期一月查明", months=1, target=3)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    settle_with_delta(
        state, db, {"dossier_progress_reports": [_report(did, "发令月密奏")]},
        before_turn=state.turn, content=content,
    )
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    settle_with_delta(
        state, db,
        _delta_work(oid, did, memorial="实查有据", eco=-3, report=True),
        before_turn=state.turn,
        content=content,
    )

    assert db.sum_dossier_actual_progress_units(did) == 3.0
    actual_row = db.list_dossier_actual_progress(did)[0]
    assert actual_row["fidelity_state"] == "忠实"
    assert actual_row["origin_ref"] == f"dossier:{did}"
    after_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert after_loyalty == before_loyalty
    eco = db.list_economy_moves_for_dossier(did)
    assert any(int(r.get("delta") or 0) == -3 for r in eco), eco
    assert all(str(r.get("origin_ref") or "") == f"dossier:{did}" for r in eco)
    assert int(state.metrics.get("内库", 0)) == before_neiku - 3
    reported = db.list_dossier_progress(did)
    assert reported

    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        assert db2.sum_dossier_actual_progress_units(did) == 3.0
        assert int(db2.conn.execute(
            "SELECT loyalty FROM characters WHERE name=?", (name,)
        ).fetchone()["loyalty"]) == after_loyalty
        assert int(state2.metrics.get("内库", 0)) == before_neiku - 3
        eco2 = db2.list_economy_moves_for_dossier(did)
        assert any(int(r.get("delta") or 0) == -3 for r in eco2)
        assert db2.list_dossier_progress(did)
        assert not any(
            "dossier_progress_json" in json.dumps(r, ensure_ascii=False) for r in eco2
        )
    finally:
        db2.close()


def test_settle_gap_failed_and_reported_divergence(game):
    """真入口：反噬月实进度 0 + 表报灌满 → settle 到期 failed，表报不翻实账。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=10, identity=90, seed_guilt="旧案")
    oid = _issue(db, state, name, "必败一月", "无人真办", months=1, target=1)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    memorial = "臣称已全部查明"
    db.record_dossier_progress(
        did, state.turn, "办成", memorial, is_terminal=False,
    )
    settle_with_delta(
        state, db, {"dossier_progress_reports": [_report(did, memorial)]},
        before_turn=state.turn, content=content,
    )
    assert db.get_secret_order(oid)["status"] == "active"
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    settle_with_delta(
        state, db,
        _delta_work(oid, did, fidelity="反噬", memorial=memorial, eco=-1, report=True),
        before_turn=state.turn,
        content=content,
    )
    mid_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert mid_loyalty == before_loyalty
    order = db.get_secret_order(oid)
    assert order["status"] == "failed"
    dossier = db.get_dossier_for_secret_order(oid)
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    assert db.list_dossier_progress(did)


def test_zero_target_is_not_delivered():
    verdict = decide_secret_order_settlement({
        "actual_units": 0.0, "target_units": 0.0,
    })
    assert verdict["status"] == "failed"
    assert not verdict["delivered"]


def test_submit_unlimited_keeps_frozen_target(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(
        db, state, name, "无期补发饷银", "补发饷银",
        months=0, target=3, kind="补发饷银", axes=["既得利益"], unit="万两",
        tags=["辽饷", "兵部", "密查"],
    )
    contract0 = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract0["delivery"]["target_units"] == 3.0
    assert int(db.get_secret_order(oid)["due_turn"] or 0) == 0

    ok = db.submit_secret_order_for_review(oid, "臣已办结", state.year, state.period)
    assert ok is True
    live = db.get_secret_order(oid)
    assert int(live["due_turn"]) == int(state.turn)
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["target_units"] == 3.0
    assert contract["kind"] == "补发饷银"
    assert contract["delivery"]["unit"] == "万两"

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] == 0.0
    assert not row["delivered"]
    assert db.get_secret_order(oid)["status"] == "failed"


def test_rush_preserves_frozen_contract(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(
        db, state, name, "无期缉获", "拿人",
        months=0, target=3, kind="缉获人犯", unit="人犯",
    )
    db.rush_secret_order(oid, state, deadline_months=0, reason="即核")
    live = db.get_secret_order(oid)
    assert int(live["due_turn"]) == int(state.turn)
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["target_units"] == 3.0
    assert contract["kind"] == "缉获人犯"
    assert contract["delivery"]["unit"] == "人犯"


@pytest.mark.parametrize("due_action", ["submit", "rush"])
def test_unlimited_investigation_due_now_uses_one_month_quota(game, due_action):
    """新档无期限查核经提交/即核到期，按一月实况配额结案。"""
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "无期查核", "查核侵冒",
        months=0, target=4, kind="查核侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )

    if due_action == "submit":
        assert db.submit_secret_order_for_review(
            oid, "臣已办结", state.year, state.period,
        ) is True
    else:
        db.rush_secret_order(oid, state, deadline_months=0, reason="即核")

    live = db.get_secret_order(oid)
    assert int(live["due_turn"]) == int(state.turn)
    span = db.conn.execute(
        "SELECT deadline_span FROM secret_orders WHERE id=?", (oid,),
    ).fetchone()["deadline_span"]
    assert int(span) == 0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(item for item in out if item["order_id"] == oid)
    assert row["status"] == "done"
    assert row["actual_units"] == 1.0
    assert row["target_units"] == 1.0


def test_1376_candidate_confirm_freezes_explicit_typed_contract(game):
    db, state, content = game
    name = _minister(db)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建",
        minister_name=name, target_id=None,
        payload={
            "title": "核辽饷侵冒",
            "content": "按数追赃补发",
            "assignee": name,
            "tags": ["辽饷", "兵部", "密查"],
            "deadline_months": 3,
            "covert_task": _task(
                kind="补发饷银", axes=["既得利益"], unit="万两", target=5,
            ),
        },
    )
    applied = db.commit_pending_actions(state, content=content, action_ids=[pid])
    assert applied
    oid = int(db.list_secret_orders(status="active")[0]["id"])
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["kind"] == "补发饷银"
    assert contract["axes"] == ["既得利益"]
    assert contract["delivery"]["unit"] == "万两"
    assert contract["delivery"]["target_units"] == 5.0
    assert contract["kind"] != "稽核"


def test_internal_extractor_receives_origin_linked_typed_briefs_without_secret_prose(game):
    """真实 extractor 装配只证明结构化输入契约；LLM 产出不以手造结果冒充。"""
    db, state, _ = game
    name = _minister(db)
    secret_prose = "乙巳密查辽饷侵冒正文不得进公共档房"
    fiscal_id = _issue(
        db, state, name, "补发边饷", secret_prose,
        months=1, target=5, kind="补发饷银", axes=["既得利益"], unit="万两",
        tags=["辽饷"],
    )
    catch_id = _issue(
        db, state, name, "缉私枭", secret_prose,
        months=1, target=3, kind="缉获人犯", unit="人犯", tags=["密查"],
    )
    assert all(
        int(b.get("order_id") or 0) not in {fiscal_id, catch_id}
        for b in build_secret_covert_effect_briefs(db, turn=state.turn)
    )
    state.turn += 1
    db.save_state(state)

    internal_ctx = build_extractor_shared_context(db, state, "", "", module="internal")
    assert secret_prose not in str(internal_ctx)
    assert "secret_orders" not in internal_ctx
    briefs = {
        int(brief["order_id"]): brief
        for brief in internal_ctx["secret_covert_effect_briefs"]
    }
    assert briefs[fiscal_id]["origin_ref"].startswith("dossier:")
    assert briefs[fiscal_id]["delivery"]["unit"] == "万两"
    assert briefs[fiscal_id]["delivery"] == {
        "unit": "万两", "target_units": 5.0, "effect_sign": -1,
        "canonical_fields": ["economy_moves"],
        "purpose": "其它", "category": "密令差务", "account": "内库",
    }
    assert briefs[fiscal_id]["canonical_fields"] == ["economy_moves"]
    assert briefs[fiscal_id]["prior_actual_units"] == 0.0
    assert briefs[fiscal_id]["remaining_units"] == briefs[fiscal_id]["delivery"]["target_units"]
    assert catch_id not in briefs
    personnel_ctx = build_extractor_shared_context(db, state, "", "", module="personnel_secret")
    assert secret_prose not in str(personnel_ctx)
    pbriefs = {
        int(brief["order_id"]): brief
        for brief in personnel_ctx["secret_covert_effect_briefs"]
    }
    assert fiscal_id not in pbriefs
    assert pbriefs[catch_id]["canonical_fields"] == ["人物变更"]
    assert pbriefs[catch_id]["delivery"]["unit"] == "人犯"
    assert pbriefs[catch_id]["delivery"]["person_action"] == "处置"
    assert pbriefs[catch_id]["delivery"]["target_units"] == 3.0

    did = int(db.get_dossier_for_secret_order(fiscal_id)["id"])
    db.record_dossier_actual_progress(
        did, state.turn, units=5.0, fidelity_state="忠实", floor_state="忠实",
        note="满标实况",
    )
    state.turn += 1
    db.save_state(state)
    later = {
        int(brief["order_id"]): brief
        for brief in build_extractor_shared_context(
            db, state, "", "", module="internal",
        )["secret_covert_effect_briefs"]
    }
    assert later[fiscal_id]["prior_actual_units"] == later[fiscal_id]["delivery"]["target_units"]
    assert later[fiscal_id]["remaining_units"] == 0.0
    assert later[fiscal_id]["delivery"]["target_units"] == 5.0


def _confirm_investigation(
    db, state, content, monkeypatch, *, minister, target,
    months=6, player_message="查核辽饷侵冒",
):
    from ming_sim import cli_backend as cb

    canned = json.dumps({
        "标题": "查核辽饷侵冒",
        "内容": "查核辽饷侵冒",
        "承办人": minister,
        "期限月数": int(months),
        "标签": ["辽饷"],
        "差务": "查核辽饷侵冒",
        "价值轴": ["既得利益"],
        "方向": 1,
        "交付目标": 4,
        "效果符号": 1,
        "调查对象": target,
    }, ensure_ascii=False)

    def fake_json(_prompt, llm_config=None, tag=""):
        return canned, 1

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", fake_json)
    ctx = MaterializeCtx(
        session=SimpleNamespace(db=db, state=state),
        character=SimpleNamespace(name=minister, office_type="文官"),
        player_message=player_message, reply="臣领密旨",
        message_text=player_message, explicit_prefixed=False,
        has_directive=False, pend_for_minister=[], out={},
        intent={"secret_action": "新建"}, intent_kind="secret",
        llm_config=None, intent_candidates=[],
    )
    run_materialize_pipeline(ctx)
    pid = int(ctx.out["pending_action_id"])
    applied = db.commit_pending_actions(state, content=content, action_ids=[pid])
    oid = 0
    for item in applied or []:
        if item.get("kind") == "secret_order" and str(item.get("action") or "") == "新建":
            try:
                oid = int(item.get("secret_order_id") or 0)
            except (TypeError, ValueError):
                oid = 0
            break
    return {"pid": pid, "secret_order_id": oid}


def test_same_target_confirmations_merge_into_one_open_case(game, monkeypatch):
    db, state, content = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    first_applied = _confirm_investigation(
        db, state, content, monkeypatch, minister=name, target=target,
    )
    first_pid = first_applied["pid"]
    first_oid = first_applied["secret_order_id"]
    assert first_oid > 0
    while len(db.list_secret_orders(status="active")) < 20:
        n = len(db.list_secret_orders(status="active"))
        _issue(
            db, state, name, f"垫条{n}", f"垫条{n}",
            months=1, target=1, kind="补发饷银", axes=["既得利益"], unit="万两",
        )
    assert len(db.list_secret_orders(status="active")) == 20
    second_applied = _confirm_investigation(
        db, state, content, monkeypatch, minister=name, target=target,
    )
    second_pid = second_applied["pid"]
    assert second_applied["secret_order_id"] == first_oid
    assert second_applied["secret_order_id"] > 0
    active = db.list_secret_orders(status="active")
    assert len(active) == 20
    matched = []
    for order in active:
        dossier = db.get_dossier_for_secret_order(int(order["id"]))
        contract = read_covert_task_contract(dossier) or {}
        if contract.get("investigation_target") == target:
            matched.append((int(order["id"]), dossier, contract))
    assert len(matched) == 1
    oid, dossier, contract = matched[0]
    payload = json.loads(dossier["payload_json"])
    sources = payload.get(INVESTIGATION_PROVENANCE_KEY) or []
    assert any(int(row.get("pending_action_id") or 0) == second_pid for row in sources)
    assert first_pid != second_pid


def test_investigation_lane_progress_emits_reason_before_used(game):
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", ("侵冒", target))
    db.conn.commit()
    oid = _issue(
        db, state, name, "查核辽饷侵冒", "查核辽饷侵冒",
        months=6, target=2, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "打折"}], commit=True,
    )
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {row["fact_key"]: row for row in payload[FACT_LANES_KEY]}
    assert lanes[target]["used"] is False
    assert not lanes[target].get("reason_code")
    assert lanes[target]["progress"] == 0.5
    assert read_substantiated_legal_reason_code(db, target, target) == ""
    assert investigation_lane_actual_units(db, did) == 0.0

    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {row["fact_key"]: row for row in payload[FACT_LANES_KEY]}
    code = read_substantiated_legal_reason_code(db, target, target)
    assert code in PERSON_LEGAL_REASON_CODES
    assert lanes[target]["reason_code"] == code
    assert lanes[target]["used"] is True
    assert investigation_lane_actual_units(db, did) == 1.0

    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="侵冒把柄", origin=f"test:{did}", evidence=True,
    )
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {row["fact_key"]: row for row in payload[FACT_LANES_KEY]}
    runtime_code = read_substantiated_legal_reason_code(db, target, str(edge_id))
    assert runtime_code in PERSON_LEGAL_REASON_CODES
    assert lanes[str(edge_id)]["reason_code"] == runtime_code
    assert lanes[str(edge_id)]["used"] is True


def test_closed_case_blocks_same_fact_on_later_case_and_due(game):
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    other = db.conn.execute(
        "SELECT name FROM characters WHERE name NOT IN (?,?) AND status='active' LIMIT 1",
        (name, target),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", ("侵冒", target))
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", ("侵冒", other))
    db.conn.commit()
    oid = _issue(
        db, state, name, "查核辽饷侵冒", "查核辽饷侵冒",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    first = settle_due_secret_orders(db, state, commit=True)
    assert first and first[0]["status"] == "done"
    assert db.get_secret_order(oid)["status"] == "done"

    oid2 = _issue(
        db, state, name, "再查同人", "再查同人",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    oid_other = _issue(
        db, state, name, "另一对象", "另一对象",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=other,
    )
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[
            {"order_id": oid2, "fidelity": "忠实"},
            {"order_id": oid_other, "fidelity": "打折"},
        ],
        commit=True,
    )
    payload2 = json.loads(db.get_dossier_for_secret_order(oid2)["payload_json"])
    lanes2 = {row["fact_key"]: row for row in payload2[FACT_LANES_KEY]}
    assert target not in lanes2 or lanes2[target].get("used") is not True
    other_payload = json.loads(db.get_dossier_for_secret_order(oid_other)["payload_json"])
    other_lanes = {row["fact_key"]: row for row in other_payload[FACT_LANES_KEY]}
    assert other_lanes[other]["used"] is False
    assert other_lanes[other]["progress"] == 0.5

    out = settle_due_secret_orders(db, state, commit=True)
    by_id = {r["order_id"]: r for r in out}
    assert by_id[oid2]["status"] == "done"
    assert by_id[oid2]["actual_units"] == 1.0
    assert by_id[oid_other]["status"] == "failed"
    assert by_id[oid_other]["actual_units"] == 0.5


def test_fiscal_quantity_tracer_same_unit_done_and_gap(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "补发五千", "补发饷银",
        months=1, target=20, kind="补发饷银", axes=["既得利益"], unit="万两",
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    settle_with_delta(
        state, db, {"dossier_progress_reports": [_report(did, "发令")]},
        before_turn=state.turn, content=content,
    )
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "内库",
                "delta": 9,
                "category": "抄没",
                "reason": "无关同案收入不得充交付",
                "origin_ref": f"dossier:{did}",
            }],
        },
        content=content,
    )
    settle_with_delta(
        state, db,
        _delta_work(oid, did, memorial="已补发", eco=-20, report=True),
        before_turn=state.turn, content=content,
    )
    assert db.sum_dossier_actual_progress_units(did) == 20.0
    assert db.get_secret_order(oid)["status"] == "done"

    oid2 = _issue(
        db, state, name, "补发缺口", "补发饷银",
        months=1, target=20, kind="补发饷银", axes=["既得利益"], unit="万两",
    )
    did2 = int(db.get_dossier_for_secret_order(oid2)["id"])
    settle_with_delta(
        state, db, {"dossier_progress_reports": [_report(did2, "发令")]},
        before_turn=state.turn, content=content,
    )
    settle_with_delta(
        state, db,
        _delta_work(oid2, did2, memorial="只补四", eco=-4, report=True),
        before_turn=state.turn, content=content,
    )
    assert db.sum_dossier_actual_progress_units(did2) == 4.0
    assert db.get_secret_order(oid2)["status"] == "failed"


@pytest.mark.parametrize("mismatch", ["region", "field"])
def test_region_quantity_ignores_same_origin_turn_with_mismatched_identity(game, mismatch):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "清丈河南", "清丈", months=1, target=1, unit="万亩")
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    wrong = {
        "region": ("shandong", "registered_land", "520", "521"),
        "field": ("henan", "hidden_land", "420", "421"),
    }[mismatch]
    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn, year, period, region_id, field, old_value, new_value, delta, reason, origin_ref) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 7, 'test', ?)",
        (state.turn, state.year, state.period, *wrong, f"dossier:{did}"),
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 0.0


def test_catch_quantity_tracer_same_unit_done_and_mismatch_ignored(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    targets = _catch_names(db, name, n=3)
    oid = _issue(
        db, state, name, "缉获三人", "拿人犯",
        months=1, target=3, kind="缉获人犯", unit="人犯",
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    settle_with_delta(
        state, db, {"dossier_progress_reports": [_report(did, "发令")]},
        before_turn=state.turn, content=content,
    )
    _originate_work(db, state, content, did, delta=-9)
    db.conn.execute(
        "INSERT INTO person_logs "
        "(turn, year, period, person_name, action, origin_ref) VALUES (?, ?, ?, ?, ?, ?)",
        (state.turn, state.year, state.period, name, "任命", f"dossier:{did}"),
    )
    _originate_catches(db, state, content, did, targets)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 3.0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done"
    assert row["actual_units"] == 3.0
    assert row["target_units"] == 3.0


@pytest.mark.parametrize(
    "case,raw",
    [
        # #1565 N2：malformed 夹具在函数内构造（首尾空白 + 超 cap）；此处占位
        ("malformed", ""),
        # #1504：合法空对象 {} → 无 extract_failed，零契约拒暂存
        ("empty_object", "{}"),
        # #1504：合法非空 JSON 但契约为零 → 同拒暂存
        (
            "zero_contract",
            json.dumps({
                "标题": "查核辽饷侵冒",
                "内容": "查核辽饷侵冒",
                "承办人": "PLACEHOLDER",
                "期限月数": 3,
                "标签": ["辽饷"],
                "差务": "",
                "价值轴": [],
                "方向": 1,
                "交付单位": "",
                "交付目标": 0,
            }, ensure_ascii=False),
        ),
    ],
    ids=["malformed", "empty_object", "zero_contract"],
)
def test_secret_extract_stage_identity_via_materialize_entry(game, monkeypatch, case, raw):
    """密令抽取三分经既有 materialize 意图入口：malformed 暂存 / 合法{}与零契约拒暂存。

    #354 异常失败路径仍由 session_cli_fallback 既有前缀入口覆盖，不在此重复。
    不预调 _extract_secret_order；不另造平行样板。
    #1565：zero/empty 走真实批 candidates 入口；显式零键保留存在性；
    malformed 带首尾空白且超 cap，payload extract_raw 逐字相等。
    """
    from ming_sim import cli_backend as cb
    from ming_sim.action_clusters import candidates_from_classifier_payload

    db, state, _ = game
    name = _minister(db)
    if case == "malformed":
        # 真实 dispatcher 仅换模型边界；首尾空白 + 超 _TRACE_FIELD_CAP
        cap = cb._TRACE_FIELD_CAP
        core = "not-json-BEGIN-" + ("X" * (cap + 9)) + "-END"
        raw = "  \n" + core + "\n  "
        assert len(raw) > cap
        api_cfg = SimpleNamespace(channel="api")
        monkeypatch.setattr(
            cb, "_run_api_for_config",
            lambda *_a, **_k: (raw, 1),
        )
        monkeypatch.setattr(
            cb, "_run_backend_for_config",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("malformed 须走 API dispatcher，不得落 CLI backend")
            ),
        )
    elif case == "zero_contract":
        raw = raw.replace("PLACEHOLDER", name)

    # zero/empty：批入口仍 stub extractor 边界（合法 JSON 契约分流，不经 API 通道）
    # malformed：保留真实 _run_json_extractor_for_config，仅 stub _run_api_for_config
    if case in ("empty_object", "zero_contract"):
        monkeypatch.setattr(
            cb, "_run_json_extractor_for_config",
            lambda *_a, **_k: (raw, 1),
        )
        candidates = candidates_from_classifier_payload(
            [{"kind": "secret", "secret_action": "新建"}], soft=False,
        )
        ctx = MaterializeCtx(
            session=SimpleNamespace(db=db, state=state),
            character=SimpleNamespace(name=name, office_type="文官"),
            player_message="查核辽饷侵冒", reply="臣领密旨",
            message_text="查核辽饷侵冒", explicit_prefixed=False,
            has_directive=False, pend_for_minister=[], out={},
            intent=None, intent_kind="none",
            llm_config=None, intent_candidates=candidates,
        )
    else:
        ctx = MaterializeCtx(
            session=SimpleNamespace(db=db, state=state),
            character=SimpleNamespace(name=name, office_type="文官"),
            player_message="查核辽饷侵冒", reply="臣领密旨",
            message_text="查核辽饷侵冒", explicit_prefixed=False,
            has_directive=False, pend_for_minister=[], out={},
            intent={"secret_action": "新建"}, intent_kind="secret",
            llm_config=api_cfg, intent_candidates=[],
        )
    run_materialize_pipeline(ctx)

    if case == "malformed":
        pid = int(ctx.out.get("pending_action_id") or 0)
        assert pid > 0, "malformed 抽取须走 extract_failed 暂存，不得零契约拒单"
        row = db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        assert "查核辽饷侵冒" in str(payload.get("content") or "")
        assert payload.get("extract_failed") is True
        assert "无法解析" in str(payload.get("contract_error") or "")
        # 持久化 pending payload 逐字读回（含首尾空白；不截断）
        assert payload.get("extract_raw") == raw
        assert not list(ctx.out.get("pending_action_failures") or [])
        return

    # empty_object / zero_contract：合法成功抽取、契约为零 → 拒暂存；显式零键保留
    assert "pending_action_id" in ctx.out
    assert ctx.out["pending_action_id"] == 0
    assert "pending_action_failures" in ctx.out
    failures = list(ctx.out["pending_action_failures"])
    assert failures
    assert all(row.get("kind") == "secret_order" for row in failures)
    assert db.list_secret_orders() == []
    staged = db.conn.execute(
        "SELECT id FROM pending_actions WHERE kind='secret_order'",
    ).fetchall()
    assert staged == []


@pytest.mark.parametrize(
    "kinds",
    [
        ("assignment", "secret"),
        ("secret", "assignment"),
    ],
    ids=["assignment_then_secret", "secret_then_assignment"],
)
def test_batch_assignment_id_survives_invalid_secret_both_orders(
    game, monkeypatch, kinds,
):
    """#1565 N1 / d.1.3.4：批归并不抹先项成功 ID；非空 F0 前缀一次 + secret 后缀。

    复用 materialize 多意图入口；两种顺序均须：assignment 持久化 ID 可回指，
    secret 零契约失败记录仍在；baseline F0 只出现一次。单 ID 契约不变。
    """
    from ming_sim import cli_backend as cb
    from ming_sim.action_clusters import candidates_from_classifier_payload

    db, state, _ = game
    name = _minister(db)
    # 合法 JSON 但零契约 → secret 路拒暂存并写 failures（#1504）
    canned = json.dumps({
        "标题": "",
        "内容": "",
        "承办人": name,
        "期限月数": 0,
        "标签": [],
        "差务": "",
        "价值轴": [],
        "方向": 1,
        "交付单位": "",
        "交付目标": 0,
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cb, "_run_json_extractor_for_config",
        lambda *_a, **_k: (canned, 1),
    )

    by_kind = {
        "assignment": {
            "kind": "assignment",
            "title": "清核太仓",
            "target_id": "qinghe-taicang",
            "commitment_kind": "无",
        },
        "secret": {"kind": "secret", "secret_action": "新建"},
    }
    payload = [by_kind[k] for k in kinds]
    candidates = candidates_from_classifier_payload(payload, soft=False)
    assert len(candidates) == 2

    F0 = [{"kind": "baseline_fail", "message": "prefix-once", "retryable": True}]
    ctx = MaterializeCtx(
        session=SimpleNamespace(db=db, state=state),
        character=SimpleNamespace(name=name, office_type="文官"),
        player_message="清核太仓，并密查辽饷。",
        reply="臣请分办。",
        message_text="清核太仓，并密查辽饷。",
        explicit_prefixed=False,
        has_directive=False,
        pend_for_minister=[],
        out={"pending_action_failures": list(F0)},
        intent=None,
        intent_kind="none",
        llm_config=None,
        intent_candidates=candidates,
    )
    run_materialize_pipeline(ctx)

    pid = int(ctx.out.get("pending_action_id") or 0)
    assert pid > 0, f"assignment 成功 ID 须保留（order={kinds}），got 0"
    row = db.conn.execute(
        "SELECT kind, payload_json FROM pending_actions WHERE id=?", (pid,),
    ).fetchone()
    assert row is not None
    assert row["kind"] == "directive"
    staged = json.loads(row["payload_json"])
    assert staged.get("dossier_action_type") == "assignment"
    assert staged.get("title") == "清核太仓"

    fails = list(ctx.out.get("pending_action_failures") or [])
    assert fails, f"secret 失败记录须保留（order={kinds})"
    assert any(f.get("kind") == "secret_order" for f in fails)
    # d.1.3.4：非空 baseline 前缀一次 + 后缀含 secret δ
    assert fails[:1] == F0
    assert sum(1 for f in fails if f == F0[0]) == 1
    assert any(f.get("kind") == "secret_order" for f in fails[1:])


def test_create_secret_order_rejects_missing_contract(game):
    db, state, _ = game
    name = _minister(db)
    with pytest.raises(CovertContractError):
        db.create_secret_order(
            state, name, "无合同密令", "无显式差务", [], deadline_months=1,
        )
    assert db.list_secret_orders() == []


def test_purpose_liaoxiang_canonicalizes_to_other_and_counts(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    frozen = build_covert_task_contract(
        kind="核发辽饷", axes=["实务事功"], direction=1,
        delivery_unit="万两", delivery_target_units=3, effect_sign=-1,
        purpose="辽饷", category="密令差务", account="内库",
    )
    assert frozen["delivery"]["purpose"] == "其它"
    with pytest.raises(CovertContractError):
        build_covert_task_contract(
            kind="核发辽饷", axes=["实务事功"], direction=1,
            delivery_unit="万两", delivery_target_units=3,
            purpose="辽饷", category="密令差务", account="内库",
        )
    oid = db.create_secret_order(
        state, name, "核发辽饷", "核发辽饷", [],
        deadline_months=1, covert_task=frozen,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["purpose"] == "其它"
    settle_with_delta(
        state, db, {"dossier_progress_reports": [_report(did, "发令")]},
        before_turn=state.turn, content=content,
    )
    settle_with_delta(
        state, db,
        _delta_work(oid, did, memorial="实发", eco=-3, report=True),
        before_turn=state.turn, content=content,
    )
    assert db.sum_dossier_actual_progress_units(did) == 3.0
    assert db.get_secret_order(oid)["status"] == "done"


def test_region_monthly_progress_sums_increments_without_final_value_gate(game):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "清丈河南", "清丈", months=2, target=5, unit="万亩")
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn, year, period, region_id, field, old_value, new_value, delta, reason, origin_ref) "
        "VALUES (?, ?, ?, 'henan', 'registered_land', '420', '422', 2, 'test', ?)",
        (state.turn, state.year, state.period, f"dossier:{did}"),
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 2.0
    state.turn += 1
    db.save_state(state)
    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn, year, period, region_id, field, old_value, new_value, delta, reason, origin_ref) "
        "VALUES (?, ?, ?, 'henan', 'registered_land', '422', '425', 3, 'test', ?)",
        (state.turn, state.year, state.period, f"dossier:{did}"),
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 5.0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done"


def test_public_secret_order_forwards_investigation_without_unit(game):
    from ming_sim.tools import build_minister_tools

    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    ctx = SimpleNamespace(db=db, state=state)
    character = SimpleNamespace(name=name, office_type="文官")
    tools = build_minister_tools(character, ctx)
    secret_order = next(fn for fn in tools if getattr(fn, "__name__", "") == "secret_order")
    out = secret_order(
        "issue",
        title="查核侵冒",
        content="查核侵冒",
        kind="查核辽饷侵冒",
        axes_json='["既得利益"]',
        direction=1,
        delivery_target_units=2,
        investigation_target=target,
        effect_sign=1,
    )
    assert out.startswith("__secret_order__")
    payload = json.loads(out[len("__secret_order__"):])
    contract = payload["covert_task"]
    assert contract["investigation_target"] == target
    assert contract["delivery"]["effect_sign"] == 1
    assert "unit" not in contract["delivery"]


def test_positive_inflow_does_not_freeze_purpose_and_counts(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    frozen = build_covert_task_contract(
        kind="抄家入帑", axes=["实务事功"], direction=1,
        delivery_unit="万两", delivery_target_units=1, effect_sign=1,
        purpose="其它", category="密令差务", account="内库",
    )
    assert "purpose" not in frozen["delivery"]
    with pytest.raises(CovertContractError):
        build_covert_task_contract(
            kind="抄家入帑", axes=["实务事功"], direction=1,
            delivery_unit="万两", delivery_target_units=1, effect_sign=1,
            purpose="补饷", category="密令差务", account="内库",
        )
    oid = db.create_secret_order(
        state, name, "抄家入帑", "入内库", [],
        deadline_months=1, covert_task=frozen,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did, delta=1)
    row = db.conn.execute(
        "SELECT purpose, delta FROM economy_ledger WHERE origin_ref=? ORDER BY id DESC LIMIT 1",
        (f"dossier:{did}",),
    ).fetchone()
    assert row is not None
    assert int(row["delta"]) == 1
    assert row["purpose"] in (None, "")
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    applied = next(r for r in out if r.get("order_id") == oid)
    assert applied.get("originated_quantity") == 1.0
    assert db.sum_dossier_actual_progress_units(did) == 1.0
    settled = settle_due_secret_orders(db, state, commit=True)
    row_s = next(r for r in settled if r["order_id"] == oid)
    assert row_s["status"] == "done"


def test_pay_delivery_requires_army_identity(game):
    from ming_sim.tools import build_minister_tools

    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    with pytest.raises(CovertContractError):
        build_covert_task_contract(
            kind="补发饷银", axes=["既得利益"], direction=1,
            delivery_unit="万两", delivery_target_units=1, effect_sign=-1,
            purpose="补饷", category="密令差务", account="内库",
        )
    ctx = SimpleNamespace(db=db, state=state)
    character = SimpleNamespace(name=name, office_type="文官")
    tools = build_minister_tools(character, ctx)
    secret_order = next(fn for fn in tools if getattr(fn, "__name__", "") == "secret_order")
    public_out = secret_order(
        "issue",
        title="补发京营欠饷", content="补发京营欠饷",
        kind="补发饷银", axes_json='["既得利益"]', direction=1,
        delivery_unit="万两", delivery_target_units=1,
        purpose="补饷", category="密令差务", account="内库",
        effect_sign=-1,
    )
    assert public_out.startswith("密令下达失败")
    assert db.list_secret_orders() == []
    army_id = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    db.conn.execute("UPDATE armies SET arrears=? WHERE id=?", (50, army_id))
    db.conn.commit()
    frozen = build_covert_task_contract(
        kind="补发饷银", axes=["既得利益"], direction=1,
        delivery_unit="万两", delivery_target_units=1, effect_sign=-1,
        purpose="补饷", category="密令差务", account="内库",
        target_kind="army", target_id=army_id,
    )
    assert frozen["delivery"]["target_kind"] == "army"
    assert frozen["delivery"]["target_id"] == army_id
    public_ok = secret_order(
        "issue",
        title="补发京营欠饷", content="补发京营欠饷",
        kind="补发饷银", axes_json='["既得利益"]', direction=1,
        delivery_unit="万两", delivery_target_units=1,
        purpose="补饷", category="密令差务", account="内库",
        target_kind="army", target_id=army_id,
        effect_sign=-1,
        dossier_links_json='[{"target_dossier_id": 999, "relation_type": "稽核", "note": "关联旧卷"}]',
    )
    assert public_ok.startswith("__secret_order__")
    payload = json.loads(public_ok[len("__secret_order__"):])
    assert payload["covert_task"]["delivery"]["target_id"] == army_id
    oid = db.create_secret_order(
        state, name, "补发饷银", "补发欠饷", [],
        deadline_months=1, covert_task=frozen,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["purpose"] == "补饷"
    assert contract["delivery"]["target_kind"] == "army"
    assert contract["delivery"]["target_id"] == army_id
    state.turn += 1
    db.save_state(state)
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "内库",
                "delta": -1,
                "category": "密令差务",
                "reason": "补发欠饷",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": army_id,
                "origin_ref": f"dossier:{did}",
            }],
        },
        content=content,
    )
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    applied = next(r for r in out if r.get("order_id") == oid)
    assert applied.get("originated_quantity") == 1.0


def test_topic_investigation_confirm_and_faithful_done(game, monkeypatch):
    """北极星：专题查核确认成案；忠实机械带到期可 done。不预植 seed_guilt。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    topic = "辽饷转运及押运相关人员"
    polaris = "查核辽饷侵冒、勿使杨嗣昌与闻"
    applied = _confirm_investigation(
        db, state, content, monkeypatch, minister=name, target=topic,
        months=3, player_message=polaris,
    )
    oid = int(applied["secret_order_id"])
    assert oid > 0
    order = db.get_secret_order(oid)
    assert order["status"] == "active"
    span = db.conn.execute(
        "SELECT deadline_span FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["deadline_span"]
    assert int(span) == 3
    dossier = db.get_dossier_for_secret_order(oid)
    contract = read_covert_task_contract(dossier)
    assert contract["investigation_target"] == topic
    did = int(dossier["id"])
    assert db.conn.execute(
        "SELECT seed_guilt FROM characters WHERE name=?",
        (topic,),
    ).fetchone() is None
    for _ in range(3):
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(
            db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
        )
    assert db.sum_dossier_actual_progress_units(did) == 3.0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done"
    assert row["actual_units"] == 3.0
    assert db.get_secret_order(oid)["status"] == "done"
    assert db.list_economy_moves_for_dossier(did) == []


def test_topic_investigation_backlash_fails_without_world_package(game):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    topic = "辽饷转运及押运相关人员"
    oid = _issue(
        db, state, name, "查核辽饷侵冒、勿使杨嗣昌与闻", "查核辽饷侵冒、勿使杨嗣昌与闻",
        months=1, target=4, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=topic,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "反噬"}], commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["units"] == 0.0
    after_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert after_loyalty == before_loyalty
    assert int(state.metrics.get("内库", 0)) == before_neiku
    assert db.list_economy_moves_for_dossier(did) == []
    db.conn.execute("UPDATE secret_orders SET due_turn=? WHERE id=?", (state.turn, oid))
    db.conn.commit()
    settled = settle_due_secret_orders(db, state, commit=True)
    close = next(r for r in settled if r["order_id"] == oid)
    assert close["status"] == "failed"
    assert close["actual_units"] == 0.0
