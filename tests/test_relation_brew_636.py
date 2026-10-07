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

import json
import sqlite3
import threading

import pytest

from ming_sim.faction_brew import STANCE_KEY, VIEW_FACTION_STANCE
from ming_sim.exceptions import LLMUnavailable
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    RECENT_KEY,
    MonthEndRelationBrewLeg,)
from ming_sim.relations import EMPEROR_NODE


def run_month_end_relation_brew(db, state, brew_fn, *, parallel=True, settled_turn=None, settled_year=None, settled_period=None):
    """Test helper: drive the live Leg three-phase entry (no retired convenience wrapper)."""
    leg = MonthEndRelationBrewLeg(
        db, state, brew_fn,
        settled_turn=settled_turn,
        settled_year=settled_year,
        settled_period=settled_period,
        parallel=parallel,
    )
    if not leg.prepare():
        return leg.report
    leg.brew()
    return leg.persist()


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
    run_month_end_relation_brew(db, state, brew_fn)
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
    run_month_end_relation_brew(db, state, brew_fn)
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


# --------------------------------------------- P5：批内条目并行不串行


# ------------------------------------------------- 「本月新增」总判据（历史水位不选旧事）


# ------- 判词类③ fail-loud 异常边界：DB/schema/程序错误响亮，仅 LLM 单条降级



# -------------------------------- 庭裁 Z1：畸形酿制产出严格拒收（不修补不改写）




# -------------------------------- 庭裁 Z2：删固定 max_workers=4，按批定容
