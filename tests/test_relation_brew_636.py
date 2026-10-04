"""#636 关系摘要层 S5：两段式存储＋月末增量重酿腿。

验收锚（冻结票面＋庭裁 r1-r4）：
- TD-2 奠基段永存：连续多轮重酿奠基段字节不丢不改。
- TD-3／庭裁 r3③ 无事不变：既无新事件又无 pending 的月份字节不变、零重酿调用。
- TD-4 翻转可回溯：重酿输入必含新边事件。
- TD-5／庭裁 r1 F1 失败月进持久 pending-backlog，下月补酿。
- 庭裁 r3 F1 三条故障注入机械验收（①②③）。
- 庭裁 r3/r4 F2 超长 fixture（B×436＝32,700 字节，sha256 冻结）经真实酿制
  持久化链路写入→读回字节原样。
"""

from __future__ import annotations

from types import SimpleNamespace
import httpx
import json

import pytest
from openai import APIConnectionError, APITimeoutError

from ming_sim.faction_brew import STANCE_KEY, VIEW_FACTION_STANCE
from ming_sim.exceptions import LLMUnavailable
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    MonthEndRelationBrewLeg,
    RECENT_KEY,
    build_brew_input,
    merge_founding_segment,
    relation_dimension,
)
from ming_sim.relations import EMPEROR_NODE


@pytest.mark.parametrize("error_type", [APITimeoutError, APIConnectionError])
def test_provider_fault_becomes_typed_brew_failure(monkeypatch, error_type):
    """生产调用缝仅把已知 provider 故障译成声明类型，保留原始 cause。"""
    from ming_sim.mechanical_tail import _brew_fn_for_session

    fault = error_type(request=httpx.Request("POST", "https://llm.invalid/v1"))
    monkeypatch.setattr("ming_sim.agents.create_relation_brew_agent", lambda *_a: object())
    def fail(*_a, **_kw):
        raise fault
    monkeypatch.setattr("ming_sim.agents.run_agent_text", fail)
    brew = _brew_fn_for_session(SimpleNamespace(llm_config=object(), agno_db=None))
    with pytest.raises(LLMUnavailable) as caught:
        brew(json.dumps({"source": "甲", "target": "乙"}))
    assert caught.value.__cause__ is fault


def _add_edge(db, state, *, source, target, kind, context, origin):
    return db.record_relation_edge_event(
        source=source, target=target, event_kind=kind, context=context,
        origin=origin, turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )


def _brew_fn_factory(calls):
    """确定性假酿制手：记录每次收到的 payload，按条目身份分队列脚本化输出。

    #637 同批双契约：关系工作项按序弹 outputs（原语义不变）；派系工作项按序弹
    stances、未备则用默认合法态势产出——批内派系腿静默成功，不劫持关系脚本、
    也不留派系 pending 噪声污染后续月份的选中判据。"""

    def _brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        calls.append(payload)
        if payload.get("view") == VIEW_FACTION_STANCE:
            stances = getattr(_brew, "stances", None)
            script = (
                dict(stances.pop(0)) if stances else {STANCE_KEY: "派系态势重酿。"}
            )
        else:
            outputs = getattr(_brew, "outputs", None)
            script = outputs.pop(0) if outputs else {
                FOUNDINGS_KEY: [], RECENT_KEY: "无事近况。",
            }
        return json.dumps(script, ensure_ascii=False)

    return _brew


def _script(foundings=None, recent="近况重酿。"):
    return {FOUNDINGS_KEY: list(foundings or []), RECENT_KEY: recent}


# ---------------------------------------------------------------- TD-2 奠基段永存


# ------------------------------------------------- TD-3／庭裁 r3③ 无事不变


# ------------------------------------------------------- TD-4 翻转可回溯


# --------------------------------- TD-5／庭裁 r1 F1 失败月 pending-backlog

def test_failed_month_degrades_to_pending_and_rebrews_next_month(game):
    db, state, _ = game
    failed_context = "温体仁当殿讦周延儒。"
    failed_id = _add_edge(
        db, state, source="温体仁", target="周延儒", kind="结怨",
        context=failed_context, origin="audience:turn-1",
    )

    # 真 LLM 单条失败（声明类型 LLMUnavailable）→ 降级留痕；程序错类不走此路。
    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")

    leg = MonthEndRelationBrewLeg(db, state, failing_brew, parallel=False)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()
    assert all(isinstance(error, LLMUnavailable) for _, _, error in leg.outcomes)
    # 同批新事实：温/周均皇党 → 关系对＋皇党，双双降级。
    assert report["selected"] == 2 and report["degraded"]

    # 保旧摘要（本就无摘要）、事件不丢、pending 持久在册。
    assert db.get_relation_summary("温体仁", "周延儒") is None
    assert db.get_relation_edge_events(source="温体仁", target="周延儒")
    pending = db.get_relation_brew_pending()
    assert [(row["source"], row["target"]) for row in pending] == [("温体仁", "周延儒")]

    # 次月无新事件，仍因 pending 被选中；成功后 pending 清除、摘要落定。
    # #642：失败月事件在次月 payload 双桶并集中恰一次，且落 new 不落 prior。
    state.turn += 1
    state.period += 1
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="温周结怨，朝堂侧目。")]
    leg = MonthEndRelationBrewLeg(db, state, brew_fn, parallel=False)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()

    assert report["selected"] == 2 and len(report["brewed"]) == 2
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls and relation_calls[0]["has_pending_failure"] is True
    payload = relation_calls[0]
    new_hits = [e for e in payload["new_events"] if e["origin"] == "audience:turn-1"]
    prior_hits = [e for e in payload["prior_events"] if e["origin"] == "audience:turn-1"]
    assert len(new_hits) + len(prior_hits) == 1
    assert len(new_hits) == 1 and prior_hits == []
    assert db.get_relation_brew_pending() == []
    summary = db.get_relation_summary("温体仁", "周延儒")
    assert summary["recent_segment"] == "温周结怨，朝堂侧目。"
    assert summary["dimension"] == "大臣"
    assert int(summary["last_event_id"]) >= int(failed_id)


# ---------------- #642 锚④：build_brew_input 只投影 prior 字段（全序/筛选归 read 缝）

def test_build_brew_input_projects_prior_event_fields():
    """brew 侧只锁 prior_events 字段投影与空列表；全量有序/和解归 read 缝主干。"""
    prior = [{
        "id": 9, "event_kind": "知遇", "context": "越次一召原句。",
        "origin": "seed:founding", "year": 1628, "period": 11,
    }]
    payload = build_brew_input(
        source=EMPEROR_NODE, target="杨嗣昌", dimension="君臣",
        year=1635, period=6, summary=None, new_events=[],
        has_pending=False, prior_events=prior,
    )
    assert payload["prior_events"] == [{
        "event_kind": "知遇", "context": "越次一召原句。",
        "origin": "seed:founding", "year": 1628, "period": 11,
    }]
    assert "id" not in payload["prior_events"][0]
    assert build_brew_input(
        source="甲", target="乙", dimension="大臣",
        year=1635, period=6, summary=None, new_events=[],
        has_pending=True, prior_events=[],
    )["prior_events"] == []


def test_prepare_attaches_prior_events_only_via_history_seam(game, monkeypatch):
    """生产装配：prepare→build_brew_input 经历史读缝取 prior；与 new 互斥。

    先成功酿出水位，再加次月新事件——已消化旧事只在 prior，本批新事只在 new。
    """
    db, state, _ = game
    source, target = EMPEROR_NODE, "杨嗣昌"
    prior_context = "越次一召原句。"
    # 严格早于开局年月（1627/10）的奠基原句，水位推进后才能进 prior_events。
    prior_id = db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context=prior_context, origin="seed:founding:yueci",
        turn=0, year=1626, period=6,
    )
    prior_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (prior_id,),
    ).fetchone()["origin"]
    _add_edge(db, state, source=source, target=target, kind="知遇",
              context="首月知遇。", origin="audience:month-1")
    brew_fn = _brew_fn_factory([])
    brew_fn.outputs = [_script(recent="首月近况。")]
    leg = MonthEndRelationBrewLeg(db, state, brew_fn, parallel=False)
    assert leg.prepare()
    leg.brew()
    leg.persist()
    assert db.get_relation_summary(source, target) is not None

    # 次月新事件：prior 经历史读缝、与 new 互斥、已消化旧事只在 prior。
    state.turn += 1
    state.period += 1
    new_context = "次月新知遇。"
    new_id = _add_edge(db, state, source=source, target=target, kind="知遇",
                       context=new_context, origin="audience:month-2")
    new_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (new_id,),
    ).fetchone()["origin"]

    import ming_sim.relation_brew as brew_mod
    import ming_sim.relation_read as read_mod
    seen = []
    real = read_mod.load_relation_history_before

    def spy(db_, *, source, target, before_year, before_period):
        seen.append((source, target, before_year, before_period))
        return real(
            db_, source=source, target=target,
            before_year=before_year, before_period=before_period,
        )

    monkeypatch.setattr(brew_mod, "load_relation_history_before", spy)
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="次月近况。")]
    leg = MonthEndRelationBrewLeg(db, state, brew_fn, parallel=False)
    assert leg.prepare()
    leg.brew()
    leg.persist()
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls
    payload = relation_calls[0]
    new_origins = {e["origin"] for e in payload["new_events"]}
    prior_origins = {e["origin"] for e in payload["prior_events"]}
    assert new_origin in new_origins
    assert prior_origin not in new_origins
    assert prior_origin in prior_origins
    assert new_origin not in prior_origins
    assert new_origins.isdisjoint(prior_origins)
    assert (source, target, int(state.year), int(state.period)) in seen


# --------------------------- 庭裁 r3/r4 F2 超长 fixture：32,700 字节零删改

def test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical(game):
    # Keep the long injected input; compare its before-image directly, not a
    # parallel checksum/length oracle for the same preservation contract.
    block = "崇祯边事关系账超长验收样文-Chongzhen-relation-brew-0123456789-".encode("utf-8")
    fixture = block * 436
    fixture_text = fixture.decode("utf-8")

    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召。", origin="audience:turn-1")

    def fixture_brew(payload_json: str) -> str:
        return json.dumps(
            {FOUNDINGS_KEY: [], RECENT_KEY: fixture_text}, ensure_ascii=False
        )

    # 经真实酿制持久化链路（MonthEndRelationBrewLeg.prepare/brew/persist
    # → apply_relation_brew_result）写入→读回：字节原样，全链无截断无删改。
    # 已删 run_month_end_relation_brew 不恢复；确定性 parallel=False。
    leg = MonthEndRelationBrewLeg(db, state, fixture_brew, parallel=False)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()
    assert len(report["brewed"]) == 1

    stored = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")["recent_segment"]
    assert stored.encode("utf-8") == fixture


# --------------------------------------------- P5：批内条目并行不串行


# ------------------------------------------------- 「本月新增」总判据（历史水位不选旧事）


# ------------------------------------------------------- 奠基段拼装机械语义

def test_merge_founding_segment_append_only_and_dedup():
    assert merge_founding_segment("", ["甲句。", "乙句。"]) == "甲句。\n乙句。"
    assert merge_founding_segment("甲句。", ["甲句。", "丙句。"]) == "甲句。\n丙句。"
    assert merge_founding_segment("甲句。", []) == "甲句。"
    # 空字符串条目是结构空操作；空白条目是合法字符串，逐字保留不去除。
    assert merge_founding_segment("甲句。", [""]) == "甲句。"
    assert merge_founding_segment("甲句。", ["  "]) == "甲句。\n  "


def test_merge_founding_segment_preserves_bytes_exactly():
    # P6/ADR 0142 零删改：旧段空行与末尾换行逐字保留，新句只做结构追加。
    old = "甲句。\n\n乙句。\n"
    assert merge_founding_segment(old, ["丙句。"]) == old + "\n丙句。"
    assert merge_founding_segment(old, []) == old
    # 新字符串逐字保留：首尾空白不剥。
    assert merge_founding_segment("", ["  句前空格。  "]) == "  句前空格。  "
    assert merge_founding_segment("甲句。", [" 甲句。 "]) == "甲句。\n 甲句。 "
    # 严格字节相等去重：仅逐字全等才跳过；近似串（多空格/带后缀）不吞。
    assert merge_founding_segment("甲句。", ["甲句。", "甲句。", "甲句 "]) == "甲句。\n甲句 "
    # 补酿不重复记账只在严格字节全等时成立：整段原样重报（含多行句）逐字全等→跳过。
    merged = merge_founding_segment("", ["甲句。", "乙句。\n乙二句。"])
    assert merged == "甲句。\n乙句。\n乙二句。"
    assert merge_founding_segment(merged, [merged]) == merged


def test_merge_founding_segment_exact_old_entry_re_report_appended_verbatim():
    """r5：跨轮去重收窄——只有「候选与整个旧段全等」与「同批候选间全等」跳过；
    旧段内某个精确历史条目被再次报出→如实逐字追加（有界重复噪声，酿制读面
    自行消化）；禁止恢复任何条目级拆解去重。"""
    merged = merge_founding_segment("", ["甲句。", "乙句。\n乙二句。"])
    assert merge_founding_segment(merged, ["甲句。", "乙句。\n乙二句。"]) == (
        merged + "\n甲句。\n乙句。\n乙二句。"
    )
    # 同批候选间全等仍去重；候选与整个旧段全等仍跳过（补酿整段重报不重复记账）。
    assert merge_founding_segment(merged, [merged]) == merged


def test_merge_founding_segment_never_infers_by_lines():
    """判词类①机械反例（冻结）：按行拆分＋集合推断会把整段候选误删。

    旧段 '甲\\n中\\n乙' 配候选 '甲\\n乙'：候选的每一行各自都在旧段内，旧的行集合
    推断据此把整条候选吞掉——零删改宪法下候选必须完整逐字追加。"""
    assert merge_founding_segment("甲\n中\n乙", ["甲\n乙"]) == "甲\n中\n乙\n甲\n乙"
    # 多行候选即使每一行都已在段内，也整条逐字追加（不拆行不推断）。
    assert merge_founding_segment("甲句。", ["甲句。\n甲句二。"]) == "甲句。\n甲句。\n甲句二。"


# ------- 判词类③ fail-loud 异常边界：DB/schema/程序错误响亮，仅 LLM 单条降级


def test_relation_dimension_marks_emperor_edges():
    assert relation_dimension(EMPEROR_NODE, "杨嗣昌") == "君臣"
    assert relation_dimension("杨嗣昌", EMPEROR_NODE) == "君臣"
    assert relation_dimension("毕自严", "王绍徽") == "大臣"


# -------------------------------- 庭裁 Z1：畸形酿制产出严格拒收（不修补不改写）


# -------------------------------- 庭裁 Z2：删固定 max_workers=4，按批定容
