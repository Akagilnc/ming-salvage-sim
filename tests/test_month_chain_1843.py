"""#1843：玩家过月入口走 ADR 0157 主链，不再走五模块 extractor。"""

from __future__ import annotations

import threading

import pytest

import ming_sim.declaration_dispatch as declaration_dispatch
import ming_sim.decree as decree_mod
import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
import ming_sim.simulation as simulation
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.session_write_queue import get_session_write_queue
from tests.settlement_seam_helpers import make_light_session
from tests.dossier_test_helpers import create_test_secret_order


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

    # 历史留中回流的同一请旨仍未答，不能因案卷创建于前月越过批红。
    from ming_sim.decree_forecast import decree_ref_for_dossier
    dossier = next(d for d in db.list_decree_dossiers() if decree_ref_for_dossier(db, d) == ref)
    db.conn.execute(
        "UPDATE decree_dossiers SET created_turn=? WHERE id=?",
        (closed_turn - 1, int(dossier["id"])),
    )
    db.conn.commit()
    held_again = session.resolve_turn(allow_empty_decree=True)
    assert held_again.stage == "rescript"
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


def test_player_recovery_discards_legacy_ready_delta(game, monkeypatch):
    """旧 extractor ready 不能在玩家入口落账；原诏及来源仍用于新月链续跑。"""
    db, state, content = game
    turn = int(state.turn)
    decree_mod.pre_settle(state, db, content=content)
    db.save_resolve_context(
        turn, "崩溃前原诏", "旧叙事", {},
        extracted={"metric_delta": {"民心": -40}}, source="player_decree",
    )
    support = db.load_state().metrics["民心"]
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    result = session.resolve_turn(allow_empty_decree=True)

    assert result.stage == "gazette"
    assert int(state.turn) == turn
    assert db.load_state().metrics["民心"] > support - 40
    assert session.last_decree == "崩溃前原诏"
    ctx = db.get_resolve_context(turn)
    assert ctx["extracted"] is None
    assert ctx["source"] == "player_decree"


def test_finish_rescript_phase2_stays_settling_until_advanced(game, monkeypatch):
    """批红续跑入口在主链停住时不得把回合标成已推进。"""
    from ming_sim.models import TurnPhase

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="批红未推进", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending_id, ref = _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        ('[{"title":"是否加赈"}]', ref),
    )
    db.save_resolve_context(state.turn, "赈灾诏", "", {})
    db.conn.commit()
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session.state.turn_phase = TurnPhase.SETTLING.value
    session.finish_rescript_phase2({"ready_replay": True}, {})
    assert int(session.state.turn) == closed_turn
    assert session.state.turn_phase == TurnPhase.SETTLING.value


def test_missing_world_model_stops_before_world_commit(game, monkeypatch):
    from ming_sim.exceptions import LLMUnavailable

    db, state, content = game
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    session = make_light_session(db, state, content)
    with pytest.raises(LLMUnavailable):
        session.resolve_turn(allow_empty_decree=True)
    assert int(state.turn) == turn
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    assert session.resolve_turn(allow_empty_decree=True).stage == "gazette"
    assert int(state.turn) == turn


def test_month_drift_settles_due_secret_and_records_inertia_rejection(game, monkeypatch, tmp_path):
    """邸报前确定性尾：到期密令结案，自然结案的容忍拒收留痕。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    turn = int(state.turn)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = create_test_secret_order(
        db, state, actor, "密查", "核验田亩", [], deadline_months=1,
    )
    db.conn.execute("UPDATE secret_orders SET due_turn=? WHERE id=?", (turn, order_id))
    army_id = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]
    db.insert_issue(
        state, kind="initiative", title="惯性留痕", origin_kind="decree",
        origin_ref="", bar_value=99, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=5, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, cancellable="decree", cancel_cost={},
        effect_on_resolve={"army_delta": {army_id: {"origin_ref": "盘面自发", "士气大振": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
    )
    db.conn.commit()
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    assert session.resolve_turn(allow_empty_decree=True).stage == "gazette"
    assert db.get_secret_order(order_id)["status"] == "failed"
    rows = db.conn.execute(
        "SELECT section FROM rejection_reports WHERE turn=? AND section='issue_inertia.entity_rejections'",
        (turn,),
    ).fetchall()
    assert len(rows) == 1
    session.resolve_turn(allow_empty_decree=True)
    assert db.get_secret_order(order_id)["status"] == "failed"
    assert len(db.conn.execute(
        "SELECT id FROM rejection_reports WHERE turn=? AND section='issue_inertia.entity_rejections'",
        (turn,),
    ).fetchall()) == 1


def test_world_segment_reads_material_directory(game, monkeypatch):
    """世界段复用列目录／读文件与 CLI materials_dir，不只把 opening 交进上下文。"""
    from pathlib import Path

    import ming_sim.agents as agents_mod
    from ming_sim.agents import bind_content
    from ming_sim.models import LLMConfig

    db, state, content = game
    bind_content(content)
    seen = []

    def capture(agent, _message, **_kwargs):
        tools = {tool.__name__: tool for tool in agent.tools}
        listing = tools["list_materials"]("")
        index = tools["read_material"]("INDEX.txt")
        has_dir = hasattr(agent.model, "materials_dir")
        materials_dir = getattr(agent.model, "materials_dir", "")
        seen.append({
            "listing": listing,
            "index": index,
            "has_dir": has_dir,
            "dir_has_index": bool(materials_dir) and (Path(materials_dir) / "INDEX.txt").is_file(),
            "opening": next(part for part in agent.instructions if "盘面：" in str(part)),
        })
        return "静"

    monkeypatch.setattr(agents_mod, "run_agent_text", capture)
    api = LLMConfig(
        api_key="sk-test", base_url="https://api.example.com/v1",
        model="gpt-test", channel="api",
    )
    assert month_chain.run_world_segment_text(db, state, api) == "静"
    assert "INDEX.txt" in seen[0]["listing"].splitlines()
    assert seen[0]["index"].strip()
    assert seen[0]["has_dir"] is False
    assert "盘面：" in seen[0]["opening"]
    # 目录里至少有一份不在开场最小集里的材料。
    extra = next(
        line for line in seen[0]["listing"].splitlines()
        if line and line != "INDEX.txt" and line not in seen[0]["opening"]
    )
    assert extra

    cli = LLMConfig(api_key="", base_url="", model="", channel="cli", cli_runner="agy")
    assert month_chain.run_world_segment_text(db, state, cli) == "静"
    assert seen[1]["has_dir"] is True
    assert seen[1]["dir_has_index"] is True
    assert seen[1]["index"].strip()
