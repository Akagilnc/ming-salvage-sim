"""#636：真实关系重酿入口的备料、保真和失败边界。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ming_sim.faction_brew import STANCE_KEY, VIEW_FACTION_STANCE
from ming_sim.exceptions import LLMUnavailable
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    RECENT_KEY,
    MonthEndRelationBrewLeg,
)
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

@pytest.mark.parametrize("first_text,next_text,expected", [
    ("越次一召，擢杨嗣昌于五品郎中。", "", "越次一召，擢杨嗣昌于五品郎中。"),
    ("  句前空格。  ", "  句前空格。  ", "  句前空格。  "),
    ("甲句。", "  ", "甲句。\n  "),
    ("甲句。", " 甲句。 ", "甲句。\n 甲句。 "),
    ("甲句。\n\n乙句。\n", "丙句。", "甲句。\n\n乙句。\n\n丙句。"),
    ("甲句。\n乙句。\n乙二句。", "乙句。\n乙二句。", "甲句。\n乙句。\n乙二句。\n乙句。\n乙二句。"),
    ("甲\n中\n乙", "甲\n乙", "甲\n中\n乙\n甲\n乙"),
])
def test_founding_segment_survives_consecutive_brews_byte_identical(game, first_text, next_text, expected):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召，擢杨嗣昌于五品郎中。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(foundings=[first_text], recent="杨嗣昌蒙知遇之恩。")]

    report = run_month_end_relation_brew(db, state, brew_fn)
    # 同批新事实：杨嗣昌党籍投影皇党（factions 表现存）→ 关系对＋皇党两个工作项。
    assert report["selected"] == 2 and len(report["brewed"]) == 2

    first = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert first["dimension"] == "君臣"
    assert first["founding_segment"] == first_text

    # 次月：新边事件入账（先落事件、后在本月末酿——与生产同序），酿制手不再报
    # 奠基句——奠基段字节不丢不改。次月无新事件的关系不因历史旧事件被选中。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="兑现所托",
              context="杨嗣昌复命，所托之事办结。", origin="audience:turn-2")
    brew_fn.outputs = [_script(foundings=[next_text], recent="杨嗣昌所托办结，恩遇正浓。")]
    run_month_end_relation_brew(db, state, brew_fn)

    second = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert second["founding_segment"] == expected
    assert second["recent_segment"] == "杨嗣昌所托办结，恩遇正浓。"

    # 第三月：酿制手重复报同一奠基句也不重复入段（补酿不重复记账）。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="辜负",
              context="杨嗣昌所请被驳。", origin="audience:turn-3")
    brew_fn.outputs = [_script(foundings=[expected, expected], recent="杨嗣昌所请被驳，渐生离心。")]
    run_month_end_relation_brew(db, state, brew_fn)
    third = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert third["founding_segment"] == second["founding_segment"]


# ------------------------------------------------- TD-3／庭裁 r3③ 无事不变

def test_no_new_events_and_no_pending_month_bytes_unchanged_zero_brews(game):
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="毕王有站台之谊。")]
    run_month_end_relation_brew(db, state, brew_fn)
    before = db.get_relation_summary("毕自严", "王绍徽")

    # 成功月重跑结算（跨月推进、无新事件、无 pending）：字节不变、零重酿调用。
    calls.clear()
    state.turn += 1
    state.period += 1
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 0
    assert calls == []
    after = db.get_relation_summary("毕自严", "王绍徽")
    assert after["recent_segment"] == before["recent_segment"]
    assert after["founding_segment"] == before["founding_segment"]


# ------------------------------------------------------- TD-4 翻转可回溯

def test_flip_brew_input_must_contain_new_edge_events(game):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="知遇",
              context="钱谦益蒙召对，简拔入朝。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="钱谦益蒙知遇。")]
    run_month_end_month = run_month_end_relation_brew(db, state, brew_fn)
    # 同批新事实：钱谦益党籍投影东林 → 关系对＋东林。
    assert len(run_month_end_month["brewed"]) == 2

    # 语义翻转月：新辜负事件入账后重酿，酿制输入必含该新事件。
    flip_id = _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="辜负",
                        context="钱谦益哭谏被拒，圣眷转衰。", origin="audience:turn-2")
    calls.clear()
    brew_fn.outputs = [_script(recent="钱谦益因哭谏被拒而离心。")]
    run_month_end_relation_brew(db, state, brew_fn)

    # 同批含东林派系工作项：翻转判据只辖关系腿的调用缝。
    relation_calls = [c for c in calls if "view" not in c]
    assert len(relation_calls) == 1
    payload = relation_calls[0]
    assert payload["new_events"] and payload["new_events"][0]["context"] == "钱谦益哭谏被拒，圣眷转衰。"
    assert payload["new_events"][0]["event_kind"] == "辜负"
    assert payload["recent_segment"] == "钱谦益蒙知遇。"
    summary = db.get_relation_summary(EMPEROR_NODE, "钱谦益")
    assert summary["last_event_id"] >= flip_id


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

    report = run_month_end_relation_brew(db, state, failing_brew)
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
    report = run_month_end_relation_brew(db, state, brew_fn)

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


def test_prepare_attaches_prior_events_only_via_history_seam(game, monkeypatch):
    """生产装配：prepare→build_brew_input 经历史读缝取 prior；与 new 互斥。


    先成功酿出水位，再加次月新事件——已消化旧事只在 prior，本批新事只在 new。
    """
    db, state, _ = game
    source, target = EMPEROR_NODE, "杨嗣昌"
    prior_context = "越次一召原句。"
    # Unbrewed history from the same year, previous month.
    prior_id = db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context=prior_context, origin="seed:founding:yueci",
        turn=0, year=int(state.year), period=int(state.period) - 1,
    )
    # Unbrewed history from the previous year, same month.
    db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context="前岁同月旧事。", origin="seed:founding:previous-year",
        turn=0, year=int(state.year) - 1, period=int(state.period),
    )
    prior_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (prior_id,),
    ).fetchone()["origin"]

    # 未酿历史事件没有本月新事，也没有 pending：关系及其派系均不得入选。
    calls: list = []
    assert db.get_relation_brew_pending() == []
    assert db.get_faction_brew_pending() == []
    report = run_month_end_relation_brew(db, state, _brew_fn_factory(calls))
    assert report["selected"] == 0
    assert calls == []
    assert db.get_relation_summary(source, target) is None
    assert db.get_faction_stance_summaries() == []

    _add_edge(db, state, source=source, target=target, kind="知遇",
              context="首月知遇。", origin="audience:month-1")
    brew_fn = _brew_fn_factory([])
    founding = "  越次一召原句。\n"
    brew_fn.outputs = [_script(foundings=[founding], recent="首月近况。")]
    run_month_end_relation_brew(db, state, brew_fn)
    first = db.get_relation_summary(source, target)
    assert first["founding_segment"] == founding

    # 次月新事件：prior 与 new 互斥、已消化旧事只在 prior。
    state.turn += 1
    state.period += 1
    new_context = "次月新知遇。"
    new_id = _add_edge(db, state, source=source, target=target, kind="知遇",
                       context=new_context, origin="audience:month-2")
    new_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (new_id,),
    ).fetchone()["origin"]

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

    after = db.get_relation_summary(source, target)
    assert after["founding_segment"] == first["founding_segment"]
    assert after["recent_segment"] == "次月近况。"
    state.turn += 1
    state.period += 1
    calls.clear()
    report = run_month_end_relation_brew(db, state, brew_fn)
    assert report["selected"] == 0
    assert calls == []
    assert db.get_relation_summary(source, target) == after


@pytest.mark.parametrize("seam,llm_failure", [
    ("claim_relation_brew_targets", False),
    ("apply_relation_brew_result", False),
    ("mark_relation_brew_pending", True),
])
def test_brew_persistence_faults_propagate_original_error(game, monkeypatch, seam, llm_failure):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="召见。", origin="audience:db-failure")
    fault = sqlite3.OperationalError("injected persistence failure")

    def boom(*args, **kwargs):
        raise fault

    monkeypatch.setattr(db, seam, boom)
    brew = _brew_fn_factory([])
    if llm_failure:
        def brew(_payload):
            raise LLMUnavailable("injected provider failure")
    with pytest.raises(sqlite3.OperationalError) as caught:
        run_month_end_relation_brew(db, state, brew)
    assert caught.value is fault


@pytest.mark.parametrize("error_type", [KeyError, ValueError])
def test_brew_program_error_propagates_loudly_not_degraded(game, error_type):
    db, state, _ = game
    failed_id = _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
                          context="召见。", origin="audience:program-failure")
    failed_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (failed_id,),
    ).fetchone()["origin"]
    fault = error_type("injected brew program error")

    def brew(_payload):
        raise fault

    with pytest.raises(error_type) as caught:
        run_month_end_relation_brew(db, state, brew)
    assert caught.value is fault
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        (EMPEROR_NODE, "杨嗣昌")
    ]
    state.turn += 1
    state.period += 1
    calls = []
    run_month_end_relation_brew(db, state, _brew_fn_factory(calls))
    assert db.get_relation_brew_pending() == []
    assert db.get_relation_summary(EMPEROR_NODE, "杨嗣昌") is not None
    payload = next(item for item in calls if "source" in item)
    assert payload["has_pending_failure"] is True
    assert [event["origin"] for event in payload["new_events"]].count(failed_origin) == 1
    assert failed_origin not in [event["origin"] for event in payload["prior_events"]]


@pytest.mark.parametrize("malformed", [
    json.dumps({FOUNDINGS_KEY: []}),
    json.dumps(_script(recent="first")) + json.dumps(_script(recent="second")),
    '{"' + FOUNDINGS_KEY + '": [], "' + RECENT_KEY + '": "甲\x01乙"}',
])
def test_parse_seam_value_error_degrades_single_item(game, malformed):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="召见。", origin="audience:before-bad-output")
    brew = _brew_fn_factory([])
    brew.outputs = [_script(foundings=["  奠基原句\n"], recent="  近况原句\n")]
    run_month_end_relation_brew(db, state, brew)
    before = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    state.turn += 1
    state.period += 1
    event_id = _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="辜负",
                         context="新事。", origin="audience:bad-output")
    report = run_month_end_relation_brew(db, state, lambda _payload: malformed)
    assert report["selected"] == 2
    assert report["brewed"] == []
    assert len(report["degraded"]) == report["selected"]
    assert db.get_relation_summary(EMPEROR_NODE, "杨嗣昌") == before
    assert event_id in {
        row["id"] for row in db.get_relation_edge_events(source=EMPEROR_NODE, target="杨嗣昌")
    }
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        (EMPEROR_NODE, "杨嗣昌")
    ]
