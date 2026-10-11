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

from tests.test_relation_brew_636 import _script as _relation_script

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
from tests.test_relation_brew_636 import _add_edge, run_month_end_relation_brew


def _faction_stance(db, faction: str):
    """Read one faction stance via live plural API (#1847 N11: no singular TEST_ONLY reader)."""
    for row in db.get_faction_stance_summaries():
        if str(row.get("faction") or "") == faction:
            return row
    return None


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
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    assert len(calls) == 3  # 1 关系＋2 派系
    assert db.get_relation_summary("毕自严", "王绍徽") is not None
    assert _faction_stance(db, "皇党")["stance_segment"] == "朝局如常。"
    assert _faction_stance(db, "阉党")["stance_segment"] == "朝局如常。"
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

def test_event_month_updates_stance_and_no_event_month_byte_identical(game):
    db, state, _ = game
    event_id = _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="知遇",
                         context="钱谦益蒙召对，简拔入朝。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _dual_brew_fn_factory(calls, stance="东林因钱谦益蒙召对而势涨。")
    run_month_end_relation_brew(db, state, brew_fn)

    summary = _faction_stance(db, "东林")
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
    run_month_end_relation_brew(db, state, brew_fn)
    assert calls == []
    after = _faction_stance(db, "东林")
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

    with pytest.raises(LLMUnavailable):
        run_month_end_relation_brew(db, state, failing_brew)
    # 关系与派系工作项同批同命：双双降级留痕后上抛。
    assert _faction_stance(db, "皇党") is None
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
    run_month_end_relation_brew(db, state, brew_fn)
    faction_payloads = [
        payload for payload in calls if payload.get("view") == VIEW_FACTION_STANCE
    ]
    assert len(faction_payloads) == 1
    assert faction_payloads[0]["has_pending_failure"] is True
    assert faction_payloads[0]["faction"] == "皇党"
    assert len(calls) == 2
    assert _faction_stance(db, "皇党")["stance_segment"] == (
        "皇党内因温周之隙而生嫌隙。"
    )
    assert db.get_faction_brew_pending() == []
    assert db.get_relation_brew_pending() == []

    # 再跑：既无新事件又无 pending → 零调用、字节不变（补酿恰一次的总证明）。
    state.turn += 1
    state.period += 1
    calls.clear()
    run_month_end_relation_brew(db, state, brew_fn)
    assert calls == []


# ----------------------- 输出契约严格边界：畸形产出拒收降级保旧摘要

def test_malformed_faction_output_degrades_and_keeps_old_summary_bytes(game):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _dual_brew_fn_factory(calls, stance="皇党旧文。")
    run_month_end_relation_brew(db, state, brew_fn)
    before = _faction_stance(db, "皇党")

    # 次月新涉派事件；派系腿产出缺 stance_segment（shape 违约）→ 单条降级后上抛。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="辜负",
              context="所请被驳。", origin="audience:turn-2")
    calls.clear()
    brew_fn.stances = ['{"irrelevant": 1}']
    with pytest.raises(ValueError):
        run_month_end_relation_brew(db, state, brew_fn)
    after = _faction_stance(db, "皇党")
    assert after["stance_segment"] == before["stance_segment"]  # 保旧摘要字节
    assert [row["faction"] for row in db.get_faction_brew_pending()] == ["皇党"]

    # 再下月：pending 补酿恰一次、成功落定清除。
    state.turn += 1
    state.period += 1
    calls.clear()
    brew_fn.stances = [{STANCE_KEY: "皇党因杨嗣昌被驳而渐离。"}]
    run_month_end_relation_brew(db, state, brew_fn)
    assert _faction_stance(db, "皇党")["stance_segment"] == "皇党因杨嗣昌被驳而渐离。"
    assert db.get_faction_brew_pending() == []


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

from tests.test_authority_ledger_611 import _minister

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


# ---- 送修口一负例 (a)：真实月末酿制入口的 source_faction/target_faction 与现算投影逐项相等、皇帝端 null、表外 null 且无拼接串 ----

def test_source_faction_target_faction_equals_current_projection_and_nulls_and_no_concatenation(game):
    """负例(a)：经真实月末酿制入口（外部酿制手为唯一桩）的派系输入逐条携带现算党籍投影；
    皇帝端显式 None、表外党籍显式 None；无任何拼接串（ADR 0142/P6）。"""
    db, state, _ = game
    projection = project_character_factions(db)
    # 皇帝端不在映射、表外党籍不在映射（前提校验）
    assert EMPEROR_NODE not in projection
    assert "皇太极" not in projection
    in_table = {row["name"] for row in db.conn.execute("SELECT name FROM factions").fetchall()}
    assert set(projection.values()) <= in_table

    # 三种边：皇党→阉党（双侧均在表）、皇党→皇帝（皇帝端 null）、表外(后金)→皇党（表外 null）
    _add_edge(db, state, source="温体仁", target="王绍徽", kind="结怨",
              context="温体仁当殿讦王绍徽。", origin="audience:turn-1")
    _add_edge(db, state, source="温体仁", target=EMPEROR_NODE, kind="结怨",
              context="温体仁面斥皇帝。", origin="audience:turn-1b")
    _add_edge(db, state, source="皇太极", target="温体仁", kind="结怨",
              context="皇太极讦温体仁。", origin="test:out_of_table")

    calls: list = []
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    events = [
        item
        for payload in calls if payload.get("view") == VIEW_FACTION_STANCE
        for item in payload["new_events"]
    ]
    assert events

    in_table_or_null = in_table | {None}
    for item in events:
        assert item["source_faction"] == projection.get(item["source"])
        assert item["target_faction"] == projection.get(item["target"])
        assert item["source_faction"] in in_table_or_null
        assert item["target_faction"] in in_table_or_null
        if item["source"] == EMPEROR_NODE:
            assert item["source_faction"] is None
        if item["target"] == EMPEROR_NODE:
            assert item["target_faction"] is None
    out_of_table = [item for item in events if item["origin"].startswith("test:out_of_table")]
    assert len(out_of_table) == 1
    assert out_of_table[0]["source_faction"] is None
    assert out_of_table[0]["target_faction"] == "皇党"


# ---- 送修口二负例 (b)：重试月场景，旧事件年月与重试月区分（经真实酿制 tracer）----

def test_faction_brew_prompt_retry_month_does_not_label_old_events_as_current_month(game):
    """失败留 pending 后次月补酿：真实 brew 输入的 year/period 是重试月，事件自带旧年月。"""
    db, state, _ = game
    old_year, old_period = int(state.year), int(state.period)
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-old")

    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")

    with pytest.raises(LLMUnavailable):
        run_month_end_relation_brew(db, state, failing_brew)
    assert any(row["faction"] == "皇党" for row in db.get_faction_brew_pending())

    state.turn += 1
    state.period += 1
    retry_year, retry_period = int(state.year), int(state.period)
    assert (retry_year, retry_period) != (old_year, old_period)

    calls: list = []
    run_month_end_relation_brew(db, state, _dual_brew_fn_factory(calls))
    faction_payloads = [
        payload for payload in calls if payload.get("view") == VIEW_FACTION_STANCE
    ]
    assert len(faction_payloads) == 1
    payload = faction_payloads[0]
    assert payload["has_pending_failure"] is True
    assert payload["year"] == retry_year and payload["period"] == retry_period
    assert payload["new_events"], payload
    assert payload["new_events"][0]["year"] == old_year
    assert payload["new_events"][0]["period"] == old_period
    assert (
        payload["year"] != payload["new_events"][0]["year"]
        or payload["period"] != payload["new_events"][0]["period"]
    )
    assert db.get_faction_brew_pending() == []
