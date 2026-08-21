"""#1504 B 包：密令机械实进度 + 到期缺口对账 + 拆 secret_order_closes 真源。

Seams:
- compute_willingness_floor / clamp_fidelity_to_floor（纯函数 golden）
- dossier_actual_progress 实况容器（origin 纪律；≠ dossier_progress_json）
- apply_monthly_covert_actual_progress + settle_due_secret_orders（settle 同 atomic）
- 正反例：已交付→done、缺口→failed；表报背离不翻实账
- secret_order_closes 不再落库结案
- auto_submit 不再翻 pending_review
"""

from __future__ import annotations

import json

import pytest

from ming_sim.covert_progress import (
    FIDELITY_STATES,
    build_minister_snapshot,
    clamp_fidelity_to_floor,
    compute_willingness_floor,
    decide_secret_order_settlement,
    derive_monthly_covert_world_effects,
    progress_units_for_state,
    seed_guilt_counts_as_debt,
    target_progress_units,
    apply_monthly_covert_actual_progress,
    settle_due_secret_orders,
)
from ming_sim.decree import settle_with_delta
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase


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


# ── 实况容器 ──────────────────────────────────────────────────────────


def test_actual_progress_container_separate_from_reported_rail(game):
    db, state, _ = game
    name = _minister(db)
    oid = db.create_secret_order(
        state, name, "密查国丈", "查周奎私通状", ["查案"], deadline_months=3,
    )
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
    assert reported[0]["memorial_text"] == "臣称已有端绪"
    assert "dossier_progress_json" not in json.dumps(actual, ensure_ascii=False)
    # list_dossier_durable_effects 仍只 economy+fiscal；实进度走并列读口
    durable = db.list_dossier_durable_effects(did)
    assert all("account" in r or "key" in r or "delta" in r for r in durable) or durable == []
    assert db.list_dossier_actual_rail(did)  # 含 actual_progress 行


def test_reported_progress_never_enters_settlement_books(game):
    """表报灌满 + 实况为空 → 到期 failed；实账不被表报翻盘。"""
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=20, identity=80)
    oid = db.create_secret_order(
        state, name, "空转密查", "查无实据之案", [], deadline_months=1,
    )
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


# ── 月度实进度 + 到期对账 ─────────────────────────────────────────────


def test_monthly_actual_then_delivered_done(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = db.create_secret_order(
        state, name, "三月密查", "限期三月查明", [], deadline_months=3,
    )
    # 发令月不计进度：从 T+1 起三月忠实
    for _ in range(3):
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fidelity": "忠实"}],
            commit=True,
        )

    order = db.conn.execute(
        "SELECT due_turn, deadline_span FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    # 已在 due 当月（issued+3）
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
    oid = db.create_secret_order(
        state, name, "必败密查", "无人真办", [], deadline_months=2,
    )
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
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    n = 3
    oid = db.create_secret_order(
        state, name, "恰三月", "验窗口", [], deadline_months=n,
    )
    issued = int(state.turn)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 发令当月：0 tick
    out0 = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    assert not any(r.get("order_id") == oid and not r.get("skipped") and r.get("units") is not None
                   and not r.get("rejected") for r in out0 if r.get("order_id") == oid and "units" in r)
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    ticks = 0
    for _ in range(n):
        state.turn += 1
        db.save_state(state)
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
    oid = db.create_secret_order(
        state, name, "离场密令", "不应再办", [], deadline_months=2,
    )
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
    oid = db.create_secret_order(
        state, name, "幽灵承办", "人已不在册", [], deadline_months=2,
    )
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
    oid = db.create_secret_order(
        state, name, "可恢复密查", "查案", [], deadline_months=4,
    )
    # 跳过发令月再落笔
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
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
    oid = db.create_secret_order(
        state, name, "一月密查", "限期一月", [], deadline_months=1,
    )
    before = state.turn
    settle_with_delta(
        state, db,
        {
            "covert_exec_selections": [
                {"order_id": oid, "fidelity": "忠实", "note": "查有实据"},
            ],
            # 旧真源：即使注入也不得结案
            "secret_order_closes": [
                {"order_id": oid, "status": "failed", "result": "旧链试图结案"},
            ],
        },
        before_turn=before,
        content=content,
    )
    # 发令月 settle：未到期、无实进度（发令月排除）
    order = db.get_secret_order(oid)
    assert order["status"] == "active"
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    # 次月：产 1.0 并到期 → done
    before2 = state.turn
    settle_with_delta(
        state, db,
        {"covert_exec_selections": [{"order_id": oid, "fidelity": "忠实"}]},
        before_turn=before2,
        content=content,
    )
    order2 = db.get_secret_order(oid)
    assert order2["status"] == "done", order2
    assert db.sum_dossier_actual_progress_units(did) == 1.0
    assert "旧链试图结案" not in (order2.get("result") or "")
    # P7：玩家 result 不得是机械到期对账模板
    assert "到期对账" not in (order2.get("result") or "")
    assert "machine_settle" not in (order2.get("result") or "")


def test_secret_order_closes_no_longer_applies(game):
    db, state, content = game
    name = _minister(db)
    oid = db.create_secret_order(
        state, name, "旧链密令", "不应被 closes 结", [], deadline_months=3,
    )
    # 旧路径依赖 pending_review；即便强行改状态，apply 也不应 close
    db.conn.execute(
        "UPDATE secret_orders SET status='pending_review' WHERE id=?", (oid,),
    )
    db.conn.commit()

    out = apply_score_extraction(
        db, state,
        {
            "secret_order_closes": [
                {"order_id": oid, "status": "done", "result": "LLM 伪结案"},
            ],
        },
        content=content,
    )
    closes = out.get("secret_order_closes") or []
    # 退役：不落成功结案
    assert all(item.get("rejected") or item.get("retired") for item in closes) or closes == []
    assert db.get_secret_order(oid)["status"] == "pending_review"


def test_auto_submit_due_no_longer_flips_pending_review(game):
    db, state, _ = game
    name = _minister(db)
    oid = db.create_secret_order(
        state, name, "到期仍在办", "到期对账前保持 active", [], deadline_months=1,
    )
    due = db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"]
    state.turn = int(due)
    db.save_state(state)

    submitted = db.auto_submit_due_secret_orders(state)
    # 可记录到期戳，但不得再 pending_review
    order = db.get_secret_order(oid)
    assert order["status"] == "active", order
    assert all(item.get("id") != oid or item.get("status") != "pending_review"
               for item in (submitted or [{"id": oid, "status": order["status"]}]))


def test_judge_selection_cannot_lighten_floor(game):
    db, state, _ = game
    name = _minister(db)
    # 低忠诚 → 底档至少 阳奉/反噬
    _set_axes(db, name, loyalty=20, identity=80, seed_guilt="x")
    oid = db.create_secret_order(
        state, name, "不可洗白", "底档钳制", [], deadline_months=2,
    )
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


def test_derive_world_effects_by_fidelity_origin():
    """clamp 后四态机械派生人物/钱粮/局势包，一律 origin_ref=dossier:N。"""
    pkg = derive_monthly_covert_world_effects(
        fidelity="忠实",
        minister_name="袁崇焕",
        dossier_id=17,
        faction="东林",
        region_id="beijing",
        title="密查",
    )
    assert pkg["origin_ref"] == "dossier:17"
    assert pkg["人物变更"][0]["loyalty"] == 1
    assert pkg["人物变更"][0]["origin_ref"] == "dossier:17"
    assert pkg["economy_moves"][0]["delta"] == -3
    assert pkg["economy_moves"][0]["origin_ref"] == "dossier:17"
    # 忠实不伤局势/派系
    assert pkg["metric_delta"] == {}
    assert pkg["faction_delta"] == {}

    backlash = derive_monthly_covert_world_effects(
        fidelity="反噬",
        minister_name="袁崇焕",
        dossier_id=9,
        faction="东林",
        region_id="beijing",
        title="反噬案",
    )
    assert backlash["人物变更"][0]["loyalty"] == -2
    assert backlash["economy_moves"] == []
    assert backlash["metric_delta"].get("皇威") == -1
    assert backlash["faction_delta"]["东林"]["satisfaction"] == -2
    assert backlash["region_delta"]["beijing"]["unrest"] == 2
    assert backlash["region_delta"]["beijing"]["origin_ref"] == "dossier:9"


def test_settle_applies_world_effects_and_restore(game):
    """真入口 settle_with_delta：忠实落人物+钱粮；restore 后世界态与实进度无损。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)

    oid = db.create_secret_order(
        state, name, "一月实办", "限期一月查明", [], deadline_months=1,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 发令月：无进度
    settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    settle_with_delta(
        state, db,
        {
            "covert_exec_selections": [
                {"order_id": oid, "fidelity": "忠实", "note": "实查有据"},
            ],
        },
        before_turn=state.turn,
        content=content,
    )

    # 实进度（次月）
    assert db.sum_dossier_actual_progress_units(did) == 1.0
    actual_row = db.list_dossier_actual_progress(did)[0]
    assert actual_row["fidelity_state"] == "忠实"
    assert actual_row["origin_ref"] == f"dossier:{did}"
    # 人物：忠诚 +1
    after_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert after_loyalty == before_loyalty + 1
    # 钱粮：内库 -3，origin 回指案卷（禁 sim_note/progress_json 冒充）
    eco = db.list_economy_moves_for_dossier(did)
    assert any(int(r.get("delta") or 0) == -3 for r in eco), eco
    assert all(str(r.get("origin_ref") or "") == f"dossier:{did}" for r in eco)
    assert int(state.metrics.get("内库", 0)) == before_neiku - 3

    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        assert db2.sum_dossier_actual_progress_units(did) == 1.0
        assert int(db2.conn.execute(
            "SELECT loyalty FROM characters WHERE name=?", (name,)
        ).fetchone()["loyalty"]) == after_loyalty
        assert int(state2.metrics.get("内库", 0)) == before_neiku - 3
        eco2 = db2.list_economy_moves_for_dossier(did)
        assert any(int(r.get("delta") or 0) == -3 for r in eco2)
        # 奏报轨未冒充
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
    oid = db.create_secret_order(
        state, name, "必败一月", "无人真办", [], deadline_months=1,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    memorial = "臣称已全部查明"
    db.record_dossier_progress(
        did, state.turn, "办成", memorial, is_terminal=False,
    )
    # 发令月：无实进度
    settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
    assert db.get_secret_order(oid)["status"] == "active"
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    # 次月：产 0 实进度 + 反噬人物后果并到期 failed
    settle_with_delta(
        state, db,
        {"covert_exec_selections": [{"order_id": oid, "fidelity": "反噬"}]},
        before_turn=state.turn,
        content=content,
    )
    mid_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert mid_loyalty == before_loyalty - 2  # 反噬评定
    order = db.get_secret_order(oid)
    assert order["status"] == "failed"
    # P7：玩家正文复用奏报，不是机械模板；表报不翻实账
    assert order.get("result") == memorial or memorial in (order.get("result") or "")
    assert "到期对账" not in (order.get("result") or "")
    assert "machine_settle" not in (order.get("result") or "")
    dossier = db.get_dossier_for_secret_order(oid)
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    # 奏报链不被机械结案句改写
    reports = db.list_dossier_progress(did)
    assert any(r.get("memorial_text") == memorial for r in reports)
    assert not any("到期对账" in str(r.get("memorial_text") or "") for r in reports)


def test_legacy_pending_review_migrated_including_due_turn_zero(game):
    """开库一次迁移：pending_review→active；due_turn=0 得未来实况窗，不立即失败。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = db.create_secret_order(
        state, name, "旧核议令", "应被迁移", [], deadline_months=0,
    )
    # 模拟旧档：pending_review + due_turn=0（旧 list_due 永不会收）
    db.conn.execute(
        "UPDATE secret_orders SET status='pending_review', due_turn=0 WHERE id=?",
        (oid,),
    )
    db.conn.commit()
    assert db.get_secret_order(oid)["status"] == "pending_review"
    issued_turn = int(state.turn)

    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        row = db2.get_secret_order(oid)
        assert row["status"] == "active", row
        assert int(row["due_turn"] or 0) > 0, row
        # 发令当月迁入：窗口在未来，不 due<=current 立即结算
        assert int(row["due_turn"]) > int(state2.turn), row
        assert "[到期迁移]" in (row.get("result") or "")

        did = int(db2.get_dossier_for_secret_order(oid)["id"])
        # 迁入当月：不立即 failed
        settle_with_delta(
            state2, db2,
            {"covert_exec_selections": [{"order_id": oid, "fidelity": "忠实"}]},
            before_turn=state2.turn,
            content=content,
        )
        assert db2.get_secret_order(oid)["status"] == "active"
        assert db2.sum_dossier_actual_progress_units(did) == 0.0

        # 次月：产实进度并对账 done
        settle_with_delta(
            state2, db2,
            {"covert_exec_selections": [{"order_id": oid, "fidelity": "忠实"}]},
            before_turn=state2.turn,
            content=content,
        )
        closed = db2.get_secret_order(oid)
        assert closed["status"] == "done", closed
        assert db2.sum_dossier_actual_progress_units(did) == 1.0
        assert int(closed["due_turn"]) == issued_turn + 1
    finally:
        db2.close()


def test_legacy_multimonth_pending_review_reopen_not_instant_fail(game):
    """多月旧令重开：不空实况立即失败；只按新实况结案；不回填奏报/sim_note。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = db.create_secret_order(
        state, name, "三月旧核议", "多月旧令", [], deadline_months=3,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 表报/sim_note 灌满——迁移不得当实况
    db.record_dossier_progress(
        did, state.turn, "在办", "臣称三月皆已办妥", is_terminal=False,
    )
    db.conn.execute(
        "UPDATE secret_orders SET status='pending_review', sim_note=? WHERE id=?",
        ("推演称已办成", oid),
    )
    db.conn.commit()

    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        row = db2.get_secret_order(oid)
        assert row["status"] == "active"
        assert row["status"] != "pending_review"
        # 尚缺 3 units → 未来窗，不立即 due 结算
        assert int(row["due_turn"]) > int(state2.turn), row
        assert db2.sum_dossier_actual_progress_units(did) == 0.0

        # 重开当月不得 failed
        settle_with_delta(state2, db2, {}, before_turn=state2.turn, content=content)
        assert db2.get_secret_order(oid)["status"] == "active"

        # 三月忠实实况后结 done（只按新实况）
        for _ in range(3):
            settle_with_delta(
                state2, db2,
                {"covert_exec_selections": [{"order_id": oid, "fidelity": "忠实"}]},
                before_turn=state2.turn,
                content=content,
            )
        closed = db2.get_secret_order(oid)
        assert closed["status"] == "done", closed
        assert db2.sum_dossier_actual_progress_units(did) == 3.0
        # 禁复活 pending_review
        assert closed["status"] != "pending_review"
        assert db2.list_secret_orders(status="pending_review") == []
    finally:
        db2.close()


def test_legacy_with_partial_actual_only_fills_remaining_window(game):
    """已有 actual 行：迁移只补剩余窗口，不回填、不重算已有实况。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = db.create_secret_order(
        state, name, "半程旧令", "已有一笔实况", [], deadline_months=3,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 先有 1.0 实况
    db.record_dossier_actual_progress(
        did, state.turn, units=1.0, fidelity_state="忠实", floor_state="忠实",
        note="旧实况", commit=True,
    )
    db.conn.execute(
        "UPDATE secret_orders SET status='pending_review', due_turn=? WHERE id=?",
        (int(state.turn), oid),  # 旧错误：due 已到
    )
    db.conn.commit()

    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        row = db2.get_secret_order(oid)
        assert row["status"] == "active"
        # remaining = 2 → due = current+1（issued < current 时）或更远
        # turn_issued == current → due = current + 2
        assert int(row["due_turn"]) >= int(state2.turn) + 1
        assert db2.sum_dossier_actual_progress_units(did) == 1.0
        # 不得从任何奏报灌实况
        assert len(db2.list_dossier_actual_progress(did)) == 1
    finally:
        db2.close()
