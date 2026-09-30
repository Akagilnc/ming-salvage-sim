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
    _CAPACITY_MAX,
    _CAPACITY_MIN,
    _FACT_DIFFICULTY_EVIDENCE_EDGE,
    _MONTHLY_EFFORT_CAP,
    CovertContractError,
    apply_investigation_monthly_effort,
    apply_investigation_spoliation,
    build_covert_task_contract,
    build_secret_covert_effect_briefs,
    decide_secret_order_settlement,
    investigation_fact_difficulty,
    investigation_monthly_capacity,
    live_investigation_fact_keys,
    monthly_actual_units,
    progress_units_for_state,
    read_covert_task_contract,
    require_covert_task_contract,
    seed_guilt_counts_as_debt,
    apply_monthly_covert_actual_progress,
    investigation_lane_actual_units,
    read_substantiated_legal_reason_code,
    settle_due_secret_orders,
)
from ming_sim.person_archive_contract import PERSON_LEGAL_REASON_CODES
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent


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
def test_unlimited_investigation_due_now_reads_real_acquisitions(game, due_action):
    """#1896：无期限查核经提交/即核到期，结案读真实查获——不再按"一月配额"判。

    取代旧 test_..._uses_one_month_quota（拿期限月数当固定配额＝旧轨满统一阈残影）。
    此处密令约定取证 1 条，承办人真投入到该条难度 → 已掌握 1 条 → 办结。
    """
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
        db, state, name, "无期查核", "查核侵冒",
        months=0, target=1, kind="查核侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    _dig_months(db, state, oid, target, months=2)
    assert investigation_lane_actual_units(db, did) == 1.0

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
    assert row["actual_units"] == 1.0        # 已掌握 1 条罪证
    assert row["target_units"] == 1.0        # 对密令约定的取证条数，与期限月数无关


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


def test_investigation_mastery_needs_effort_to_reach_fact_difficulty(game):
    """#1896：投入累计到"该条罪证自己的难度"才记已掌握；无统一阈值、不自动写依律。

    取代旧"执行态折固定增量、满 1 自动坐实并固定写依律"。
    """
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
        months=6, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    assert difficulty > 0.0

    # 敷衍：本月零投入 → 不查获、也不改实证
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 0.0}], commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["effort_applied"] == 0.0
    assert row["units"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}
    assert lanes[target]["mastered"] is False
    assert lanes[target]["effort"] == 0.0
    # 掌握证据 ≠ 已依法清算：满阈不自动写依律
    assert read_substantiated_legal_reason_code(db, target, target) == ""

    # 投入未达难度：累计但不查获（实投＝强度×承办人实况，非模型直采）
    capacity = investigation_monthly_capacity(db, name, dossier_id=did)
    apply_investigation_monthly_effort(
        db, did, target, name, fact_key=target,
        intensity=0.5, commit=True,
    )
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}
    assert lanes[target]["mastered"] is False
    assert lanes[target]["effort"] == pytest.approx(
        min(_MONTHLY_EFFORT_CAP, 0.5 * capacity)
    )
    assert investigation_lane_actual_units(db, did) == 0.0

    # 首月在查（months=1）：即便满强度，单月也不得坐实（堵一月速坐实）
    assert _lanes(db, oid)[target]["months"] == 1
    apply_investigation_monthly_effort(
        db, did, target, name, fact_key=target, intensity=1.0, commit=True,
    )
    # 次月补足：累计实投达难度且已满 floor → 该条已掌握，
    # 且仍不自动写依律/翻轴（掌握 ≠ 清算）
    assert _lanes(db, oid)[target]["months"] == 2
    assert _lanes(db, oid)[target]["mastered"] is True
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}
    assert lanes[target]["mastered"] is True
    assert not lanes[target].get("reason_code")
    assert read_substantiated_legal_reason_code(db, target, target) == ""
    assert investigation_lane_actual_units(db, did) == 1.0

    # 运行期新长的把柄边入同一案即新 lane，可再查
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="侵冒把柄", origin=f"test:{did}", evidence=True,
    )
    edge_difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=str(edge_id), investigator=name,
    )
    # 边事实基准档更高（已落库的实物/证词边比待坐实罪谱更难撬）
    assert edge_difficulty > difficulty
    # 逐月投入至该条难度（边事实更难，需更多月），满 floor 后方掌握
    result = {}
    for _ in range(12):
        result = apply_investigation_monthly_effort(
            db, did, target, name, fact_key=str(edge_id), intensity=1.0, commit=True,
        )
        if str(edge_id) in (result.get("mastered") or []):
            break
    assert str(edge_id) in result["mastered"]
    assert _lanes(db, oid)[str(edge_id)]["effort"] >= edge_difficulty
    assert investigation_lane_actual_units(db, did) == 2.0

    # 本案已掌握的事实在再投入时不重复计数、不虚增查获
    again = apply_investigation_monthly_effort(
        db, did, target, name, fact_key=target, intensity=1.0, commit=True,
    )
    assert again["effort_applied"] == 0.0
    assert again["mastered"] == []
    assert investigation_lane_actual_units(db, did) == 2.0


def test_difficulty_varies_by_ability_and_travel(game):
    """#1896：办案人能力与实际到差行程都进难度——不同人不同差走查案不同难。"""
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", ("侵冒", target))
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (target,))
    db.conn.execute(
        "UPDATE characters SET ability=88, location='beizhili', transit_to='' WHERE name=?",
        (name,),
    )
    db.conn.commit()
    able_here = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    # 同人在远地办差 → 行程更远 → 更难
    db.conn.execute(
        "UPDATE characters SET location='yunnan' WHERE name=?", (name,),
    )
    db.conn.commit()
    able_far = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    assert able_far > able_here
    # 换弱能力承办人 → 更难
    weak = db.conn.execute(
        "SELECT name FROM characters WHERE name NOT IN (?,?) AND status='active' LIMIT 1",
        (name, target),
    ).fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET ability=30, location='beizhili' WHERE name=?", (weak,),
    )
    db.conn.commit()
    weak_here = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=weak,
    )
    assert weak_here > able_here


def test_no_evidence_case_opens_and_stays_empty(game):
    """#1896：无证可开案（空 lane 集合法）——不造罪，也不是免费清白神谕。

    清白目标照样占案、照样到期结案为查无实据，不即时拒开、不产查获。
    """
    db, state, _ = game
    name = _minister(db)
    # 取真相底确无实有罪证者（无 seed_guilt 且无 evidence 边）＝空 lane 集
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters "
            "WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if not live_investigation_fact_keys(db, row["name"])
    )
    assert live_investigation_fact_keys(db, target) == []
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "查核清白者", "查核清白者",
        months=1, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    assert db.get_secret_order(oid)["status"] == "active"  # 照开
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 1.0}], commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["effort_applied"] == 0.0  # 空 lane 集：投入无处可施，no-op 不抛
    assert row["units"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0
    settled = settle_due_secret_orders(db, state, commit=True)
    close = next(r for r in settled if r["order_id"] == oid)
    assert close["status"] == "failed"
    assert close["actual_units"] == 0.0


def _relation_informer(db, source, target, *, context="通风报信之路"):
    """取与目标真有 0081 关系边的人；无则先落一条真实边（知情须有真实关系可循）。"""
    for edge in db.get_relation_edge_events(person=target):
        who = str(edge["source"]) if str(edge["target"]) == target else str(edge["target"])
        if who and who != target:
            return who
    db.record_relation_edge_event(
        source=source, target=target, event_kind="恩义",
        context=context, origin="test:1896-informer", evidence=False,
    )
    return str(source)


def test_spoliation_requires_real_knowledge_source(game):
    """#1896：开案不等于被查者知情——无真实关系网来源，引擎不代其毁证。"""
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    key = live_investigation_fact_keys(db, target)[0]
    base = investigation_fact_difficulty(
        db, target=target, fact_key=key, investigator=name,
    )

    # 无来源 → 不毁
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone", commit=True,
    )
    assert out["applied"] is False
    assert "知情" in out["reason"]
    assert db.list_investigation_spoiled_facts(target) == []
    assert investigation_fact_difficulty(
        db, target=target, fact_key=key, investigator=name,
    ) == base

    # 凭空捏造一个不相干的人 → 仍不毁（账本里查无此关系边）
    stranger = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name NOT IN (?,?)",
            (name, target),
        ).fetchall()
        if not db.get_relation_edge_events(person=target)
        or all(
            str(e["source"]) != row["name"] and str(e["target"]) != row["name"]
            for e in db.get_relation_edge_events(person=target)
        )
    )
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=stranger, commit=True,
    )
    assert out["applied"] is False
    assert db.list_investigation_spoiled_facts(target) == []

    # 真实关系网里的人递话 → 知情成立，其毁证选择被承接
    informer = _relation_informer(db, name, target)
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=informer, commit=True,
    )
    assert out["applied"] is True
    assert out["knowledge_source"] == informer
    assert investigation_fact_difficulty(
        db, target=target, fact_key=key, investigator=name,
    ) == float("inf")


def test_4a_unknown_target_declaring_spoliation_is_rejected(game):
    """#1896 贯穿 4a：被查者不知情而声明毁证 → 落账拒，实证不动。"""
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核无从下手", "查核无从下手",
        months=2, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[{
            "order_id": oid,
            "effort": 0.0,
            # 无知情来源的毁证声明
            "spoliation": {"effect": "gone", "fact_key": key},
        }],
        commit=True,
    )
    assert db.list_investigation_spoiled_facts(target) == []
    assert investigation_fact_difficulty(
        db, target=target, fact_key=key, investigator=name,
    ) != float("inf")
    assert key in live_investigation_fact_keys(db, target)
    assert investigation_lane_actual_units(db, did) == 0.0


def test_spoliation_makes_fact_harder_and_survives_case_reopen(game):
    """#1896 / ADR 0100 后出：毁证按事实改可查性，不团灭，重开案不恢复。"""
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
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", ("贪墨", other))
    db.conn.commit()
    base = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="另一条罪证", origin=f"test:spoil", evidence=True,
    )
    other_difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=str(edge_id), investigator=name,
    )

    # 毁一条 → 该条变难查；同目标其他事实无损（知情来源须是真实关系网里的人）
    informer = _relation_informer(db, name, target)
    out = apply_investigation_spoliation(
        db, target=target, fact_key=target, effect="harder",
        knowledge_source=informer, commit=True,
    )
    assert out["applied"] is True
    harder = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    assert harder > base
    assert investigation_fact_difficulty(
        db, target=target, fact_key=str(edge_id), investigator=name,
    ) == other_difficulty

    # 毁成 gone → 该事实永不可查，且投入再多也查不回来
    apply_investigation_spoliation(
        db, target=target, fact_key=target, effect="gone",
        knowledge_source=informer, commit=True,
    )
    assert investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    ) == float("inf")
    oid = _issue(
        db, state, name, "重开查案", "重开查案",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    result = apply_investigation_monthly_effort(
        db, did, target, name, fact_key=target, intensity=1.0, commit=True,
    )
    assert result["effort_applied"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0

    # 真相底本身不动：罪仍在册（毁的是可查性，不是"罪是否实有"）
    assert target in live_investigation_fact_keys(db, target)
    # 重复毁同一事实不叠第二次
    rows = db.list_investigation_spoiled_facts(target)
    assert len([r for r in rows if r["fact_key"] == target]) == 2  # harder + gone 各一


def test_clue_pointing_at_absent_fact_is_dropped_not_credited(game):
    """#1896：线索只助其所指实有证据；指向不存在的罪 → 确定性丢弃，不造罪。"""
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
        db, state, name, "查核辽饷", "查核辽饷",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    result = apply_investigation_monthly_effort(
        db, did, target, name, fact_key="不存在的罪证键", intensity=1.0, commit=True,
    )
    assert result["effort_applied"] == 0.0
    assert result["dropped_fact_key"] == "不存在的罪证键"
    assert investigation_lane_actual_units(db, did) == 0.0
    assert live_investigation_fact_keys(db, target) == [target]


def test_false_memorial_does_not_create_or_erase_evidence(game):
    """#1896：奏报可以谎——假密奏不造罪也不抹证，结案只读实账。"""
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
        db, state, name, "谎报密查", "谎报密查",
        months=1, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    # 奏报自称"已查明全部" + 零投入
    db.record_dossier_progress(
        did, state.turn, "办成", "臣已查明全部罪状", is_terminal=False,
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 0.0}], commit=True,
    )
    settled = settle_due_secret_orders(db, state, commit=True)
    close = next(r for r in settled if r["order_id"] == oid)
    assert close["status"] == "failed"
    assert close["actual_units"] == 0.0
    # 实证未被奏报改动：罪仍在真相底
    assert target in live_investigation_fact_keys(db, target)


def test_4a_declaration_routes_to_per_fact_accounting_and_spoliation(game):
    """#1896 贯穿 4a 接缝：effort/fact_key/spoliation 三项声明走既有写口落账。

    不新增人物调用、不新增转译调用、不新增第二写口——只是既有
    ``covert_exec_selections`` 里的查案项按新形状被核算。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="第二条罪证", origin="test:1896-e2e", evidence=True,
    )
    keys = live_investigation_fact_keys(db, target)
    assert str(edge_id) in keys
    oid = _issue(
        db, state, name, "查核两罪", "查核两罪",
        months=2, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    state.turn += 1
    db.save_state(state)
    informer = _relation_informer(db, name, target)
    # 4a 产物形状：深挖一条 + 毁掉另一条
    selection = {
        "order_id": oid,
        "effort": 1.0,
        "fact_key": target,
        "spoliation": {
            "effect": "harder", "fact_key": str(edge_id),
            "knowledge_source": informer,
        },
        "note": "臣已查得实据",
    }
    apply_monthly_covert_actual_progress(
        db, state, selections=[selection], commit=True,
    )
    # 首月实投受引擎硬顶，尚不足坐实（最低在查月数亦未满）
    assert investigation_lane_actual_units(db, did) == 0.0
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state, selections=[selection], commit=True,
    )
    # 次月补足 → 深挖那条已掌握
    assert investigation_lane_actual_units(db, did) == 1.0
    # 毁证那条 → 可查性被抬高（不再只是边事实的基准档），但真相底不动、也未查获
    harder = investigation_fact_difficulty(
        db, target=target, fact_key=str(edge_id), investigator=name,
    )
    assert harder > _FACT_DIFFICULTY_EVIDENCE_EDGE
    assert str(edge_id) in live_investigation_fact_keys(db, target)
    # 实况轨逐月各落一笔（幂等键 dossier+turn），查获数取自 lane 账非月进度和
    rows = db.list_dossier_actual_progress(did)
    assert len(rows) == 2
    assert rows[-1]["units"] == 1.0
    # 掌握不等于自动清算
    assert read_substantiated_legal_reason_code(db, target, target) == ""


def _dig_months(db, state, oid, fact_key, intensity=1.0, months=1):
    """经真实 4a 入口连推数月（逐月推进 turn，落一条 selections）。"""
    for _ in range(int(months)):
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fact_key": fact_key, "effort": intensity}],
            commit=True,
        )


def _lanes(db, oid):
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    return {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}


def test_absurd_declared_effort_cannot_master_in_one_month(game):
    """#1896 修判官 finding 1：4a 声明的 effort 是无上限裸数 → 当月坐实任意罪证。

    人物只声明 0..1 的**强度**（人心的选择），本月实投由引擎按其真实状态折算并
    硬顶；且坐实须该条已在查满最低月数。故模型写 effort=100 也不能一月坐实。
    经真实入口（4a selections → apply_monthly_covert_actual_progress）断言。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核",
        months=6, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    # 模型把 effort 填到荒谬的 100
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fact_key": key, "effort": 100}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    # 声明被 clamp 成强度 1；实投由引擎核出且有硬顶，不等于 100
    assert row["effort_applied"] <= _MONTHLY_EFFORT_CAP
    assert row["effort_applied"] < 100.0
    # 且因最低在查月数未满，首月不得坐实
    assert investigation_lane_actual_units(db, did) == 0.0
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}
    assert lanes[key]["mastered"] is False
    assert lanes[key]["months"] == 1

    # 连续多月满强度深挖：逐月累计，但受硬顶约束，不会一月跳完
    difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=key, investigator=name,
    )
    months_needed = 0
    for _ in range(12):
        if investigation_lane_actual_units(db, did) >= 1.0:
            break
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fact_key": key, "effort": 1.0}],
            commit=True,
        )
        months_needed += 1
    assert investigation_lane_actual_units(db, did) == 1.0
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    lanes = {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}
    assert lanes[key]["effort"] >= difficulty
    # 首月那句 effort=100 已在案上，故总在查月数 = 1 + 循环月数，且已满 floor
    assert lanes[key]["months"] == months_needed + 1
    assert lanes[key]["months"] >= 2


def test_capacity_bounds_effort_by_ability_presence_and_bandwidth(game):
    """#1896 修判官 finding 1：实投按承办人真实状态折算（能力／在途／0092 带宽）。"""
    db, state, _ = game
    name = _minister(db)
    # 强能吏、在差上、无其它在办差务
    db.conn.execute(
        "UPDATE characters SET ability=88, transit_to='' WHERE name=?", (name,),
    )
    db.conn.commit()
    free = investigation_monthly_capacity(db, name)
    assert free > 0.0
    # 同样的强度，在途未到差 → 打折
    db.conn.execute(
        "UPDATE characters SET transit_to='yunnan' WHERE name=?", (name,),
    )
    db.conn.commit()
    traveling = investigation_monthly_capacity(db, name)
    assert traveling < free
    db.conn.execute("UPDATE characters SET transit_to='' WHERE name=?", (name,))
    # 庸人 → 更低
    db.conn.execute("UPDATE characters SET ability=30 WHERE name=?", (name,))
    db.conn.commit()
    weak = investigation_monthly_capacity(db, name)
    assert weak < free
    # 带宽：手上未结差务越多，可分的越少（0092 带宽①）
    db.conn.execute("UPDATE characters SET ability=88 WHERE name=?", (name,))
    db.conn.commit()
    before = investigation_monthly_capacity(db, name)
    for _ in range(2):
        _issue(db, state, name, "另案", "另案", months=6, target=1)
    db.conn.commit()
    loaded = investigation_monthly_capacity(db, name)
    assert loaded < before
    # 恒在引擎边界内，且与任何模型输入无关
    assert _CAPACITY_MIN <= loaded <= _CAPACITY_MAX


def test_deep_dig_and_perfunctory_differ_but_are_bounded(game):
    """#1896：深挖与敷衍产生不同实投，但两者都被引擎 clamp 在硬顶之下。

    三个案各查一个不同对象，同月同承办人，唯一差别是声明强度——差异只能来自
    声明本身，而实投一律受引擎硬顶约束。此处直接打引擎口（clamp 就在这一层）；
    经 4a 入口的端到端断言见 test_absurd_declared_effort_cannot_master_in_one_month。
    """
    db, state, _ = game
    name = _minister(db)
    targets = [
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    ][:3]
    _set_axes(db, name, loyalty=90, identity=30)
    seen = {}
    for target, intensity in zip(targets, (0.0, 1.0, 100.0)):
        key = live_investigation_fact_keys(db, target)[0]
        oid = _issue(
            db, state, name, "查核", "查核", months=6, target=1,
            kind="查核", axes=["既得利益"], investigation_target=target,
        )
        did = int(db.get_dossier_for_secret_order(oid)["id"])
        apply_investigation_monthly_effort(
            db, did, target, name, fact_key=key, intensity=intensity, commit=True,
        )
        seen[intensity] = float(_lanes(db, oid)[key]["effort"])

    idle, deep, over = seen[0.0], seen[1.0], seen[100.0]
    assert idle == 0.0                    # 敷衍／停办＝本月零投入
    assert deep > idle                    # 深挖确实多下了功夫
    assert over == deep                    # 超范围声明被 clamp，与满强度无异
    assert 0.0 < deep <= _MONTHLY_EFFORT_CAP   # 且都在引擎硬顶之下


def test_supply_feed_carries_per_fact_investigation_materials(game):
    """#1896：4a 供料带逐证清单（键/难度/已投入/状态），模型才可能声明 fact_key。

    空 lane 集（清白目标）照发空清单——不因无证而拒开案。
    """
    from ming_sim.month_chain import build_secret_orders_supply_feed

    db, state, _ = game
    name = _minister(db)
    guilty = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    clean = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if not live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "密查有罪者", "密查有罪者",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=guilty,
    )
    clean_oid = _issue(
        db, state, name, "密查清白者", "密查清白者",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=clean,
    )
    state.turn += 1
    db.save_state(state)

    feed = build_secret_orders_supply_feed(db, state, {})
    orders = {int(o["id"]): o for o in feed["active_secret_orders"]}
    assert oid in orders and clean_oid in orders
    hot = orders[oid]
    assert hot["investigation_target"] == guilty
    keys = [f["fact_key"] for f in hot["investigation_facts"]]
    assert keys == live_investigation_fact_keys(db, guilty)
    fact = hot["investigation_facts"][0]
    assert fact["state"] == "在查"
    assert fact["effort_so_far"] == 0.0
    assert fact["months_under_investigation"] == 0
    # 难度是引擎的账，不递给模型当答案
    assert "difficulty" not in fact
    # 清白目标：照开案、照列空清单
    assert orders[clean_oid]["investigation_facts"] == []

    # 已掌握的事实在供料里如实标为已掌握，供下一月据实决策
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    difficulty = investigation_fact_difficulty(
        db, target=guilty, fact_key=keys[0], investigator=name,
    )
    apply_investigation_monthly_effort(
        db, did, guilty, name, fact_key=keys[0], intensity=1.0, commit=True,
    )
    apply_investigation_monthly_effort(
        db, did, guilty, name, fact_key=keys[0], intensity=1.0, commit=True,
    )
    feed2 = build_secret_orders_supply_feed(db, state, {})
    orders2 = {int(o["id"]): o for o in feed2["active_secret_orders"]}
    fact2 = orders2[oid]["investigation_facts"][0]
    assert fact2["state"] == "已掌握"


def test_spoliated_fact_reported_as_unreachable_in_feed(game):
    """#1896：被毁成 gone 的罪证在供料里标湮灭，难度不给数字（inf 不外泄）。"""
    from ming_sim.month_chain import build_secret_orders_supply_feed

    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    key = live_investigation_fact_keys(db, target)[0]
    informer = _relation_informer(db, name, target)
    apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=informer, commit=True,
    )
    oid = _issue(
        db, state, name, "密查被毁证者", "密查被毁证者",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    state.turn += 1
    db.save_state(state)
    feed = build_secret_orders_supply_feed(db, state, {})
    order = next(o for o in feed["active_secret_orders"] if int(o["id"]) == oid)
    fact = next(f for f in order["investigation_facts"] if f["fact_key"] == key)
    assert fact["state"] == "已被毁证湮灭"
    assert "difficulty" not in fact  # 不把难度／inf 摆给模型


def test_closed_case_blocks_same_fact_on_later_case_and_due(game):
    """#1896：同一事实不重复查获——换案重查同一罪证不再计入本案查获。

    另一对象的案不受牵连（逐 lane 记账，不按人整体清零）。
    """
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
    t_difficulty = investigation_fact_difficulty(
        db, target=target, fact_key=target, investigator=name,
    )
    o_difficulty = investigation_fact_difficulty(
        db, target=other, fact_key=other, investigator=name,
    )
    oid = _issue(
        db, state, name, "查核辽饷侵冒", "查核辽饷侵冒",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    state.turn += 1
    db.save_state(state)
    _dig_months(db, state, oid, target, months=2)
    assert investigation_lane_actual_units(
        db, int(db.get_dossier_for_secret_order(oid)["id"])
    ) == 1.0
    first = settle_due_secret_orders(db, state, commit=True)
    assert first and first[0]["status"] == "done"
    assert db.get_secret_order(oid)["status"] == "done"

    oid2 = _issue(
        db, state, name, "再查同人", "再查同人",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    did2 = int(db.get_dossier_for_secret_order(oid2)["id"])
    oid_other = _issue(
        db, state, name, "另一对象", "另一对象",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=other,
    )
    did_other = int(db.get_dossier_for_secret_order(oid_other)["id"])
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[
            {"order_id": oid2, "fact_key": target, "effort": t_difficulty},
            {"order_id": oid_other, "fact_key": other, "effort": o_difficulty / 2.0},
        ],
        commit=True,
    )
    # 同一事实已被前案查获 → 本案投入确定性丢弃，不重复查获
    assert investigation_lane_actual_units(db, did2) == 0.0
    # 另一对象：投入只到半程 → 未达难度，未查获
    assert investigation_lane_actual_units(db, did_other) == 0.0

    out = settle_due_secret_orders(db, state, commit=True)
    by_id = {r["order_id"]: r for r in out}
    assert by_id[oid2]["status"] == "failed"
    assert by_id[oid2]["actual_units"] == 0.0
    assert by_id[oid_other]["status"] == "failed"
    assert by_id[oid_other]["actual_units"] == 0.0


def test_fiscal_quantity_tracer_same_unit_done_and_gap(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "补发五千", "补发饷银",
        months=1, target=20, kind="补发饷银", axes=["既得利益"], unit="万两",
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
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
    _originate_work(db, state, content, did, delta=-20)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    settle_due_secret_orders(db, state, commit=True)
    assert db.sum_dossier_actual_progress_units(did) == 20.0
    assert db.get_secret_order(oid)["status"] == "done"

    oid2 = _issue(
        db, state, name, "补发缺口", "补发饷银",
        months=1, target=20, kind="补发饷银", axes=["既得利益"], unit="万两",
    )
    did2 = int(db.get_dossier_for_secret_order(oid2)["id"])
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did2, delta=-4)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid2, "fidelity": "忠实"}], commit=True,
    )
    settle_due_secret_orders(db, state, commit=True)
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
    state.turn += 1
    db.save_state(state)
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
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did, delta=-3)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    settle_due_secret_orders(db, state, commit=True)
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