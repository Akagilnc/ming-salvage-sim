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
from ming_sim.relation_brew import FOUNDINGS_KEY, RECENT_KEY
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



# ------------------------------------- 验收：事件月更新／无事月字节不变


# ------------------------- F2 pending 补酿复用 #636 接缝：恰一次


# ----------------------- 输出契约严格边界：畸形产出拒收降级保旧摘要


# ------------------------------------------- 异常边界：DB 错响亮不伪装降级



# ------------------------------- P5：关系与派系同批条目并行不串行


# -------------------- F3 零写观察面：factions 数值列负向断言（机械）


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
            # Separate structured identities must preserve the source rows,
            # regardless of punctuation that may legitimately occur in names.
            assert projected["source"] == row["source"]
            assert projected["target"] == row["target"]

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
