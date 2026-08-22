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
        for projected, row in zip(payload["new_events"], events):
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
