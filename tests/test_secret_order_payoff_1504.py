"""#1504 B 包：密令机械实进度 + 到期缺口对账 + 拆 secret_order_closes 真源。

Seams:
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

from ming_sim.covert_progress import (
    FACT_LANES_KEY,
    INVESTIGATION_PROVENANCE_KEY,
    CovertContractError,
    build_covert_task_contract,
    build_secret_covert_effect_briefs,
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
    _sanitize_module_output,
)
from tests.conftest import stub_scene_agent


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


def test_seed_guilt_structured_clean_vs_debt():
    assert not seed_guilt_counts_as_debt("")
    assert not seed_guilt_counts_as_debt(None)
    assert not seed_guilt_counts_as_debt({"crime": "无", "severity": "无"})
    assert not seed_guilt_counts_as_debt('{"crime": "无", "severity": "无"}')
    assert seed_guilt_counts_as_debt("血债")
    assert seed_guilt_counts_as_debt({"crime": "交结近侍", "severity": "中"})


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
    # 两月由推演者选反噬 → 0 实进度（跳过发令月）
    for _ in range(2):
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(
            db, state, selections=[{"order_id": oid, "fidelity": "反噬"}], commit=True,
        )
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


def test_monthly_actual_progress_preserves_selected_fidelity_in_sqlite(game):
    db, state, _ = game
    name = _minister(db)
    # The old loyalty-derived floor must not rewrite the selected execution state.
    _set_axes(db, name, loyalty=20, identity=80, seed_guilt="x")
    oid = _issue(db, state, name, "执行态由推演者决定", "本月执行态由推演者决定", months=2, target=2)
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["fidelity"] == "忠实"
    persisted = db.list_dossier_actual_progress(row["dossier_id"])
    assert persisted[-1]["fidelity_state"] == "忠实"


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
    missing_state_oid = _issue(
        db, state, name, "执行态缺失仍可隔离", "独立密令", months=2, target=5,
    )
    missing_state_did = int(db.get_dossier_for_secret_order(missing_state_oid)["id"])
    settle_with_delta(
        state, db, {"dossier_progress_reports": [
            _report(did, "发令月密奏"),
            _report(missing_state_did, "独立密令发令月密奏"),
        ]},
        before_turn=state.turn, content=content,
    )
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    settlement_turn = int(state.turn)
    second_month = _delta_work(oid, did, memorial="实查有据", eco=-3, report=True)
    second_month["dossier_progress_reports"].append(
        _report(missing_state_did, "执行态缺失案卷照常月报")
    )
    settle_with_delta(
        state, db,
        second_month,
        before_turn=state.turn,
        content=content,
    )

    assert db.sum_dossier_actual_progress_units(did) == 3.0
    assert db.sum_dossier_actual_progress_units(missing_state_did) == 0.0
    rejection = db.conn.execute(
        "SELECT section, category, reason, item_json FROM rejection_reports "
        "WHERE turn=? AND section='covert_exec_selections'",
        (settlement_turn,),
    ).fetchone()
    assert rejection is not None
    assert rejection["category"] == "invalid_enum"
    assert rejection["reason"]
    assert json.loads(rejection["item_json"]) == {"order_id": missing_state_oid}
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


def _recovery_compose_fed(
    call: dict, *emperor_frags: str, prior_raw: str = "",
) -> bool:
    """Recovery compose received actual gaps, emperor context, and prior product.

    Structured kwargs only — not prompt labels/headers (anchoring constitution).
    Losing gaps/prior/context must fail; label/header reword must not.
    """
    emperor = str(call.get("emperor_words") or "")
    frags = [f for f in emperor_frags if f]
    if frags and not any(f in emperor for f in frags):
        return False
    gaps = [str(g).strip() for g in (call.get("landing_gaps") or []) if str(g).strip()]
    if not gaps:
        return False
    prior = str(call.get("prior_output") or "")
    if prior_raw:
        needle = prior_raw if prior_raw in prior else prior_raw.strip()
        return bool(needle) and needle in prior
    return bool(prior.strip())
