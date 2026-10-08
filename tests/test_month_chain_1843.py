"""#1843：玩家过月入口走 ADR 0157 主链，不再走五模块 extractor。"""

from __future__ import annotations

import json
import threading

import pytest

import ming_sim.declaration_dispatch as declaration_dispatch
import ming_sim.decree as decree_mod
import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.session_write_queue import get_session_write_queue
from tests.month_chain_helpers import make_light_session
from tests.dossier_test_helpers import create_test_secret_order

def _forbid_extractor(monkeypatch):
    from tests.month_chain_helpers import empty_rescript_response
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", empty_rescript_response)
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

def _prepare_player_month(db, state, content, monkeypatch, *, world=None, translate=None, secret_orders_supply=None):
    """换掉世界段与转译的模型缝，返回尚未过月的 session。不含在飞屏障。"""
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text",
        world if world is not None else (lambda *_a, **_k: ""),
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment",
        translate if translate is not None else (lambda *_a, **_k: {"effects": {}}),
    )
    if secret_orders_supply is not None:
        monkeypatch.setattr(month_chain, "run_secret_orders_supply", secret_orders_supply)
    session = make_light_session(db, state, content)
    return session

def test_unforecast_edict_is_caught_up_once_and_crash_does_not_double_charge(game, monkeypatch):
    from ming_sim.exceptions import SettlementAbort

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
    with pytest.raises(SettlementAbort) as exc_info:
        session.resolve_turn(allow_empty_decree=True)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
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
    from tests.test_refugee_loop_652 import _recovery_grant, _pop
    _recovery_grant(db, state, amount=10)
    pool_before = _pop(db, "流民", "shaanxi")
    farmers_before = _pop(db, "农民", "shaanxi")
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        ('[{"title":"是否加赈","context":"c","options":[{"label":"加","hint":"h1"},{"label":"否","hint":"h2"}]}]', ref),
    )
    db.conn.commit()
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session.llm_config = object()
    monkeypatch.setattr(
        month_chain, "_run_decree_continuation_text", lambda *a, **k: "",
    )
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.awaiting is True
    assert held.advanced is False
    assert int(state.turn) == closed_turn
    assert _pop(db, "流民", "shaanxi") == pool_before
    assert any(row["title"] == "是否加赈" for row in held.decisions)

    # 历史留中回流的同一请旨仍未答，不能因案卷创建于前月越过批红。
    from ming_sim.decree_forecast import decree_ref_for_dossier
    from ming_sim.models import TurnPhase
    dossier = next(d for d in db.list_decree_dossiers() if decree_ref_for_dossier(db, d) == ref)
    db.conn.execute(
        "UPDATE decree_dossiers SET created_turn=? WHERE id=?",
        (closed_turn - 1, int(dossier["id"])),
    )
    db.conn.commit()
    # 仍停在待裁；幂等回读案头，不二跑世界段。
    held_again = session.resolve_turn(allow_empty_decree=True)
    assert held_again.awaiting is True
    assert any(row["title"] == "是否加赈" for row in held_again.decisions)
    assert int(state.turn) == closed_turn

    # 亲裁答复后清请旨，主链才能进邸报交接。
    desk_row = session.pending_decisions()[0]
    opt = desk_row["options"][0]
    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "label": opt["label"],
            "hint": opt.get("hint") or "",
        }],
        write_gate=session._write_gate,
    )
    assert not db.staged_declarations.questions_for(ref)
    assert session.state.turn_phase == TurnPhase.SETTLING.value
    waiting_gazette = session.resolve_turn(allow_empty_decree=True)
    assert waiting_gazette.stage == "gazette"
    assert int(state.turn) == closed_turn
    assert _pop(db, "流民", "shaanxi") == pool_before

    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (closed_turn, state.year, state.period, "邸报已成"),
    )
    db.conn.commit()
    advanced = session.resolve_turn(allow_empty_decree=True)
    assert advanced.advanced is True
    assert int(state.turn) == closed_turn + 1
    from ming_sim.constants import RECOVERY_PERSONS_PER_WAN
    assert _pop(db, "流民", "shaanxi") == pool_before - 10 * RECOVERY_PERSONS_PER_WAN
    assert _pop(db, "农民", "shaanxi") == farmers_before + 10 * RECOVERY_PERSONS_PER_WAN
    del pending_id

def test_player_recovery_uses_resolve_context_decree_not_ready_delta(game, monkeypatch):
    """#1846：玩家入口从 resolve_context 原诏续跑；不再存在 ready delta 落账。"""
    db, state, content = game
    turn = int(state.turn)
    decree_mod.pre_settle(state, db, content=content)
    db.save_resolve_context(
        turn, "崩溃前原诏", {},
        source="player_decree",
    )
    support = db.load_state().metrics["民心"]
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    result = session.resolve_turn(allow_empty_decree=True)

    assert result.stage == "gazette"
    assert int(state.turn) == turn
    # 无 ready delta：不得出现 metric_delta 级大跳（旧 ready 会 -40）
    assert db.load_state().metrics["民心"] > support - 40
    assert session.last_decree == "崩溃前原诏"
    ctx = db.get_resolve_context(turn)
    assert "extracted" not in ctx
    assert ctx["source"] == "player_decree"



def test_world_segment_persists_declaration_ending_with_commit(game, monkeypatch):
    db, state, content = game
    from ming_sim.applier import Provenance

    monkeypatch.setattr(
        month_translate, "translate_month_segment",
        lambda *_a, **_k: {"effects": {"emperor_fate": "suicide"}},
    )
    chain = {"world_text_ready": True, "world_text": "世界段"}
    session = make_light_session(db, state, content)

    outcome = month_chain._run_world_segment(
        session, chain, source=Provenance.system_simulation,
    )

    expected = {"status": "emperor_suicide", "summary": "崇祯帝自尽殉国，煤山一缢，大明社稷俱亡。"}
    assert outcome == expected
    assert chain["declaration_outcome"] == expected
    payload = db.get_resolve_context(int(state.turn))["simulator_payload"]
    assert payload["month_chain"]["declaration_outcome"] == expected

def test_player_entry_recovers_ending_after_interrupted_segment(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="结局承接", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending_id, ref = _stage_edict(
        db, state, minister, "禅位", "宁远补饷", -1, affair.id,
    )
    staged = db.staged_declarations.staged_for(ref)[0]
    staged.declaration["effects"] = {"emperor_fate": "abdicate"}
    db.conn.execute(
        "UPDATE staged_declarations SET declaration_json=? WHERE decree_ref=?",
        (json.dumps(staged.declaration, ensure_ascii=False), ref),
    )
    db.conn.commit()
    turn = int(state.turn)
    calls = []

    def world(*_args, **_kwargs):
        calls.append("world")
        if len(calls) == 1:
            raise RuntimeError("interrupted after decree settlement")
        return "世界段完成"

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *_a, **_k: {"effects": {}})
    session = make_light_session(db, state, content)

    from ming_sim.exceptions import SettlementAbort

    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert db.staged_declarations.is_settled(ref)
    assert caught.value.error_pack_path

    waiting = session.resolve_turn(allow_empty_decree=True)
    assert waiting.stage == "gazette"
    payload = db.get_resolve_context(turn)["simulator_payload"]
    assert payload["month_chain"]["declaration_outcome"]["status"] == "emperor_abdicate"
    assert "call_failure" not in payload["month_chain"]

    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (turn, state.year, state.period, "邸报已成"),
    )
    db.conn.commit()
    advanced = session.resolve_turn(allow_empty_decree=True)

    assert advanced.advanced is True
    assert state.ended is True
    assert state.ending_status == "emperor_abdicate"
    assert int(state.turn) == turn + 1

def test_staged_ending_is_available_inside_its_settlement_transaction(game):
    db, state, _content = game
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import (
        settle_staged_declarations_in_decree_order, stage_declaration,
    )

    stage_declaration(
        db, decree_ref="ending-decree", turn=int(state.turn),
        declaration={"effects": {"emperor_fate": "abdicate"}},
    )
    committed = {}
    settled = settle_staged_declarations_in_decree_order(
        db, state, ["ending-decree"], source=Provenance.player_decree,
        alongside=lambda ref, result: committed.update(
            ref=ref, outcome=month_chain._ending_from_dispatch_result(result),
        ),
    )

    assert "ending-decree" in settled
    assert committed["ref"] == "ending-decree"
    assert committed["outcome"]["status"] == "emperor_abdicate"
    assert db.staged_declarations.is_settled("ending-decree")

def test_failed_declaration_commit_reloads_memory_from_db(game):
    db, state, _content = game
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import (
        settle_staged_declarations_in_decree_order, stage_declaration,
    )

    before_metrics = dict(state.metrics)
    before_treasury = db.conn.execute(
        "SELECT balance FROM economy_accounts WHERE account='国库'",
    ).fetchone()["balance"]
    affair = db.affairs.open(
        name="事务回滚探针", origin="旨意", year=state.year,
        period=state.period, turn=state.turn,
    )
    decree_ref = "failed-ending-decree"
    stage_declaration(
        db, decree_ref=decree_ref, turn=int(state.turn),
        declaration={"effects": {
            "economy_moves": [{
                "origin_ref": f"affair:{affair.id}",
                "account": "国库", "delta": -25, "category": "test",
                "reason": "atomic rollback probe",
            }],
            "emperor_fate": "abdicate",
        }},
        visible_refs={"affairs": [affair.id]},
    )

    def fail_after_effects(*_args):
        assert state.metrics["国库"] == before_metrics["国库"] - 25
        raise RuntimeError("chain persistence failed")

    with pytest.raises(RuntimeError):
        settle_staged_declarations_in_decree_order(
            db, state, [decree_ref], source=Provenance.player_decree,
            alongside=fail_after_effects,
        )

    assert state.metrics == before_metrics
    assert db.conn.execute(
        "SELECT balance FROM economy_accounts WHERE account='国库'",
    ).fetchone()["balance"] == before_treasury
    assert not db.staged_declarations.is_settled(decree_ref)

def test_held_dossier_settlement_failure_retry_and_reentry_isolation(game, monkeypatch):
    db, state, content = game
    state.turn = 2
    db.save_state(state)
    from ming_sim.declaration_dispatch import (
        held_dossier_decree_ref, pending_action_decree_ref, stage_declaration,
    )
    from types import SimpleNamespace
    from ming_sim.decree_forecast import decree_ref_for_dossier
    from ming_sim.month_chain import _settle_edicts
    import ming_sim.month_chain as mc

    minister = next(iter(content.characters.values()))
    pending_id = db.stage_pending_action(
        1, kind="directive", action="拟旨",
        minister_name=minister.name,
        payload={"dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "test-issue", "text": "留中重判案卷"},
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="留中重判案卷",
        target_kind="issue", target_id="test-issue",
        pending_action_id=pending_id,
        payload={"dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "test-issue", "text": "留中重判案卷"},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='proposed', promulgation_decision='rejected', "
        "held_turn=1, rescript_pending=0 WHERE id=?",
        (dossier_id,),
    )
    db.conn.commit()

    stale_ref = pending_action_decree_ref(pending_id, 1)
    held_ref = held_dossier_decree_ref(dossier_id)

    stage_declaration(
        db, decree_ref=stale_ref, turn=1,
        declaration={}, verdict={"decision": "rejected"},
    )
    stage_declaration(
        db, decree_ref=held_ref, turn=2,
        declaration={"effects": {"economy_moves": []}},
        verdict={"decision": "promulgated"},
        visible_refs={"dossiers": [dossier_id]},
    )

    sess = SimpleNamespace(
        db=db, state=state, llm_config=None, agno_db=None, content=content,
    )

    chain = {}
    # 首次结算失败：暂存保持未落账，旧打回暂存不被破坏
    import ming_sim.declaration_dispatch as dd
    real_settle = dd.settle_staged_declarations_in_decree_order
    fail_once = True

    def fail_first(*args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("transient settlement crash")
        return real_settle(*args, **kwargs)

    monkeypatch.setattr(dd, "settle_staged_declarations_in_decree_order", fail_first)

    with pytest.raises(RuntimeError):
        _settle_edicts(sess, chain=chain)

    assert not db.staged_declarations.is_settled(held_ref)
    assert not db.staged_declarations.is_settled(stale_ref)

    # 结算失败重试：以 held_ref 身份续跑并成功落账
    _settle_edicts(sess, chain=chain)
    assert db.staged_declarations.is_settled(held_ref)
    assert not db.staged_declarations.is_settled(stale_ref)
    assert db.get_decree_dossier(dossier_id)["promulgation_decision"] == "promulgated"

    # 再次进入月链结算：保持 held_ref 案卷身份，旧 pending-action 不被冒名结算
    _settle_edicts(sess, chain=chain)
    assert db.staged_declarations.is_settled(held_ref)
    assert not db.staged_declarations.is_settled(stale_ref)
    dossier = db.get_decree_dossier(dossier_id)
    assert decree_ref_for_dossier(db, dossier) == held_ref




