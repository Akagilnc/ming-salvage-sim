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


def test_prepare_attaches_prior_events_only_via_history_seam(game):
    """生产装配：prepare→build_brew_input 历史 prior 与本批 new 互斥。

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
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="召见。", origin="audience:program-failure")
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
    assert next(item for item in calls if "source" in item)["has_pending_failure"] is True


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
