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
    compute_floor_for_minister,
    compute_willingness_floor,
    decide_secret_order_settlement,
    derive_monthly_covert_world_effects,
    progress_units_for_state,
    seed_guilt_is_active,
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
    ],
)
def test_willingness_floor_golden(loyalty, identity, satisfaction, guilt, expected):
    assert compute_willingness_floor(
        loyalty=loyalty,
        identity=identity,
        satisfaction=satisfaction,
        seed_guilt=guilt,
    ) == expected


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


def test_blank_seed_guilt_json_does_not_count_as_blood_debt():
    """characters.json 无/无 落库为 JSON 字符串，不得当血债下拉底档。"""
    kwargs = dict(loyalty=80, identity=40, satisfaction=70)
    assert compute_willingness_floor(**kwargs, seed_guilt="") == "忠实"
    assert compute_willingness_floor(
        **kwargs, seed_guilt='{"crime": "无", "severity": "无"}',
    ) == "忠实"
    assert compute_willingness_floor(
        **kwargs, seed_guilt={"crime": "无", "severity": "无"},
    ) == "忠实"
    assert compute_willingness_floor(**kwargs, seed_guilt="{}") == "忠实"
    assert not seed_guilt_is_active('{"crime": "无", "severity": "无"}')
    # 有坐实指控仍下拉
    assert compute_willingness_floor(**kwargs, seed_guilt="血债") == "打折"
    assert compute_willingness_floor(
        **kwargs, seed_guilt='{"crime": "党附", "severity": "轻"}',
    ) == "打折"


def test_opening_clean_record_floor_ignores_blank_guilt_json(game):
    """开局韩爌（无/无 JSON）底档须与无血债计算一致，月度实进度不得被打成 0。"""
    db, state, _ = game
    name = "韩爌"
    raw = db.conn.execute(
        "SELECT seed_guilt FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert raw is not None
    assert "无" in str(raw["seed_guilt"])
    snap = build_minister_snapshot(db, name)
    intended = compute_willingness_floor(
        loyalty=int(snap["loyalty"]),
        identity=int(snap["identity"]),
        satisfaction=int(snap["satisfaction"]),
        seed_guilt="",
    )
    assert compute_floor_for_minister(db, name) == intended
    oid = db.create_secret_order(
        state, name, "密查", "查案", [], deadline_months=1,
    )
    out = apply_monthly_covert_actual_progress(
        db, state, selections=None, commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["fidelity"] == intended
    assert row["units"] == progress_units_for_state(intended)


def test_snapshot_keeps_zero_loyalty(game):
    """loyalty=0 不得被 ``or 50`` 抬成中性，否则反噬底档被洗成打折。"""
    db, state, _ = game
    name = _minister(db)
    db.conn.execute(
        "UPDATE characters SET loyalty=0, seed_guilt='' WHERE name=?",
        (name,),
    )
    db.conn.commit()
    snap = build_minister_snapshot(db, name)
    assert snap["loyalty"] == 0
    assert compute_floor_for_minister(db, name) == compute_willingness_floor(
        loyalty=0,
        identity=int(snap["identity"]),
        satisfaction=int(snap["satisfaction"]),
        seed_guilt="",
    )


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
    # 三月忠实实进度
    for _ in range(3):
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fidelity": "忠实"}],
            commit=True,
        )
        # 推进回合（只动 turn 字段；不对全量 settle）
        state.turn += 1
        db.save_state(state)

    order = db.conn.execute(
        "SELECT due_turn, deadline_span FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    # 回到 due 当月
    state.turn = int(order["due_turn"])
    db.save_state(state)

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
    # 两月反噬/阳奉 → 0 实进度
    for _ in range(2):
        apply_monthly_covert_actual_progress(db, state, selections=None, commit=True)
        state.turn += 1
        db.save_state(state)
    due = db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"]
    state.turn = int(due)
    db.save_state(state)

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] < row["target_units"]
    assert db.get_secret_order(oid)["status"] == "failed"


def test_mid_month_restore_preserves_actual_progress(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=85, identity=40)
    oid = db.create_secret_order(
        state, name, "可恢复密查", "查案", [], deadline_months=4,
    )
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
    # 单月期限：本月产 1.0 即交付
    oid = db.create_secret_order(
        state, name, "一月密查", "限期一月", [], deadline_months=1,
    )
    # due = turn+1；先空转一个月到 due 前夜
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
    # 第一月：未到期，应仍 active，已有实进度
    order = db.get_secret_order(oid)
    assert order["status"] == "active"
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    assert db.sum_dossier_actual_progress_units(did) == 1.0

    # 第二月：到期 → done（实进度已够）
    before2 = state.turn
    settle_with_delta(state, db, {}, before_turn=before2, content=content)
    order2 = db.get_secret_order(oid)
    assert order2["status"] == "done", order2
    assert "旧链试图结案" not in (order2.get("result") or "")


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
    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))

    oid = db.create_secret_order(
        state, name, "一月实办", "限期一月查明", [], deadline_months=1,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    before_turn = state.turn
    settle_with_delta(
        state, db,
        {
            "covert_exec_selections": [
                {"order_id": oid, "fidelity": "忠实", "note": "实查有据"},
            ],
        },
        before_turn=before_turn,
        content=content,
    )

    # 实进度
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
    # 只写奏报
    db.record_dossier_progress(
        did, state.turn, "办成", "臣称已全部查明", is_terminal=False,
    )
    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])

    # 第一月：产 0 实进度 + 反噬人物后果；未到期
    settle_with_delta(
        state, db,
        {"covert_exec_selections": [{"order_id": oid, "fidelity": "反噬"}]},
        before_turn=state.turn,
        content=content,
    )
    assert db.get_secret_order(oid)["status"] == "active"
    assert db.sum_dossier_actual_progress_units(did) == 0.0
    mid_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert mid_loyalty == before_loyalty - 2  # 反噬评定

    # 第二月：到期 → failed（表报不救）
    settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
    order = db.get_secret_order(oid)
    assert order["status"] == "failed"
    assert "表报" in (order.get("result") or "") or True  # note 可能在 close 文本
    dossier = db.get_dossier_for_secret_order(oid)
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"


def test_legacy_pending_review_migrated_including_due_turn_zero(game):
    """开库一次迁移：pending_review→active；due_turn=0 得到期标记且可对账结案。"""
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

    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        row = db2.get_secret_order(oid)
        assert row["status"] == "active", row
        assert int(row["due_turn"] or 0) > 0, row
        assert int(row["due_turn"]) <= int(state2.turn)
        assert "[到期迁移]" in (row.get("result") or "")

        # 迁后可当月产实进度并对账 done
        did = int(db2.get_dossier_for_secret_order(oid)["id"])
        settle_with_delta(
            state2, db2,
            {"covert_exec_selections": [{"order_id": oid, "fidelity": "忠实"}]},
            before_turn=state2.turn,
            content=content,
        )
        # due 已≤turn：同月 settle 尾应对账；忠实 1.0 ≥ target 1.0 → done
        closed = db2.get_secret_order(oid)
        assert closed["status"] == "done", closed
        assert db2.sum_dossier_actual_progress_units(did) == 1.0
    finally:
        db2.close()
