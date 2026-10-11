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

from ming_sim.exceptions import LLMUnavailable
from ming_sim.faction_brew import (
    STANCE_KEY,
    VIEW_FACTION_STANCE,
    project_character_factions,
    select_faction_brew_targets,
)
from ming_sim.relation_brew import FOUNDINGS_KEY, RECENT_KEY
from ming_sim.relations import EMPEROR_NODE
from tests.test_relation_brew_636 import run_month_end_relation_brew


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
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    # 同批：1 条关系工作项＋1 条派系工作项 → 外部 DB 可见落定。
    assert len(calls) == 2
    assert db.get_relation_summary("温体仁", "周延儒") is not None
    assert _faction_stance(db, "皇党") is not None
    assert db.get_relation_brew_pending() == []
    assert db.get_faction_brew_pending() == []



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
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    # 只剩两条关系工作项；零派系工作项。
    assert len(calls) == 2
    assert all(c.get("view") != VIEW_FACTION_STANCE for c in calls)
    assert db.get_faction_stance_summaries() == []



# ------------------------------------- 验收：事件月更新／无事月字节不变


# ------------------------- F2 pending 补酿复用 #636 接缝：恰一次


# ----------------------- 输出契约严格边界：畸形产出拒收降级保旧摘要


# ------------------------------------------- 异常边界：DB 错响亮不伪装降级

def test_faction_claim_db_error_propagates_loudly(game):
    """认领 DB 失败响亮上抛；来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    fault = sqlite3.OperationalError("派系认领库不可写")

    def boom(*args, **kwargs):
        raise fault

    db.claim_faction_brew_targets = boom
    with pytest.raises(sqlite3.OperationalError) as ei:
        run_month_end_relation_brew(db, state, _dual_brew_fn_factory([]))
    assert ei.value is fault


def test_faction_apply_db_error_propagates_loudly_not_disguised(game):
    """落定 DB 失败响亮上抛、不伪装；来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    fault = sqlite3.OperationalError("派系落定库不可写")

    def boom(*args, **kwargs):
        raise fault

    db.apply_faction_brew_result = boom
    with pytest.raises(sqlite3.OperationalError) as ei:
        run_month_end_relation_brew(db, state, _dual_brew_fn_factory([]))
    assert ei.value is fault


# ------------------------------- P5：关系与派系同批条目并行不串行

def test_relation_and_faction_items_share_single_batch_in_parallel(game):
    """同批 1 关系＋2 派系必须并行进入调用缝（P5）。"""
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")
    # 同批 3 条工作项（1 关系＋2 派系）必须并行进入调用缝。
    barrier = threading.Barrier(3)
    threads: list = []

    def parallel_brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        threads.append(threading.current_thread().name)
        barrier.wait()  # 串行实现会在第 2/3 条处超时破裂
        if payload.get("view") == VIEW_FACTION_STANCE:
            return json.dumps({STANCE_KEY: "朝局如常。"}, ensure_ascii=False)
        return json.dumps(_relation_script(recent="毕王有站台之谊。"), ensure_ascii=False)

    run_month_end_relation_brew(db, state, parallel_brew)
    assert len(set(threads)) == 3
    assert db.get_relation_summary("毕自严", "王绍徽") is not None
    assert _faction_stance(db, "皇党") is not None
    assert _faction_stance(db, "阉党") is not None



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

    with pytest.raises(LLMUnavailable):
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


def test_declared_holder_to_emperor_grudge_reaches_holder_faction_brew(game):
    """Declared holder→EMPEROR 结怨 (no auto authority_revoke write) still feeds
    that holder's faction brew; direction comes only from source/target (#1895)."""
    db, state, _content = game
    holder = _minister(db)
    projection = project_character_factions(db)
    holder_faction = projection[holder]
    origin = f"declaration:结怨|{holder}"
    _add_edge(
        db, state, source=holder, target=EMPEROR_NODE, kind="结怨",
        context="密令被收后心生不满", origin=origin,
    )

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
        if str(item["origin"]).startswith(origin)
    ]
    assert len(matching) == 1
    assert matching[0]["source"] == holder
    assert matching[0]["target"] == EMPEROR_NODE

def _faction_stance(db, faction: str):
    """Read one faction stance via live plural API (#1847 N11: no singular TEST_ONLY reader)."""
    for row in db.get_faction_stance_summaries():
        if str(row.get("faction") or "") == faction:
            return row
    return None
