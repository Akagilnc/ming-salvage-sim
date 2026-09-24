"""#1843：玩家过月入口走 ADR 0157 主链，不再走五模块 extractor。"""

from __future__ import annotations

import threading

import ming_sim.declaration_dispatch as declaration_dispatch
import ming_sim.decree as decree_mod
import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
import ming_sim.simulation as simulation
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.session_write_queue import get_session_write_queue
from tests.settlement_seam_helpers import make_light_session


def _forbid_extractor(monkeypatch):
    assert not hasattr(decree_mod, "extract_scores_by_modules_with_agno")
    assert not hasattr(simulation, "extract_scores_by_modules_with_agno")
    assert not hasattr(simulation, "EXTRACTION_MODULES")
    monkeypatch.setattr(
        "ming_sim.session.write_decree_with_agno", lambda *_a, **_k: "诏",
    )


def _stage_edict(db, state, minister, text, category, delta, affair_id):
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-chain", "actor": minister, "mode": "ordinary",
            "text": text,
        },
    )
    ref = pending_action_decree_ref(pending_id, 1)
    db.staged_declarations.stage(
        decree_ref=ref,
        declaration={"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair_id}", "account": "国库", "delta": delta,
            "category": category, "reason": text,
        }]}},
        turn=int(state.turn),
        verdict={"decision": "promulgated"},
        forecast_text=f"预推不可见:{text}",
        visible_refs={"affairs": [affair_id], "issues": [], "secret_orders": []},
    )
    return pending_id, ref


def _categories(db):
    return [
        str(row["category"]) for row in db.conn.execute(
            "SELECT category, delta FROM economy_ledger ORDER BY id",
        ) if str(row["category"]) in {"宁远补饷", "陕西赈灾", "大凌河"}
    ]


def test_player_month_entry_settles_prepushed_edicts_then_world_once(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="过月可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    _stage_edict(db, state, minister, "大凌河", "大凌河", -10**12, affair.id)
    state.metrics["国库"] = 500000
    db.save_state(state)
    closed_turn = int(state.turn)
    sources_before = {
        str(row[0]) for row in db.conn.execute("SELECT source_id FROM character_knowledge_sources")
    }
    events = []
    world_calls = []
    translate_calls = []

    def world(db_, state_, llm_config, agno_db=None, cheat_directive=""):
        del llm_config, agno_db, cheat_directive
        from ming_sim.materials import prepare_world_materials, release_material_tree
        prepared = prepare_world_materials(db_, state_)
        try:
            world_calls.append({
                "treasury": int(state_.metrics["国库"]),
                "opening": prepared.opening,
                "edicts": _categories(db_),
            })
        finally:
            release_material_tree(prepared.root)
        return "世界段只推演一次。"

    def translate(*_a, **_k):
        translate_calls.append(1)
        return {"effects": {}}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    queue = get_session_write_queue(session)
    ticket = queue.claim_if_absent([("mechanical-tail", closed_turn)])[0]
    joined = {}

    def finish_prior():
        joined["done"] = True
        queue.complete(ticket)

    threading.Thread(target=finish_prior).start()
    result = session.resolve_turn(allow_empty_decree=True, on_event=lambda kind, data: events.append((kind, data)))

    assert joined.get("done") is True
    assert world_calls and world_calls[0]["edicts"][:2] == ["宁远补饷", "陕西赈灾"]
    ledger = list(db.conn.execute(
        "SELECT category, delta FROM economy_ledger WHERE category IN ('宁远补饷','陕西赈灾','大凌河') ORDER BY id",
    ))
    assert [str(row["category"]) for row in ledger][:2] == ["宁远补饷", "陕西赈灾"]
    assert all(int(row["delta"]) != -10**12 for row in ledger)
    assert int(state.metrics["国库"]) >= 0
    assert world_calls[0]["treasury"] == int(state.metrics["国库"])
    assert len(world_calls) == 1
    assert len(translate_calls) == 1
    assert result.advanced is False
    assert result.stage == "gazette"
    assert int(state.turn) == closed_turn
    assert not db.get_turn_report(closed_turn)
    assert sources_before == {
        str(row[0]) for row in db.conn.execute("SELECT source_id FROM character_knowledge_sources")
    }
    assert all("预推不可见" not in str(item) and "世界段只推演一次" not in str(item) for item in events)

    session.resolve_turn(allow_empty_decree=True)
    assert len(world_calls) == 1
    assert len(translate_calls) == 1
    assert [str(row["category"]) for row in db.conn.execute(
        "SELECT category FROM economy_ledger WHERE category IN ('宁远补饷','陕西赈灾','大凌河') ORDER BY id",
    )] == [str(row["category"]) for row in ledger]


def test_unforecast_edict_is_caught_up_once_and_crash_does_not_double_charge(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="补跑可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    first_id, first_ref = _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    second_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-chain", "actor": minister, "mode": "midzhi",
            "text": "大凌河",
        },
    )
    second_ref = pending_action_decree_ref(second_id, 1)
    state.metrics["国库"] = 500000
    db.save_state(state)
    produced = []

    def product(session, snapshot):
        produced.append(snapshot["decree_ref"])
        return {
            "verdict": {"decision": "promulgated"},
            "declaration": {"effects": {"economy_moves": [{
                "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -1,
                "category": "大凌河", "reason": "补跑",
            }]}},
            "questions": None,
            "forecast_text": "补跑不可见",
            "visible_refs": snapshot.get("visible_refs"),
        }

    real_settle = declaration_dispatch.settle_staged_declarations_in_decree_order
    armed = {"fail": True}

    def flaky(db_, state_, refs, **kwargs):
        if armed["fail"] and refs == [second_ref]:
            armed["fail"] = False
            raise RuntimeError("过月中断")
        return real_settle(db_, state_, refs, **kwargs)

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr("ming_sim.decree_forecast.produce_forecast_product", product)
    monkeypatch.setattr(declaration_dispatch, "settle_staged_declarations_in_decree_order", flaky)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    try:
        session.resolve_turn(allow_empty_decree=True)
    except RuntimeError as exc:
        assert "过月中断" in str(exc)
    assert db.staged_declarations.is_settled(first_ref)
    assert not db.staged_declarations.is_settled(second_ref)
    first_rows = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0]
    session.resolve_turn(allow_empty_decree=True)
    assert produced == [second_ref]
    assert db.staged_declarations.is_settled(second_ref)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0] == first_rows
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='大凌河'",
    ).fetchone()[0] == 1
    del first_id


def test_questions_hold_rescript_and_gazette_is_required_before_advance(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="请旨可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    pending_id, ref = _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        ('[{"title":"是否加赈"}]', ref),
    )
    db.conn.commit()
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.advanced is False
    assert int(state.turn) == closed_turn

    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=NULL WHERE decree_ref=?",
        (ref,),
    )
    db.conn.commit()
    waiting_gazette = session.resolve_turn(allow_empty_decree=True)
    assert waiting_gazette.stage == "gazette"
    assert int(state.turn) == closed_turn

    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (closed_turn, state.year, state.period, "邸报已成"),
    )
    db.conn.commit()
    advanced = session.resolve_turn(allow_empty_decree=True)
    assert advanced.advanced is True
    assert int(state.turn) == closed_turn + 1
    del pending_id
