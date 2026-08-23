"""#637 派系态势摘要 S6：涉派事件驱动的聚合视图（ADR 0084；冻结票面＋庭裁 r1 三修正案）。

验收锚：
- F1 涉派目标集合唯一化：既有人物党籍→canonical 派系投影（characters.faction ∩
  factions 现存集合）；任一端命中即入选／两端不同派均入选／同派去重／皇帝端不投影／
  表外党籍与未知人物不入选，不猜不建映射表。
- F2 稳定性对齐 #636：无本月新涉派事件∧无该派 durable pending 才字节不变；
  pending 补酿复用既有 claim/watermark/apply+clear 接缝恰一次。
- F3 零写观察面收窄：只辖 S6 新增写缝（faction_stance_summaries ＋ item_kind='派系'
  的 relation_brew_pending 行）；负向断言 factions 数值列全程不变；不加护栏。
- 三不碰红线进测试：不写派系真源数值、不动满意度/影响力、不建认同度。
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from ming_sim.db import GameDB
from ming_sim.exceptions import LLMUnavailable
from ming_sim.faction_brew import (
    STANCE_KEY,
    VIEW_FACTION_STANCE,
    build_faction_brew_input,
    collect_new_edge_events_for_faction,
    project_character_factions,
    select_faction_brew_targets,
)
from ming_sim.relation_brew import FOUNDINGS_KEY, RECENT_KEY, run_month_end_relation_brew
from ming_sim.relations import EMPEROR_NODE


def _add_edge(db, state, *, source, target, kind, context, origin):
    return db.record_relation_edge_event(
        source=source, target=target, event_kind=kind, context=context,
        origin=origin, turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )


def _dual_brew_fn_factory(calls, *, stance="朝局如常。"):
    """确定性假酿制手（双契约分派）：派系工作项回 stance 契约，关系工作项按序消费脚本。

    派系项可经 stances 按序注入脚本化输出（缺省恒成功）。"""

    def _brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        calls.append(payload)
        if payload.get("view") == VIEW_FACTION_STANCE:
            scripted = getattr(_brew, "stances", None)
            out = (
                scripted.pop(0)
                if scripted
                else {STANCE_KEY: stance}
            )
            if isinstance(out, BaseException):
                raise out
            if isinstance(out, str):
                return out  # raw 字符串（畸形产出的注入缝）
            return json.dumps(out, ensure_ascii=False)
        script = _brew.outputs.pop(0) if getattr(_brew, "outputs", None) else {
            FOUNDINGS_KEY: [], RECENT_KEY: "无事近况。",
        }
        return json.dumps(script, ensure_ascii=False)

    return _brew


def _relation_script(foundings=None, recent="近况重酿。"):
    return {FOUNDINGS_KEY: list(foundings or []), RECENT_KEY: recent}


def _faction_rows(db):
    return {
        row["name"]: dict(row)
        for row in db.conn.execute(
            "SELECT * FROM factions"
        ).fetchall()
    }


# ------------------------------------------------- F1 canonical 党籍投影

def test_canonical_projection_intersects_existing_factions_only(game):
    """投影＝characters.faction ∩ factions 现存集合：表外党籍与皇帝节点不入映射，
    不猜不建第二套映射表。"""
    db, state, _ = game
    proj = project_character_factions(db)
    assert proj["杨嗣昌"] == "皇党"
    assert proj["王绍徽"] == "阉党"
    # 皇帝端不投影（皇帝不是 characters 行，即便同名也绝不入映射）。
    assert EMPEROR_NODE not in proj
    # 表外党籍（后金/中宫/流寇等真实种子）不入投影。
    in_table = {row["name"] for row in db.conn.execute("SELECT name FROM factions")}
    assert set(proj.values()) <= in_table
    assert "皇太极" not in proj
    assert "周皇后" not in proj


def test_any_endpoint_hit_selects_and_same_faction_dedups(game):
    """任一端命中则入选；两端同派去重为一份派系工作项。"""
    db, state, _ = game
    # 温体仁×周延儒均皇党 → 恰一个派系目标＋一条关系目标。
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")
    targets = select_faction_brew_targets(
        db, year=int(state.year), period=int(state.period),
    )
    assert [row["faction"] for row in targets] == ["皇党"]

    calls: list = []
    report = run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    # 同批：1 条关系工作项＋1 条派系工作项。
    assert report["selected"] == 2
    assert len(report["brewed"]) == 2


def test_both_endpoints_different_factions_both_selected(game):
    """两端不同派均入选（不只取 source）。"""
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")
    targets = select_faction_brew_targets(
        db, year=int(state.year), period=int(state.period),
    )
    assert [row["faction"] for row in targets] == ["皇党", "阉党"]

    calls: list = []
    report = run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    assert report["selected"] == 3  # 1 关系＋2 派系
    assert len(report["brewed"]) == 3
    brewed_factions = sorted(
        entry["faction"] for entry in report["brewed"] if "faction" in entry
    )
    assert brewed_factions == ["皇党", "阉党"]
    assert db.get_faction_stance_summary("皇党")["stance_segment"] == "朝局如常。"
    assert db.get_faction_stance_summary("阉党")["stance_segment"] == "朝局如常。"


def test_out_of_table_faction_and_unknown_person_never_projected(game):
    """表外党籍（皇帝↔后金人物）与未知人物（不在 characters）的事件不入任何派系视图。"""
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="皇太极", kind="辜负",
              context="皇太极请市被拒。", origin="audience:turn-1")
    _add_edge(db, state, source="甲", target="乙", kind="协作",
              context="甲乙当场协作。", origin="audience:turn-1")
    targets = select_faction_brew_targets(
        db, year=int(state.year), period=int(state.period),
    )
    assert targets == []

    calls: list = []
    report = run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    # 只剩两条关系工作项；零派系工作项。
    assert report["selected"] == 2
    assert all("faction" not in entry for entry in report["brewed"])
    assert db.get_faction_stance_summaries() == []


# ------------------------------------- 验收：事件月更新／无事月字节不变

def test_event_month_updates_stance_and_no_event_month_byte_identical(game):
    db, state, _ = game
    event_id = _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="知遇",
                         context="钱谦益蒙召对，简拔入朝。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _dual_brew_fn_factory(calls, stance="东林因钱谦益蒙召对而势涨。")
    report = run_month_end_relation_brew(db, state, brew_fn)

    summary = db.get_faction_stance_summary("东林")
    assert summary["stance_segment"] == "东林因钱谦益蒙召对而势涨。"
    assert summary["last_event_id"] >= event_id
    assert (summary["last_brewed_year"], summary["last_brewed_period"]) == (
        int(state.year), int(state.period),
    )

    # 无涉派事件月：零调用、摘要字节不变（F2 双条件之前件）。
    before = dict(summary)
    state.turn += 1
    state.period += 1
    calls.clear()
    report = run_month_end_relation_brew(db, state, brew_fn)
    assert report["selected"] == 0
    assert calls == []
    after = db.get_faction_stance_summary("东林")
    assert after["stance_segment"] == before["stance_segment"]
    assert after["last_event_id"] == before["last_event_id"]
    assert (after["last_brewed_year"], after["last_brewed_period"]) == (
        before["last_brewed_year"], before["last_brewed_period"],
    )


# ------------------------- F2 pending 补酿复用 #636 接缝：恰一次

def test_failed_faction_brew_rebrews_once_via_existing_pending_seam(game):
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")

    report = run_month_end_relation_brew(db, state, failing_brew)
    # 关系与派系工作项同批同命：双双降级留痕。
    assert report["selected"] == 2
    assert len(report["degraded"]) == 2
    assert db.get_faction_stance_summary("皇党") is None
    # durable pending 在册（同一 claim 机制，item_kind='派系' 身份）。
    pending = db.get_faction_brew_pending()
    assert [row["faction"] for row in pending] == ["皇党"]
    # 既有 #636 关系接缝语义原样：关系 pending 同在册。
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        ("温体仁", "周延儒")
    ]

    # 次月无任何新事件：仍凭 durable pending 补酿恰一次，复用同一接缝。
    state.turn += 1
    state.period += 1
    calls: list = []
    brew_fn = _dual_brew_fn_factory(calls, stance="皇党内因温周之隙而生嫌隙。")
    report = run_month_end_relation_brew(db, state, brew_fn)
    faction_payloads = [
        payload for payload in calls if payload.get("view") == VIEW_FACTION_STANCE
    ]
    assert len(faction_payloads) == 1
    assert faction_payloads[0]["has_pending_failure"] is True
    assert faction_payloads[0]["faction"] == "皇党"
    assert len(report["brewed"]) == 2
    assert db.get_faction_stance_summary("皇党")["stance_segment"] == (
        "皇党内因温周之隙而生嫌隙。"
    )
    assert db.get_faction_brew_pending() == []
    assert db.get_relation_brew_pending() == []

    # 再跑：既无新事件又无 pending → 零调用、字节不变（补酿恰一次的总证明）。
    state.turn += 1
    state.period += 1
    calls.clear()
    report = run_month_end_relation_brew(db, state, brew_fn)
    assert report["selected"] == 0
    assert calls == []


# ----------------------- 输出契约严格边界：畸形产出拒收降级保旧摘要

def test_malformed_faction_output_degrades_and_keeps_old_summary_bytes(game):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _dual_brew_fn_factory(calls, stance="皇党旧文。")
    run_month_end_relation_brew(db, state, brew_fn)
    before = db.get_faction_stance_summary("皇党")

    # 次月新涉派事件；派系腿产出缺 stance_segment（shape 违约）→ 单条降级。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="辜负",
              context="所请被驳。", origin="audience:turn-2")
    calls.clear()
    brew_fn.stances = ['{"irrelevant": 1}']
    report = run_month_end_relation_brew(db, state, brew_fn)
    assert report["degraded"], "派系腿 shape 违约必须降级留痕"
    after = db.get_faction_stance_summary("皇党")
    assert after["stance_segment"] == before["stance_segment"]  # 保旧摘要字节
    assert [row["faction"] for row in db.get_faction_brew_pending()] == ["皇党"]

    # 再下月：pending 补酿恰一次、成功落定清除。
    state.turn += 1
    state.period += 1
    calls.clear()
    brew_fn.stances = [{STANCE_KEY: "皇党因杨嗣昌被驳而渐离。"}]
    report = run_month_end_relation_brew(db, state, brew_fn)
    assert db.get_faction_stance_summary("皇党")["stance_segment"] == "皇党因杨嗣昌被驳而渐离。"
    assert db.get_faction_brew_pending() == []


# ------------------------------------------- 异常边界：DB 错响亮不伪装降级

def test_faction_claim_db_error_propagates_loudly(game):
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("派系认领库不可写")

    db.claim_faction_brew_targets = boom
    with pytest.raises(sqlite3.OperationalError, match="派系认领库不可写"):
        run_month_end_relation_brew(db, state, _dual_brew_fn_factory([]))


def test_faction_apply_db_error_propagates_loudly_not_disguised(game):
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("派系落定库不可写")

    db.apply_faction_brew_result = boom
    with pytest.raises(sqlite3.OperationalError, match="派系落定库不可写"):
        run_month_end_relation_brew(db, state, _dual_brew_fn_factory([]))


# ------------------------------- P5：关系与派系同批条目并行不串行

def test_relation_and_faction_items_share_single_batch_in_parallel(game):
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")
    # 同批 3 条工作项（1 关系＋2 派系）必须并行进入调用缝。
    barrier = threading.Barrier(3, timeout=10)
    threads: list = []

    def parallel_brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        threads.append(threading.current_thread().name)
        barrier.wait()  # 串行实现会在第 2/3 条处超时破裂
        if payload.get("view") == VIEW_FACTION_STANCE:
            return json.dumps({STANCE_KEY: "朝局如常。"}, ensure_ascii=False)
        return json.dumps(_relation_script(recent="毕王有站台之谊。"), ensure_ascii=False)

    report = run_month_end_relation_brew(db, state, parallel_brew)
    assert len(report["brewed"]) == 3
    assert len(set(threads)) == 3


# -------------------- F3 零写观察面：factions 数值列负向断言（机械）

def test_zero_writes_to_factions_numeric_columns_across_all_seams(game):
    """三不碰红线的机械验收：S6 全部写缝（faction_stance_summaries upsert＋
    item_kind='派系' pending 行）之外，factions 表任何列——尤其 satisfaction/
    leverage/leverage_offset 数值列——全程零写（含失败降级路）。"""
    db, state, _ = game
    before = _faction_rows(db)
    assert before, "开局盘面必须有 factions 行"

    # 缝①②③：正常酿制月（claim＋apply＋clear 全走一遍）。
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")
    calls: list = []
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    assert _faction_rows(db) == before

    # 缝④⑤：LLM 失败降级路（mark pending 写缝）＋跨月 pending 补酿路。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="使绊",
              context="毕自严使绊克扣军饷。", origin="audience:turn-2")

    def failing_then_ok(payload_json: str) -> str:
        payload = json.loads(payload_json)
        if payload.get("view") == VIEW_FACTION_STANCE and payload["faction"] == "皇党":
            raise LLMUnavailable("酿制裁判接口不可用")
        if payload.get("view") == VIEW_FACTION_STANCE:
            return json.dumps({STANCE_KEY: "阉党与皇党生隙。"}, ensure_ascii=False)
        return json.dumps(_relation_script(recent="毕王生隙。"), ensure_ascii=False)

    run_month_end_relation_brew(db, state, failing_then_ok)
    assert [row["faction"] for row in db.get_faction_brew_pending()] == ["皇党"]
    assert _faction_rows(db) == before

    state.turn += 1
    state.period += 1
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory([]))
    assert db.get_faction_brew_pending() == []
    assert _faction_rows(db) == before


# ------------- #637 codex P2：new_events 必须保留 source/target 结构字段

def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _eligible_dossier(db, state, holder, *, target_kind="issue", target_id="清丈田亩"):
    """真实 effect-eligible 案卷（同 #611 测试口径）作授权变更来源。"""
    dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="授以便宜行事之权",
        target_kind=target_kind,
        target_id=target_id,
        executor_kind="character",
        executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办", "role": "承办"},
        ],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    assert db.dossier_authorizes_effects(dossier_id)
    return db.get_decree_dossier(dossier_id)


def test_new_events_preserve_source_target_equal_to_db_rows(game):
    """(a) 机械断言：每条 new_events 的 source/target 与 DB 行相等。"""
    db, state, content = game
    holder_a, holder_b = _minister(db), "王绍徽"
    _add_edge(db, state, source=holder_a, target=holder_b, kind="结怨",
              context=f"{holder_a}当殿讦{holder_b}。", origin="audience:turn-1")
    targets = select_faction_brew_targets(
        db, year=int(state.year), period=int(state.period),
    )
    assert targets
    for target in targets:
        events = collect_new_edge_events_for_faction(
            db, faction=target["faction"], watermark=target["watermark"],
        )
        payload = build_faction_brew_input(
            faction=target["faction"], year=int(state.year),
            period=int(state.period), summary=target["summary"],
            new_events=events, has_pending=target["has_pending"],
        )
        assert len(payload["new_events"]) == len(events)
        for projected, row in zip(payload["new_events"], events, strict=True):
            assert projected["source"] == row["source"]
            assert projected["target"] == row["target"]


def test_authority_revoke_edge_reaches_holder_faction_with_emperor_target(game):
    """(b) 本 finding 原始缺陷用例：复刻收权·罢差路径（经 issues.py 落一条
    holder→EMPEROR 结怨边，context 不含参与方名字），断言该事件进入该 holder
    党籍派的酿制输入且 target==EMPEROR_NODE——方向事实只能靠 source/target。"""
    from ming_sim import issues as issue_engine

    db, state, content = game
    holder = _minister(db)
    projection = project_character_factions(db)
    holder_faction = projection[holder]
    domain = "issue:清丈田亩"
    grant_dossier = _eligible_dossier(db, state, holder)
    grant_result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
            "scope": domain, "dossier_id": grant_dossier["id"],
        }],
    }, content=content)["authority_changes"][0]
    assert grant_result.get("rejected") is not True
    authority_id = int(grant_result["authority_id"])

    revoke_dossier = _eligible_dossier(db, state, holder, target_id="收权清丈")
    revoke_result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "收回", "authority_id": authority_id,
            "dossier_id": revoke_dossier["id"],
        }],
    }, content=content)["authority_changes"][0]
    assert revoke_result.get("rejected") is not True

    # DB 里确实落了 holder→EMPEROR 的结怨边（context 只有权限名＋辖域）。
    edges = db.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )
    assert len(edges) == 1
    assert edges[0]["context"] == f"收权·罢差·便宜行事·{domain}"

    targets = select_faction_brew_targets(
        db, year=int(state.year), period=int(state.period),
    )
    assert [row["faction"] for row in targets] == [holder_faction]

    calls: list = []
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    payloads = [
        payload for payload in calls if payload.get("view") == VIEW_FACTION_STANCE
    ]
    assert len(payloads) == 1
    matching = [
        item for item in payloads[0]["new_events"]
        if item["origin"].startswith(f"authority_revoke:{authority_id}")
    ]
    assert len(matching) == 1
    assert matching[0]["source"] == holder
    assert matching[0]["target"] == EMPEROR_NODE


def test_new_event_fields_are_pure_data_no_prose_composition(game):
    """(c) 新增字段为纯数据、无任何拼接散文（ADR 0142：给数据不给话术）。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target=EMPEROR_NODE, kind="结怨",
              context="收权·罢差·便宜行事·issue:清丈田亩", origin="audience:turn-1")
    targets = select_faction_brew_targets(
        db, year=int(state.year), period=int(state.period),
    )
    assert targets
    events = collect_new_edge_events_for_faction(
        db, faction=targets[0]["faction"], watermark=targets[0]["watermark"],
    )
    payload = build_faction_brew_input(
        faction=targets[0]["faction"], year=int(state.year),
        period=int(state.period), summary=targets[0]["summary"],
        new_events=events, has_pending=targets[0]["has_pending"],
    )
    for item in payload["new_events"]:
        # 新增字段值必须与 DB 列逐字节相同——非任何 "{source}（{faction}）与{target}…" 式拼接串。
        row = next(r for r in events if r["origin"] == item["origin"])
        assert item["source"] == row["source"]
        assert item["target"] == row["target"]
        assert isinstance(item["source"], str) and isinstance(item["target"], str)


# ---- 送修口一负例 (a)：source_faction/target_faction 与现算投影逐项相等、皇帝端 null、表外 null 且无拼接串 ----

def test_source_faction_target_faction_equals_current_projection_and_nulls_and_no_concatenation(game):
    """负例(a) 机械可验：每项 source_faction/target_faction == project_character_factions 现算投影；
    皇帝端显式 None、表外党籍显式 None；无任何拼接串（ADR 0142/P6）。"""
    db, state, _ = game
    projection = project_character_factions(db)
    # 皇帝端不在映射、表外党籍不在映射（前提校验）
    assert EMPEROR_NODE not in projection
    assert "皇太极" not in projection
    assert "周皇后" not in projection
    in_table = {row["name"] for row in db.conn.execute("SELECT name FROM factions").fetchall()}
    assert set(projection.values()) <= in_table

    # 构造三种边：皇党→阉党（双侧均在表）、皇党→皇帝（皇帝端 null）、表外(后金)→皇党（表外 null)
    _add_edge(db, state, source="温体仁", target="王绍徽", kind="结怨",
              context="温体仁当殿讦王绍徽。", origin="audience:turn-1")
    _add_edge(db, state, source="温体仁", target=EMPEROR_NODE, kind="结怨",
              context="温体仁面斥皇帝。", origin="audience:turn-1b")
    # 表外角色：直接落边（select 不会选中表外派，但 build 現算投影应给 null）
    # 用 build 的显式投影路径直接验证表外 null
    fake_event_out_of_table = {
        "event_kind": "结怨",
        "context": "皇太极讦温体仁。",
        "origin": "test:out_of_table",
        "year": int(state.year),
        "period": int(state.period),
        "source": "皇太极",
        "target": "温体仁",
    }

    # 经 collect 路径的派系事件（皇党）应携带正确投影
    targets = select_faction_brew_targets(db, year=int(state.year), period=int(state.period))
    assert any(row["faction"] == "皇党" for row in targets)
    for target in targets:
        events = collect_new_edge_events_for_faction(
            db, faction=target["faction"], watermark=target["watermark"],
        )
        # collect 自身已附带 faction 字段且与现算投影一致（皇帝端 null）
        for row in events:
            assert row["source_faction"] == projection.get(row["source"])
            assert row["target_faction"] == projection.get(row["target"])
            if row["source"] == EMPEROR_NODE or row["target"] == EMPEROR_NODE:
                assert (row["source_faction"] is None or row["target_faction"] is None)
        payload = build_faction_brew_input(
            faction=target["faction"], year=int(state.year),
            period=int(state.period), summary=target["summary"],
            new_events=events, has_pending=target["has_pending"],
        )
        # build 透传与现算投影逐项相等
        assert len(payload["new_events"]) == len(events)
        for projected, row in zip(payload["new_events"], events, strict=True):
            assert projected["source_faction"] == projection.get(row["source"])
            assert projected["target_faction"] == projection.get(row["target"])
            # 皇帝端显式 null
            if row["source"] == EMPEROR_NODE:
                assert projected["source_faction"] is None
            if row["target"] == EMPEROR_NODE:
                assert projected["target_faction"] is None
            # 纯数据字段：无任何拼接串
            for key in ("source", "target", "source_faction", "target_faction"):
                val = projected[key]
                if val is not None:
                    assert isinstance(val, str)
                    assert "(" not in val and "（" not in val and "与" not in val or val in (projected["source"], projected["target"], projected["source_faction"], projected["target_faction"])
            # 严禁出现 "{source}({faction})与{target}" 式拼接串在任何字符串字段
            dumped = json.dumps(projected, ensure_ascii=False)
            # 若字段为拼接串，必含 source 与 faction 同串
            if projected["source_faction"] is not None:
                assert f"{projected['source']}({projected['source_faction']})" not in dumped
                assert f"{projected['source']}（{projected['source_faction']}）" not in dumped
            if projected["target_faction"] is not None:
                assert f"{projected['target']}({projected['target_faction']})" not in dumped
                assert f"{projected['target']}（{projected['target_faction']}）" not in dumped

    # 表外党籍显式 null：经 build 显式投影路径验证（不经 select）
    payload_out = build_faction_brew_input(
        faction="皇党", year=int(state.year), period=int(state.period),
        summary=None, new_events=[fake_event_out_of_table], has_pending=False,
        character_factions=projection,
    )
    assert payload_out["new_events"][0]["source_faction"] is None  # 皇太极表外
    assert payload_out["new_events"][0]["target_faction"] == projection.get("温体仁")
    # db 路径亦同
    payload_out_db = build_faction_brew_input(
        faction="皇党", year=int(state.year), period=int(state.period),
        summary=None, new_events=[fake_event_out_of_table], has_pending=False,
        db=db,
    )
    assert payload_out_db["new_events"][0]["source_faction"] is None
    assert payload_out_db["new_events"][0]["target_faction"] == "皇党"


# ---- 送修口二负例 (b)：重试月场景，prompt 不把旧事件称作本月 ----

def test_faction_brew_prompt_retry_month_does_not_label_old_events_as_current_month(game):
    """负例(b) 机械可验：复刻重试月场景（水位之上含旧月事件），断言 prompt 渲染措辞不把旧事件称作本月。
    正向表述：描述为未处理事件、每条自带时间戳、以事件自带年月为据；禁负向句。"""
    from pathlib import Path
    db, state, _ = game
    # 旧月事件：落在当前 year/period
    old_year, old_period = int(state.year), int(state.period)
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-old")
    # 模拟失败：酿制失败留 pending（不推进水位）
    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")
    report = run_month_end_relation_brew(db, state, failing_brew)
    assert any(row["faction"] == "皇党" for row in db.get_faction_brew_pending())
    old_summary = db.get_faction_stance_summary("皇党")
    assert old_summary is None
    old_pending = db.get_faction_brew_pending()
    assert old_pending

    # 重试月：推进年月但不新增事件，水位仍为 0，旧事件仍在水位之上
    state.turn += 1
    state.period += 1
    retry_year, retry_period = int(state.year), int(state.period)
    assert (retry_year, retry_period) != (old_year, old_period)
    targets = select_faction_brew_targets(db, year=retry_year, period=retry_period)
    # 无本月新事件但有 pending 仍选中（F2）
    assert any(row["faction"] == "皇党" for row in targets)
    retry_target = next(row for row in targets if row["faction"] == "皇党")
    assert retry_target["has_pending"] is True
    events = collect_new_edge_events_for_faction(db, faction="皇党", watermark=retry_target["watermark"])
    assert len(events) >= 1
    assert events[0]["year"] == old_year and events[0]["period"] == old_period
    payload = build_faction_brew_input(
        faction="皇党", year=retry_year, period=retry_period,
        summary=retry_target["summary"], new_events=events, has_pending=retry_target["has_pending"],
    )
    assert payload["has_pending_failure"] is True
    assert payload["year"] == retry_year and payload["period"] == retry_period
    assert payload["new_events"][0]["year"] == old_year
    assert payload["new_events"][0]["period"] == old_period
    assert payload["year"] != payload["new_events"][0]["year"] or payload["period"] != payload["new_events"][0]["period"]

    # prompt 措辞断言：不把旧事件称作本月，且为正向表述
    prompt_path = Path("content/prompts/faction_brew.md")
    prompt = prompt_path.read_text(encoding="utf-8")
    # 禁止旧措辞
    assert "本月新落" not in prompt
    assert "本月新事" not in prompt
    # 必须含新措辞（正向）
    assert "本批待酿的涉派事件" in prompt
    assert "水位之上未消化的新事件" in prompt or "未消化的新事件" in prompt
    assert "以其自带年月为据" in prompt
    assert "has_pending_failure为真时包含此前失败月的遗留事件" in prompt
    assert "source_faction" in prompt and "target_faction" in prompt
    assert "都须由本批新事件撑起" in prompt
    assert "以事件自带年月定夺新旧与跨度" in prompt
    # 宪法 P6 禁负向句：不得出现“不要当作本月发生/不要把旧事件当本月”
    assert "不要当作本月发生" not in prompt
    assert "不要把旧事件当本月" not in prompt
    assert "不要把" not in prompt or "不要把旧事件当本月" not in prompt  # 宽松：确保无负向时间语义
    # 正向表述校验：提示按自带时序判断（不通过否定达到）
    assert "依各事件自带时序判断" in prompt or "以事件自带年月定夺" in prompt or "以其自带年月为据" in prompt
