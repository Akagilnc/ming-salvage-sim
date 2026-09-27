"""#1847：请旨停在问处 → 批红案头统一收口 → 答复后续推。

沿既有 HITL / pending_decisions / month_chain 接缝，不另造平行机制。
LLM 外缝可打；续推函数本身保持真实实现。
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import TurnPhase
from tests.settlement_seam_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor, _stage_edict
from tests.dossier_test_helpers import create_test_secret_order


_WORLD_WITH_QUESTION = (
    "关外告急。"
    "<<DECISION>>"
    '{"title":"是否增援宁远","context":"袁崇焕请兵","options":['
    '{"label":"准调关宁","hint":"饷银加紧"},'
    '{"label":"暂缓","hint":"先观守势"}'
    "]}"
    "<<END>>"
    "余波未尽。"
)

_WORLD_WITH_TWO_QUESTIONS = (
    "边警叠至。"
    "<<DECISION>>"
    '{"title":"问一","context":"c1","options":['
    '{"label":"甲","hint":"h甲"},'
    '{"label":"乙","hint":"h乙"}'
    "]}"
    "<<END>>"
    "中段。"
    "<<DECISION>>"
    '{"title":"问二","context":"c2","options":['
    '{"label":"丙","hint":"h丙"},'
    '{"label":"丁","hint":"h丁"}'
    "]}"
    "<<END>>"
    "尾声。"
)


def _decision_block(title: str, *labels: str) -> str:
    options = ",".join(
        f'{{"label":"{label}","hint":"h-{label}"}}' for label in labels
    )
    return (
        f"<<DECISION>>"
        f'{{"title":"{title}","context":"c","options":[{options}]}}'
        f"<<END>>"
    )


def test_world_question_opens_rescript_desk_and_awaits(game, monkeypatch):
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is True
    assert result.stage == "rescript"
    assert result.advanced is False
    assert int(state.turn) == closed_turn
    assert session.state.turn_phase == TurnPhase.AWAITING_DECISION.value
    desk = session.pending_decisions()
    assert len(desk) == 1
    assert desk[0]["title"] == "是否增援宁远"
    assert {opt["label"] for opt in desk[0]["options"]} == {"准调关宁", "暂缓"}
    assert desk[0]["status"] == "pending"
    # 世界段问前提交入口须持久化 kind=world 段结果（ADR 0157 步骤 4／4a）。
    segments = month_chain._load_chain(db, closed_turn).get("segment_applied_results") or []
    assert any(seg.get("kind") == "world" for seg in segments)


def test_world_segment_multiple_questions_share_one_desk(game, monkeypatch):
    """同段多问：全部 DECISION 块上案头，不得只收第一问。"""
    db, state, content = game
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text",
        lambda *a, **k: _WORLD_WITH_TWO_QUESTIONS,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is True
    titles = {row["title"] for row in session.pending_decisions()}
    assert titles == {"问一", "问二"}


def test_prior_month_answered_rescript_does_not_block_or_reappear(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    # 上月已答打回件：仍可能残留历史案卷，但不得进本月案头、不得挡过月。
    old_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="旧打回已答",
        target_kind="issue", target_id="old-rejected",
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET created_turn=?, status='proposed', "
        "promulgation_decision='rejected', rescript_pending=1 WHERE id=?",
        (int(state.turn) - 1, old_id),
    )
    db.conn.execute(
        "INSERT INTO decree_dossier_decisions "
        "(dossier_id, turn, decision, blocked_layer, rescript_action, reason, "
        "legal_reason_code, primary_opponents_json, gatekeeper_id, criteria_snapshot_json) "
        "VALUES (?, ?, 'rejected', 'cabinet_drafting', 'hold', '', '', '[]', NULL, '{}')",
        (old_id, int(state.turn) - 1),
    )
    db.conn.commit()

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is False
    assert result.stage == "gazette"
    assert all(
        f"dossier:{old_id}" != str(row.get("event_id") or "")
        for row in session.pending_decisions()
    )
    del minister


def test_this_turn_rejection_opens_triad_on_same_desk(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = _stage_rejected_edict(db, state, minister)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is True
    assert result.stage == "rescript"
    desk = {row["event_id"]: row for row in session.pending_decisions()}
    dossier = next(
        d for d in db.list_decree_dossiers()
        if int(d.get("pending_action_id") or 0) == pending_id
    )
    key = f"dossier:{int(dossier['id'])}"
    assert key in desk
    labels = {opt["label"] for opt in desk[key]["options"]}
    assert labels >= {"强颁", "收回", "留中"}
    assert db.get_decree_dossier(int(dossier["id"]))["rescript_pending"] is True
    assert db.list_decree_dossier_decisions(int(dossier["id"]))[-1]["affected_parties"] == (
        _rejected_verdict(db)["affected_parties"]
    )


def test_answering_triad_applies_and_releases_rescript_gate(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = _stage_rejected_edict(db, state, minister)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    withdrawn = next(
        opt for opt in desk_row["options"] if opt.get("dossier_decision") == "withdrawn"
    )

    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "label": withdrawn["label"],
            "hint": withdrawn.get("hint") or "",
            "dossier_id": withdrawn["dossier_id"],
            "dossier_decision": "withdrawn",
        }],
        write_gate=session._write_gate,
    )

    dossier = db.get_decree_dossier(int(withdrawn["dossier_id"]))
    assert dossier["status"] == "closed"
    assert dossier["rescript_pending"] is False
    assert session.state.turn_phase == TurnPhase.SETTLING.value
    # 零待批后主链停在邸报交接，不得仍卡批红。
    again = session.resolve_turn(allow_empty_decree=True)
    assert again.awaiting is False
    assert again.stage == "gazette"
    del pending_id


def test_answering_world_question_resumes_suffix_then_gazette(game, monkeypatch):
    """真实 continue_world_after_answers：只打 LLM 外缝，续推闸与清问须落库可见。"""
    db, state, content = game
    closed_turn = int(state.turn)
    continuation_calls = []
    dispatched_segments = []

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )

    def fake_continuation(session, chain, answers):
        continuation_calls.append(list(answers))
        return "准调关宁，关宁增戍。"

    real_dispatch = month_translate.dispatch_month_segment

    def spy_dispatch(db_, state_, *, segment, llm_config, source, alongside=None):
        dispatched_segments.append(str(segment))
        return real_dispatch(
            db_, state_, segment=segment, llm_config=llm_config,
            source=source, alongside=alongside,
        )

    monkeypatch.setattr(month_chain, "_run_world_continuation_text", fake_continuation)
    monkeypatch.setattr(month_translate, "dispatch_month_segment", spy_dispatch)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    choice = desk_row["options"][0]

    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "label": choice["label"],
            "hint": choice.get("hint") or "",
        }],
        write_gate=session._write_gate,
    )

    assert continuation_calls and continuation_calls[0][0]["label"] == choice["label"]
    assert any("关宁增戍" in seg for seg in dispatched_segments)
    assert session.state.turn_phase == TurnPhase.SETTLING.value
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_questions") in (None, [], ())
    assert chain.get("world_continued") is True

    again = session.resolve_turn(allow_empty_decree=True)
    assert again.stage == "gazette"
    assert again.awaiting is False
    # 同回合重入不得再烧续推。
    assert len(continuation_calls) == 1


def test_decree_question_continuation_idempotent_on_same_turn_reentry(game, monkeypatch):
    """旨意请旨续推：同回合二次入链不得重复分派声明。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="旨意续推幂等", origin="旨意", year=state.year, period=state.period,
        turn=state.turn,
    )
    _pending_id, ref = _stage_edict(
        db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id,
    )
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否加赈",
            "context": "灾民待哺",
            "options": [
                {"label": "加赈十万", "hint": "国库吃紧"},
                {"label": "照旧", "hint": "勉力支撑"},
            ],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()

    dispatch_count = []

    def fake_decree_text(session, dossier, answers):
        return "加赈落实，仓廪出十万。"

    real_dispatch = month_translate.dispatch_declaration

    def spy_dispatch(db_, state_, declaration, **kwargs):
        dispatch_count.append(dict(declaration) if isinstance(declaration, dict) else declaration)
        return real_dispatch(db_, state_, declaration, **kwargs)

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_chain, "_run_decree_continuation_text", fake_decree_text)
    monkeypatch.setattr(
        month_translate, "translate_month_segment",
        lambda *a, **k: {"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -10,
            "category": "加赈", "reason": "批红后续推",
        }]}},
    )
    monkeypatch.setattr(month_translate, "dispatch_declaration", spy_dispatch)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    choice = desk_row["options"][0]

    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "label": choice["label"],
            "hint": choice.get("hint") or "",
        }],
        write_gate=session._write_gate,
    )
    assert len(dispatch_count) == 1
    assert not db.staged_declarations.questions_for(ref)

    # 邸报交接重入 / SETTLING 恢复：已落不动。
    again = session.resolve_turn(allow_empty_decree=True)
    assert again.awaiting is False
    assert again.stage == "gazette"
    assert len(dispatch_count) == 1, (
        f"旨意请旨续推在同回合二次入链时重复分派：1 -> {len(dispatch_count)}"
    )


def test_decree_continuation_survives_llm_exhaustion_then_retries(game, monkeypatch):
    """ADR 0157：续推 LLM 耗尽后 questions 须保留；恢复口重试须再续推落账。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="续推耗尽恢复", origin="旨意", year=state.year, period=state.period,
        turn=state.turn,
    )
    _pending_id, ref = _stage_edict(
        db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id,
    )
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否加赈",
            "context": "灾民待哺",
            "options": [
                {"label": "加赈十万", "hint": "国库吃紧"},
                {"label": "照旧", "hint": "勉力支撑"},
            ],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()

    llm_calls = []
    dispatch_count = []
    fail_once = {"armed": True}

    def flaky_decree_text(session, dossier, answers):
        llm_calls.append(1)
        if fail_once["armed"]:
            fail_once["armed"] = False
            raise RuntimeError("模型调用耗尽")
        return "加赈落实，仓廪出十万。"

    real_dispatch = month_translate.dispatch_declaration

    def spy_dispatch(db_, state_, declaration, **kwargs):
        dispatch_count.append(1)
        return real_dispatch(db_, state_, declaration, **kwargs)

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_chain, "_run_decree_continuation_text", flaky_decree_text)
    monkeypatch.setattr(
        month_translate, "translate_month_segment",
        lambda *a, **k: {"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -10,
            "category": "加赈", "reason": "批红后续推",
        }]}},
    )
    monkeypatch.setattr(month_translate, "dispatch_declaration", spy_dispatch)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    choice = desk_row["options"][0]
    payload = [{
        "decision_key": desk_row["decision_key"],
        "label": choice["label"],
        "hint": choice.get("hint") or "",
    }]

    try:
        session.submit_hitl_choices(payload, write_gate=session._write_gate)
        raised = None
    except RuntimeError as exc:
        raised = exc
    assert raised is not None and "模型调用耗尽" in str(raised)
    assert db.staged_declarations.questions_for(ref), (
        "续推失败后 questions 已清，恢复将无法再续推"
    )
    assert len(llm_calls) == 1
    assert len(dispatch_count) == 0

    # 真实恢复口：携原 decision_key 重交 → already_applied → phase2 续跑月链。
    session.submit_hitl_choices(payload, write_gate=session._write_gate)
    assert len(llm_calls) == 2
    assert len(dispatch_count) == 1, (
        "旨意问后后果永久丢失：重试未再续推（questions 已清，闸跳过）"
    )
    assert not db.staged_declarations.questions_for(ref)
    assert session.state.turn_phase == TurnPhase.SETTLING.value


def test_decree_question_and_world_question_share_one_desk(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="同页请旨", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending_id, ref = _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否加赈",
            "context": "灾民待哺",
            "options": [
                {"label": "加赈十万", "hint": "国库吃紧"},
                {"label": "照旧", "hint": "勉力支撑"},
            ],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text",
        lambda *a, **k: "边警。" + _decision_block("是否增援宁远", "准调", "暂缓"),
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is True
    titles = {row["title"] for row in session.pending_decisions()}
    assert titles == {"是否加赈", "是否增援宁远"}


def _hitl_payload(desk_row):
    choice = desk_row["options"][0]
    return [{
        "decision_key": desk_row["decision_key"],
        "label": choice["label"],
        "hint": choice.get("hint") or "",
    }]


def test_missing_model_keeps_decree_question_until_retry(game, monkeypatch):
    """缺模型不得清问；原批红入口重试后才续推。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="缺模型续推", origin="旨意", year=state.year, period=state.period,
        turn=state.turn,
    )
    _pending_id, ref = _stage_edict(
        db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id,
    )
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否加赈",
            "context": "灾民待哺",
            "options": [
                {"label": "准", "hint": "出仓"},
                {"label": "驳", "hint": "缓"},
            ],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session.llm_config = None
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    payload = _hitl_payload(desk_row)

    try:
        session.submit_hitl_choices(payload, write_gate=session._write_gate)
        raised = None
    except LLMUnavailable as exc:
        raised = exc
    assert raised is not None
    assert db.staged_declarations.questions_for(ref)
    assert session.state.turn_phase == TurnPhase.AWAITING_DECISION.value

    calls = []

    def continuation(session_, dossier, answers):
        calls.append(answers)
        return "问后无新账。"

    monkeypatch.setattr(month_chain, "_run_decree_continuation_text", continuation)
    session.llm_config = object()
    session.submit_hitl_choices(payload, write_gate=session._write_gate)
    assert calls
    assert not db.staged_declarations.questions_for(ref)
    assert session.state.turn_phase == TurnPhase.SETTLING.value


def test_missing_model_does_not_mark_world_continued(game, monkeypatch):
    """世界段缺模型不得记 world_continued；重试才从问处续推。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session.llm_config = None
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    payload = _hitl_payload(desk_row)

    try:
        session.submit_hitl_choices(payload, write_gate=session._write_gate)
        raised = None
    except LLMUnavailable as exc:
        raised = exc
    assert raised is not None
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_continued") is not True
    assert chain.get("world_questions")
    assert session.state.turn_phase == TurnPhase.AWAITING_DECISION.value

    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text",
        lambda *a, **k: "准调关宁，关宁增戍。",
    )
    session.llm_config = object()
    session.submit_hitl_choices(payload, write_gate=session._write_gate)
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_continued") is True
    assert chain.get("world_questions") in (None, [], ())


def test_cross_month_pending_draft_opens_rescript_desk(game, monkeypatch):
    """本月零请旨时，既有跨月急务仍走同一案头，不得直接交邸报。"""
    db, state, content = game
    closed_turn = int(state.turn)
    prior = closed_turn - 1
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, event_id, title, context, options_json, choice_json, "
        " status, kind, actor_name, actor_office, actor_faction, "
        " revision_round, prior_options_json) "
        "VALUES (?, 0, 'urgent:old:0', '旧急务甲', '跨月待批', ?, '', "
        " 'pending', 'rescript_draft', '首辅', '内阁首辅', '东林', 0, '[]')",
        (
            prior,
            json.dumps([
                {"label": "发帑", "hint": "饥民"},
                {"label": "留中", "hint": "待查"},
            ], ensure_ascii=False),
        ),
    )
    db.conn.commit()
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is True
    assert result.stage == "rescript"
    assert result.advanced is False
    assert int(state.turn) == closed_turn
    assert session.state.turn_phase == TurnPhase.AWAITING_DECISION.value
    titles = [row["title"] for row in session.pending_decisions()]
    assert titles == ["旧急务甲"]
    assert session.pending_decisions()[0]["kind"] == "rescript_draft"


def test_decree_continuation_keeps_forecast_and_lands_affair_effect(game, monkeypatch):
    """问后续推读已存问前段与请旨语境，并以冻结引用落下 affair 来源效果。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="问后落账", origin="旨意", year=state.year, period=state.period,
        turn=state.turn,
    )
    _pending_id, ref = _stage_edict(
        db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id,
    )
    question_context = "灾民待哺于关中，短选项不足以自明"
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否加赈",
            "context": question_context,
            "options": [
                {"label": "准", "hint": "出仓"},
                {"label": "驳", "hint": "缓"},
            ],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()
    captured = {}

    def fake_agent(llm_config, sim_payload):
        del llm_config
        captured["sim_payload"] = sim_payload
        return object()

    def fake_run(agent, message, tag="", transport_policy=None):
        del agent, transport_policy
        captured["tag"] = tag
        captured["message"] = message
        return "加赈落实，仓廪出十万。"

    def translate(*_a, **kwargs):
        captured["grounding"] = kwargs.get("target_grounding") or ""
        segment = str(kwargs.get("segment") or "")
        if "仓廪出十万" not in segment:
            return {"effects": {}}
        return {"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}",
            "account": "国库",
            "delta": -10,
            "category": "问后加赈",
            "reason": "批红后续推",
        }]}}

    import ming_sim.simulation as simulation

    real_payload = simulation.build_simulator_payload

    def payload_with_world_event(*args, **kwargs):
        payload = real_payload(*args, **kwargs)
        payload["candidate_events"] = [{"id": "ev-boundary", "title": "边警"}]
        return payload

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr("ming_sim.agents.create_decree_forecast_agent", fake_agent)
    monkeypatch.setattr("ming_sim.agents.run_agent_text", fake_run)
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(simulation, "build_simulator_payload", payload_with_world_event)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='问后加赈'",
    ).fetchone()[0]
    pre_rows = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='陕西赈灾'",
    ).fetchone()[0]
    desk_row = next(
        row for row in session.pending_decisions() if row["title"] == "是否加赈"
    )

    session.submit_hitl_choices(
        _hitl_payload(desk_row), write_gate=session._write_gate,
    )

    message = str(captured.get("message") or "")
    assert "预推不可见:陕西赈灾" in message
    assert question_context in message
    assert captured["sim_payload"]["candidate_events"] == []
    assert str(affair.id) in str(captured.get("grounding") or "")
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='问后加赈'",
    ).fetchone()[0] == before + 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='陕西赈灾'",
    ).fetchone()[0] == pre_rows
    assert not db.staged_declarations.questions_for(ref)
    # 批红问后旨意续推入口须持久化 kind=decree_post 段结果并可供 4a 读入。
    turn = int(state.turn)
    segments = month_chain._load_chain(db, turn).get("segment_applied_results") or []
    decree_post = [s for s in segments if s.get("kind") == "decree_post"]
    assert len(decree_post) == 1
    assert any(
        any(int(m.get("delta") or 0) == -10 for m in (rep.get("economy_moves") or []))
        for rep in (decree_post[0].get("applied") or [])
        if isinstance(rep, dict)
    )
    feed = month_chain.build_secret_orders_supply_feed(
        db, state, month_chain._load_chain(db, turn),
    )
    assert any(
        int(m.get("delta") or 0) == -10
        for m in (feed.get("origin_effects") or {}).get("economy_moves") or []
    )

    session.resolve_turn(allow_empty_decree=True)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='问后加赈'",
    ).fetchone()[0] == before + 1


def test_decree_forecast_keeps_every_question_and_translates_prefix_once(
    game, monkeypatch,
):
    """同一旨的合法请旨全部上案头；只转译、暂存首问前的段文。"""
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="secret_authorization", decree_text="密旨两问",
        target_kind="issue", target_id="two-questions",
        payload={"mode": "ordinary"},
    )
    narrative = (
        "问前事实。"
        + _decision_block("问一", "准", "驳")
        + "中段。"
        + _decision_block("问二", "甲", "乙")
        + "问后不入预推。"
    )
    segments = []

    def translate(*_a, **kwargs):
        segments.append(str(kwargs.get("segment") or ""))
        return {"effects": {}}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.decree_forecast.agents.create_decree_forecast_agent",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "ming_sim.decree_forecast.agents.run_agent_text",
        lambda *a, **k: narrative,
    )
    monkeypatch.setattr(
        "ming_sim.decree_forecast.translate_month_segment", translate,
    )
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.awaiting is True
    assert [row["title"] for row in result.decisions] == ["问一", "问二"]
    assert segments == ["问前事实。"]
    from ming_sim.decree_forecast import decree_ref_for_dossier
    ref = decree_ref_for_dossier(db, db.get_decree_dossier(dossier_id))
    stored = db.staged_declarations.questions_for(ref)
    assert [item["title"] for item in stored] == ["问一", "问二"]
    assert db.staged_declarations.forecast_text_for(ref) == "问前事实。"


def test_question_note_only_is_kept_and_other_decisions_still_require_label(
    game, monkeypatch,
):
    """请旨可只交亲笔 note；普通选项仍须命中票拟，批语不改写成选项。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="亲笔请旨", origin="旨意", year=state.year, period=state.period,
        turn=state.turn,
    )
    _pending_id, ref = _stage_edict(
        db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id,
    )
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否加赈",
            "context": "灾民待哺",
            "options": [
                {"label": "准", "hint": "出仓"},
                {"label": "驳", "hint": "缓"},
            ],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()
    answers = []

    def continuation(_session, _dossier, got):
        answers.append(list(got))
        return ""

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_chain, "_run_decree_continuation_text", continuation)
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    bad = [{
        "decision_key": desk_row["decision_key"],
        "label": "不是票拟",
        "note": "着户部另议",
    }]
    try:
        session.submit_hitl_choices(bad, write_gate=session._write_gate)
        rejected = None
    except ValueError as exc:
        rejected = exc
    assert rejected is not None and "选项不在当前 options" in str(rejected)
    assert db.staged_declarations.questions_for(ref)
    assert desk_row["status"] == "pending"

    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "note": "着户部另议",
        }],
        write_gate=session._write_gate,
    )
    assert answers and answers[0][0]["note"] == "着户部另议"
    assert answers[0][0]["label"] == ""
    assert not db.staged_declarations.questions_for(ref)

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "season:1",
        "title": "旧抉择",
        "context": "非请旨",
        "options": [
            {"label": "甲", "hint": ""},
            {"label": "乙", "hint": ""},
        ],
    }])
    ordinary = session.pending_decisions()[0]
    try:
        session.submit_hitl_choices(
            [{"decision_key": ordinary["decision_key"], "note": "只写批语"}],
            write_gate=session._write_gate,
        )
        ordinary_rejected = None
    except ValueError as exc:
        ordinary_rejected = exc
    assert ordinary_rejected is not None and "选项不在当前 options" in str(ordinary_rejected)
    assert session.pending_decisions()[0]["status"] == "pending"


def _rejected_verdict(db):
    faction = db.conn.execute("SELECT name FROM factions LIMIT 1").fetchone()["name"]
    return {
        "decision": "rejected",
        "reason": "科参未允",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": faction}],
        "affected_parties": [{
            "kind": "faction", "key": faction,
            "direction": "negative", "intensity": "weak",
        }],
        "criteria_snapshot": {
            "imperial_authority_band": "中等", "appointment_tenure": "",
            "authorization_ids": [], "endorsement_entry_ids": [],
        },
        "gatekeeper_id": None,
    }


def _stage_rejected_edict(db, state, minister):
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-chain", "actor": minister, "mode": "ordinary",
            "text": "河工",
        },
    )
    db.staged_declarations.stage(
        decree_ref=pending_action_decree_ref(pending_id, 1),
        declaration={}, turn=int(state.turn), verdict=_rejected_verdict(db),
    )
    return pending_id


def _choice(row, *, decision=""):
    option = row["options"][0]
    if decision:
        option = next(opt for opt in row["options"] if opt.get("dossier_decision") == decision)
    payload = {
        "decision_key": row["decision_key"],
        "label": option["label"],
        "hint": option.get("hint") or "",
    }
    if decision:
        payload["dossier_id"] = option["dossier_id"]
        payload["dossier_decision"] = decision
    return payload


def _stage_fatal_midzhi(db, state, content):
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-chain", "actor": minister, "mode": "midzhi",
            "text": "命门中旨",
        },
    )
    ref = pending_action_decree_ref(pending_id, 1)
    verdict = _rejected_verdict(db)
    verdict.pop("affected_parties", None)
    verdict["midzhi_unpromulgatable"] = True
    db.staged_declarations.stage(
        decree_ref=ref,
        declaration={"effects": {}},
        turn=int(state.turn),
        verdict=verdict,
        visible_refs={"affairs": [], "issues": [], "secret_orders": []},
    )
    return pending_id


def test_fatal_midzhi_rejection_hides_force_option(game, monkeypatch):
    """命门中旨打回的亦不可颁标记落判决行，批红台不得再给强颁。"""
    db, state, content = game
    _stage_fatal_midzhi(db, state, content)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    session.resolve_turn(allow_empty_decree=True)

    triad = next(
        row for row in session.pending_decisions() if str(row["event_id"]).startswith("dossier:")
    )
    assert all(opt.get("dossier_decision") != "force_promulgated" for opt in triad["options"])
    dossier_id = int(str(triad["event_id"]).split(":", 1)[1])
    assert db.list_decree_dossier_decisions(dossier_id)[-1]["midzhi_unpromulgatable"] is True
    with sqlite3.connect(db.path) as reopened:
        assert reopened.execute(
            "SELECT midzhi_unpromulgatable FROM decree_dossier_decisions WHERE dossier_id=?",
            (dossier_id,),
        ).fetchone()[0] == 1


def test_midzhi_promulgation_records_authority_cost_once(game, monkeypatch):
    """预声明中旨顺颁由权威判决入口落皇威代价，不扇出猜派反应。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-chain", "actor": minister, "mode": "midzhi",
            "text": "中旨顺颁",
        },
    )
    db.staged_declarations.stage(
        decree_ref=pending_action_decree_ref(pending_id, 1),
        declaration={"effects": {}}, turn=int(state.turn),
        verdict={"decision": "promulgated"},
    )
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    session.resolve_turn(allow_empty_decree=True)

    dossier_id = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (pending_id,),
    ).fetchone()[0]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_cost_events WHERE dossier_id=? "
        "AND cost_kind='authority' AND cost_identity='override'",
        (dossier_id,),
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_cost_events WHERE dossier_id=? AND cost_kind='satisfaction'",
        (dossier_id,),
    ).fetchone()[0] == 0


def test_midzhi_verdict_and_metadata_roll_back_together(game, monkeypatch):
    """共享元数据写口落标后中断，判决同事务回滚，重开仍为待判。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    pending_id = _stage_fatal_midzhi(db, state, content)
    original = db._record_dossier_verdict_metadata

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("判决落标中断")

    monkeypatch.setattr(db, "_record_dossier_verdict_metadata", interrupted)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert isinstance(caught.value.__cause__, RuntimeError)
    with sqlite3.connect(db.path) as reopened:
        assert reopened.execute(
            "SELECT status FROM decree_dossiers WHERE pending_action_id=?",
            (pending_id,),
        ).fetchone()[0] == "proposed"
        assert reopened.execute(
            "SELECT COUNT(*) FROM decree_dossier_decisions WHERE dossier_id="
            "(SELECT id FROM decree_dossiers WHERE pending_action_id=?)",
            (pending_id,),
        ).fetchone()[0] == 0


def test_decree_continuation_ending_ends_the_month(game, monkeypatch):
    """旨意问后续推的退位结局写入月链，推进不得当成 ongoing。"""
    from ming_sim.models import LLMConfig

    db, state, content = game
    closed_turn = int(state.turn)
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="问后结局", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending_id, ref = _stage_edict(db, state, minister, "逊国", "逊国", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否逊国", "context": "国势已去",
            "options": [{"label": "逊", "hint": "退位"}, {"label": "守", "hint": "不退"}],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()

    def translate(*_a, **kwargs):
        if "煤山" not in str(kwargs.get("segment") or ""):
            return {"effects": {}}
        return {"effects": {"emperor_fate": "abdicate"}}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_chain, "_run_decree_continuation_text", lambda *a, **k: "煤山已定。")
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_gazette_text", lambda *a, **k: ("邸报", "逊国已闻"))
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    session._write_gate = threading.Lock()
    session.resolve_turn(allow_empty_decree=True)
    question = session.pending_decisions()[0]
    session.submit_hitl_choices([_choice(question)], write_gate=session._write_gate)

    again = session.resolve_turn(allow_empty_decree=True)

    assert again.advanced is True
    assert state.ended is True
    assert state.ending_status == "emperor_abdicate"
    assert month_chain._load_chain(db, closed_turn)["declaration_outcome"]["status"] == "emperor_abdicate"


def test_drift_sees_effects_landed_after_answers(game, monkeypatch):
    """问后续推落下的局面，当月惯性才看得到；未答完不得先跑惯性。"""
    db, state, content = game
    db.conn.execute(
        "INSERT INTO issues (kind, title, origin_turn, inertia, bar_value, status) "
        "VALUES ('situation', '边警自走', ?, 5, 40, 'active')",
        (int(state.turn),),
    )
    issue_id = int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    db.conn.commit()

    def translate(*_a, **kwargs):
        if "问后结案" not in str(kwargs.get("segment") or ""):
            return {"effects": {}}
        return {"effects": {"close_issues": [{
            "issue_id": issue_id, "reason": "resolved",
        }]}}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text", lambda *a, **k: "问后结案。",
    )
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()
    paused = session.resolve_turn(allow_empty_decree=True)
    assert paused.awaiting is True
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='inertia'",
        (issue_id,),
    ).fetchone()[0] == 0
    session.submit_hitl_choices(
        [_choice(session.pending_decisions()[0])], write_gate=session._write_gate,
    )

    session.resolve_turn(allow_empty_decree=True)

    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] != "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='inertia'",
        (issue_id,),
    ).fetchone()[0] == 0


def test_step_4a_no_eligible_objects_skips_run_and_completes(game, monkeypatch):
    """步骤 4a：无合资格长差案卷且无在办密令时，不为凑调用而起 run。"""
    db, state, content = game
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})

    def forbidden_supply(*a, **k):
        raise AssertionError("没有合资格对象时不应调用整月供料 run")

    monkeypatch.setattr(month_chain, "run_secret_orders_supply", forbidden_supply)
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.stage == "gazette"
    chain = month_chain._load_chain(db, int(state.turn))
    assert chain.get("secret_orders_supply_done") is True


def test_step_4a_rescript_continuation_feeds_supply_run_input(game, monkeypatch):
    """问后续推落下的 origin 效果进入步骤 4a 供料，且能驱动密令实际进度。"""
    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = db.create_secret_order(
        state, minister, "辽饷清核", "查清兵部饷银", [],
        deadline_months=2,
        covert_task={
            "kind": "差务", "axes": ["实务事功"], "direction": 1,
            "delivery": {
                "unit": "万两", "target_units": 5.0, "effect_sign": -1,
                "purpose": "其它", "category": "密令差务", "account": "内库",
            },
        },
    )
    db.conn.execute(
        "UPDATE secret_orders SET turn_issued=? WHERE id=?",
        (turn - 1, order_id),
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    captured_feed = {}

    def supply_run(db_, state_, llm_config, chain):
        feed = month_chain.build_secret_orders_supply_feed(db_, state_, chain)
        captured_feed.update(feed)
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "顺利",
                "memorial_text": "关外饷银如数盘点，实支有据。",
            }],
            "covert_exec_selections": [{
                "order_id": order_id,
                "fidelity": "忠实",
                "note": "实办尽职",
            }],
        }

    def translate(*_a, **kwargs):
        if "问后核银" not in str(kwargs.get("segment") or ""):
            return {"effects": {}}
        return {"effects": {
            "economy_moves": [{
                "account": "内库", "delta": -5, "category": "密令差务",
                "purpose": "其它", "reason": "问后实办内库出银",
                "origin_ref": f"dossier:{dossier_id}",
            }],
        }}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text", lambda *a, **k: "问后核银。",
    )
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()

    # Step 1: Pauses at rescript question
    paused = session.resolve_turn(allow_empty_decree=True)
    assert paused.awaiting is True
    assert captured_feed == {}

    # Step 2: Answer question, resumes
    session.submit_hitl_choices(
        [_choice(session.pending_decisions()[0])], write_gate=session._write_gate,
    )
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"

    # Verify Step 4a saw continuation origin effects (structured, not generated prose)
    assert captured_feed.get("turn") == turn
    origin_effects = captured_feed.get("origin_effects") or {}
    eco_moves = origin_effects.get("economy_moves") or []
    assert any(m.get("origin_ref") == f"dossier:{dossier_id}" for m in eco_moves)
    eligible = captured_feed.get("eligible_dossiers") or []
    assert any(
        int(item.get("dossier_id") or 0) == dossier_id
        and str(item.get("decree_text") or "").strip()
        and isinstance(item.get("payload"), dict)
        and item.get("covert_task_contract") is not None
        for item in eligible
    )
    assert str(captured_feed.get("board") or "").strip()

    # Verify 0058 structured落库与实况单位（禁盯密奏正文）
    reports = db.list_dossier_progress(dossier_id)
    assert any(str(r.get("progress_band") or "") == "顺利" for r in reports)
    actual_units = db.sum_dossier_actual_progress_units(dossier_id)
    assert actual_units == 5.0


def test_step_4a_deferred_disclosure_sees_fresh_0058_progress(game, monkeypatch):
    """步骤 2-4 的密令披露暂缓至 0058 密奏落库后发布，公开事件包含本月最新进展正文。"""
    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = create_test_secret_order(
        db, state, minister, "查抄私仓", "核实私设粮仓", [],
        deadline_months=2,
    )
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (turn - 1, order_id))
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    # World segment sets disclosed=True for order_id
    def translate(*_a, **_k):
        return {"effects": {
            "secret_order_updates": [{
                "order_id": order_id,
                "sim_note": "私仓已被锦衣卫查封",
                "disclosed": True,
            }],
        }}

    def supply_run(*_a, **_k):
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "顺利",
                "memorial_text": "已查得私仓粮石十万石，罪证确凿。",
            }],
            "covert_exec_selections": [{
                "order_id": order_id,
                "fidelity": "忠实",
            }],
        }

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "世界段推演。")
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"

    # Disclosure event exists after 0058；只验结构化落库与事件存在，不盯生成正文
    rows = db.conn.execute(
        "SELECT title, body, source_id FROM character_knowledge_events "
        "WHERE character_name='' AND source_id LIKE ?",
        (f"secret_order_disclosure:{order_id}:%",),
    ).fetchall()
    assert len(rows) == 1
    assert str(rows[0]["source_id"]).startswith(f"secret_order_disclosure:{order_id}:")
    reports = db.list_dossier_progress(dossier_id)
    assert any(str(r.get("progress_band") or "") == "顺利" for r in reports)
    chain = month_chain._load_chain(db, turn)
    assert chain.get("secret_orders_disclosures_done") is True


def test_step_4a_incomplete_0058_report_fails_loud_and_retry_restarts(game, monkeypatch):
    """步骤 4a：0058 完整性校验缺报响亮中止，重试废弃不完整产物重新调用 supply run。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_1 = create_test_secret_order(db, state, minister, "密令一", "差务一", [], deadline_months=2)
    order_2 = create_test_secret_order(db, state, minister, "密令二", "差务二", [], deadline_months=2)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id IN (?, ?)", (turn - 1, order_1, order_2))
    dossier_1 = int(db.get_dossier_for_secret_order(order_1)["id"])
    dossier_2 = int(db.get_dossier_for_secret_order(order_2)["id"])
    db.conn.commit()

    call_count = 0

    def supply_run(*_a, **_k):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: incomplete! Only reports dossier_1, missing dossier_2
            return {
                "dossier_progress_reports": [{
                    "dossier_id": dossier_1,
                    "progress_band": "持平",
                    "memorial_text": "密奏一",
                }],
                "covert_exec_selections": [
                    {"order_id": order_1, "fidelity": "忠实"},
                    {"order_id": order_2, "fidelity": "忠实"},
                ],
            }
        # Second call (after retry): complete!
        return {
            "dossier_progress_reports": [
                {"dossier_id": dossier_1, "progress_band": "持平", "memorial_text": "密奏一"},
                {"dossier_id": dossier_2, "progress_band": "持平", "memorial_text": "密奏二"},
            ],
            "covert_exec_selections": [
                {"order_id": order_1, "fidelity": "忠实"},
                {"order_id": order_2, "fidelity": "忠实"},
            ],
        }

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "边事暂宁。")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    # First attempt: incomplete report fails loud
    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert caught.value.stage == "secret_orders_supply"
    chain = month_chain._load_chain(db, turn)
    assert chain.get("secret_orders_supply_invalid") is True
    # Neither dossier received a progress report
    assert db.list_dossier_progress(dossier_1) == []
    assert db.list_dossier_progress(dossier_2) == []

    # Retry: discards invalid product, re-calls supply run
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"
    assert call_count == 2
    assert len(db.list_dossier_progress(dossier_1)) == 1
    assert len(db.list_dossier_progress(dossier_2)) == 1


def test_step_4a_crash_recovery_resumes_without_re_running_supply(game, monkeypatch):
    """步骤 4a 校验通过的产物在后续崩溃后重开，保留产物并幂等接续未完成相。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = create_test_secret_order(db, state, minister, "密令", "差务", [], deadline_months=2)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (turn - 1, order_id))
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    call_count = 0

    def supply_run(*_a, **_k):
        nonlocal call_count
        call_count += 1
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "顺利",
                "memorial_text": "进度良好",
            }],
            "covert_exec_selections": [{
                "order_id": order_id,
                "fidelity": "忠实",
            }],
        }

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "边事暂宁。")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    crash_once = True
    from ming_sim import covert_progress

    real_apply = covert_progress.apply_monthly_covert_actual_progress

    def buggy_apply(*args, **kwargs):
        nonlocal crash_once
        if crash_once:
            crash_once = False
            raise RuntimeError("模拟执行态落账中断")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(covert_progress, "apply_monthly_covert_actual_progress", buggy_apply)

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    # First pass: lands Phase 1 (reports), but crashes on Phase 3
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)

    assert call_count == 1
    # Phase 1 already committed: 0058 report exists
    assert len(db.list_dossier_progress(dossier_id)) == 1
    chain = month_chain._load_chain(db, turn)
    assert chain.get("secret_orders_reports_done") is True
    assert chain.get("secret_orders_supply_product") is not None

    # Resume turn: supply run must NOT be called again
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"
    assert call_count == 1  # Not re-run!
    # Reports not duplicated
    assert len(db.list_dossier_progress(dossier_id)) == 1
    # Phase 3 actual progress landed
    assert db.conn.execute(
        "SELECT COUNT(*) FROM dossier_actual_progress WHERE dossier_id=? AND turn=?",
        (dossier_id, turn),
    ).fetchone()[0] == 1


def test_step_4a_missing_covert_fidelity_records_inline_rejection(game, monkeypatch):
    """步骤 4a：密令缺少有效执行态时按 0073 记入 inline rejection，不静默吞掉。"""
    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = create_test_secret_order(
        db, state, minister, "密令执行态缺失", "差务", [], deadline_months=2,
    )
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (turn - 1, order_id))
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    # Supply run provides 0058 report, but omits covert_exec_selections!
    def supply_run(*_a, **_k):
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "持平",
                "memorial_text": "按期奏报",
            }],
            "covert_exec_selections": [],
        }

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "边事暂宁。")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"

    # Inline rejection：断言机读 category，不读人读 prose（ADR 0142 / 0073）
    rejections = db.conn.execute(
        "SELECT section, category, reason FROM rejection_reports "
        "WHERE turn=? AND section='covert_exec_selections'",
        (turn,),
    ).fetchall()
    assert len(rejections) == 1
    assert rejections[0]["category"] == "invalid_enum"


def test_settle_edicts_persists_pending_disclosures_in_same_transaction(game, monkeypatch):
    """_settle_edicts.persist_result：disclosed 暂缓项须与旨意结算同事务写入月链。"""
    from types import SimpleNamespace

    from ming_sim.decree_forecast import pending_action_decree_ref, stage_declaration
    from ming_sim.month_chain import _load_chain, _settle_edicts

    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = create_test_secret_order(
        db, state, minister, "披露暂缓密令", "差务", [], deadline_months=2,
    )
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (turn - 1, order_id))
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "disclosure-pending", "actor": minister, "mode": "ordinary",
            "text": "查抄并明发",
        },
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="查抄并明发",
        target_kind="issue", target_id="disclosure-pending",
        pending_action_id=pending_id,
        payload={"text": "查抄并明发"},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='promulgated', promulgation_decision='promulgated' "
        "WHERE id=?",
        (dossier_id,),
    )
    ref = pending_action_decree_ref(pending_id, 1)
    stage_declaration(
        db, decree_ref=ref, turn=turn,
        declaration={"effects": {"secret_order_updates": [{
            "order_id": order_id,
            "sim_note": "私仓已查封，案情明发",
            "disclosed": True,
        }]}},
        verdict={"decision": "promulgated"},
        visible_refs={"secret_orders": [order_id], "issues": [], "affairs": []},
    )
    db.conn.commit()

    sess = SimpleNamespace(
        db=db, state=state, llm_config=None, agno_db=None, content=content,
    )
    chain: dict = {}
    _settle_edicts(sess, registry=None, chain=chain)

    assert db.staged_declarations.is_settled(ref)
    reloaded = _load_chain(db, turn)
    pending = reloaded.get("pending_disclosures") or []
    assert any(
        int(item.get("order_id") or 0) == order_id
        and "私仓已查封" in str(item.get("sim_note") or "")
        for item in pending
    ), f"pending_disclosures missing after settle: {pending!r}"

    # 同事务：alongside 内 _save_chain 失败须回滚结算标记
    order_2 = create_test_secret_order(
        db, state, minister, "原子回滚密令", "差务二", [], deadline_months=2,
    )
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (turn - 1, order_2))
    pending_2 = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "disclosure-atomic", "actor": minister, "mode": "ordinary",
            "text": "第二道披露旨",
        },
    )
    dossier_2 = db.create_decree_dossier(
        state, action_type="policy", decree_text="第二道披露旨",
        target_kind="issue", target_id="disclosure-atomic",
        pending_action_id=pending_2,
        payload={"text": "第二道披露旨"},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='promulgated', promulgation_decision='promulgated' "
        "WHERE id=?",
        (dossier_2,),
    )
    ref_2 = pending_action_decree_ref(pending_2, 1)
    stage_declaration(
        db, decree_ref=ref_2, turn=turn,
        declaration={"effects": {"secret_order_updates": [{
            "order_id": order_2,
            "sim_note": "第二道应暂缓",
            "disclosed": True,
        }]}},
        verdict={"decision": "promulgated"},
        visible_refs={"secret_orders": [order_2], "issues": [], "affairs": []},
    )
    db.conn.commit()

    real_save = month_chain._save_chain

    def boom_save(db_, turn_, chain_, **kwargs):
        pending_now = chain_.get("pending_disclosures") or []
        if any(int(item.get("order_id") or 0) == order_2 for item in pending_now):
            raise RuntimeError("injected chain save failure")
        return real_save(db_, turn_, chain_, **kwargs)

    monkeypatch.setattr(month_chain, "_save_chain", boom_save)
    with pytest.raises(RuntimeError, match="injected chain save failure"):
        _settle_edicts(sess, registry=None, chain=chain)
    assert not db.staged_declarations.is_settled(ref_2)


def test_step_4a_non_validation_failure_keeps_product_on_retry(game, monkeypatch):
    """步骤 4a：非 0058 校验失败不得标 invalid；重试保留产物、不重跑 supply。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = create_test_secret_order(db, state, minister, "密令", "差务", [], deadline_months=2)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (turn - 1, order_id))
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    call_count = 0

    def supply_run(*_a, **_k):
        nonlocal call_count
        call_count += 1
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "持平",
                "memorial_text": "完整密奏",
            }],
            "covert_exec_selections": [{"order_id": order_id, "fidelity": "忠实"}],
        }

    real_presence = db.record_monthly_supervision_presence
    fail_once = True

    def flaky_presence(turn_, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("injected supervision presence failure")
        return real_presence(turn_, **kwargs)

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "边事暂宁。")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)
    monkeypatch.setattr(db, "record_monthly_supervision_presence", flaky_presence)

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert caught.value.stage == "secret_orders_supply"
    chain = month_chain._load_chain(db, turn)
    assert chain.get("secret_orders_supply_invalid") is not True
    assert chain.get("secret_orders_supply_product") is not None
    assert call_count == 1

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"
    assert call_count == 1  # 保留产物，不重跑 supply
    assert len(db.list_dossier_progress(dossier_id)) == 1


def test_step_4a_settles_due_secret_order(game, monkeypatch):
    """步骤 4a：到期密令在实况落账后由步骤 4a 办理结案，且早于邸报供料。"""
    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = db.create_secret_order(
        state, minister, "到期结案密令", "到期查核", [],
        deadline_months=1,
        covert_task={
            "kind": "差务", "axes": ["实务事功"], "direction": 1,
            "delivery": {
                "unit": "万两", "target_units": 2.0, "effect_sign": -1,
                "purpose": "其它", "category": "密令差务", "account": "内库",
            },
        },
    )
    # Issued last turn, due this turn
    db.conn.execute(
        "UPDATE secret_orders SET turn_issued=?, due_turn=? WHERE id=?",
        (turn - 1, turn, order_id),
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    def translate(*_a, **_k):
        return {"effects": {
            "economy_moves": [{
                "account": "内库", "delta": -2, "category": "密令差务",
                "purpose": "其它", "reason": "差务结项出银",
                "origin_ref": f"dossier:{dossier_id}",
            }],
        }}

    def supply_run(*_a, **_k):
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "顺利",
                "memorial_text": "核查终结奏报",
            }],
            "covert_exec_selections": [{
                "order_id": order_id,
                "fidelity": "忠实",
            }],
        }

    _forbid_extractor(monkeypatch)
    # 空世界段文会跳过转译；须有非空段文才能落下问前 origin 效果供 4a 结案。
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "边事暂宁。")
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"

    # Secret order should be settled to 'done' (delivered 2.0 / target 2.0)
    assert db.get_secret_order(order_id)["status"] == "done"
    chain = month_chain._load_chain(db, turn)
    assert chain.get("due_secret_orders_settled") is True
    assert chain.get("secret_orders_supply_done") is True


def test_step_4a_rescript_supply_includes_issue_and_office_origin_effects(
    game, monkeypatch,
):
    """批红问后落地的 issue／任免经真实声明写入，从段结果供料；拒收与上月表行不混入。"""
    from tests.conftest import active_ming_character

    db, state, content = game
    turn = int(state.turn)
    minister = active_ming_character(db, content)
    old_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,),
    ).fetchone()["office"]
    new_office = "陕西总督" if old_office != "陕西总督" else "陕西巡抚"
    order_id = db.create_secret_order(
        state, minister, "边材考选", "考选边材并立核饷局", [],
        deadline_months=2,
        covert_task={
            "kind": "差务", "axes": ["实务事功"], "direction": 1,
            "delivery": {
                "unit": "万两", "target_units": 2.0, "effect_sign": -1,
                "purpose": "其它", "category": "密令差务", "account": "内库",
            },
        },
    )
    db.conn.execute(
        "UPDATE secret_orders SET turn_issued=? WHERE id=?",
        (turn - 1, order_id),
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    # 上月任免表行：逐表猜补时代会混入；段结果真源不得读到它。
    db.conn.execute(
        """
        INSERT INTO office_change_records
            (character_name, office_title, office_type, source, dossier_id,
             appointment_tenure, turn)
        VALUES (?, '旧职方司主事', '中央', 'prior-month', ?, '真除', ?)
        """,
        (minister, dossier_id, turn - 1),
    )
    db.conn.commit()

    issue_title = "问后核饷局"
    captured_feed = {}

    def supply_run(db_, state_, llm_config, chain):
        feed = month_chain.build_secret_orders_supply_feed(db_, state_, chain)
        captured_feed.update(feed)
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "顺利",
                "memorial_text": "边材考选有着落。",
            }],
            "covert_exec_selections": [{
                "order_id": order_id,
                "fidelity": "忠实",
                "note": "实办尽职",
            }],
        }

    def translate(*_a, **kwargs):
        if "问后考选" not in str(kwargs.get("segment") or ""):
            return {"effects": {}}
        return {"effects": {
            "economy_moves": [{
                "account": "内库", "delta": -2, "category": "密令差务",
                "purpose": "其它", "reason": "问后考选支银",
                "origin_ref": f"dossier:{dossier_id}",
            }],
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{dossier_id}",
                "title": issue_title,
                "kind": "situation",
            }],
            "人物变更": [{
                "origin_ref": f"dossier:{dossier_id}",
                "name": minister, "动作": "任命",
                "office": new_office, "office_type": "地方",
                "region_id": "shaanxi", "reason": "问后考选任免",
            }],
        }}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text", lambda *a, **k: "问后考选。",
    )
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()

    paused = session.resolve_turn(allow_empty_decree=True)
    assert paused.awaiting is True
    session.submit_hitl_choices(
        [_choice(session.pending_decisions()[0])], write_gate=session._write_gate,
    )
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"

    origin_effects = captured_feed.get("origin_effects") or {}
    issues = origin_effects.get("issues") or []
    assert any(
        str(row.get("title") or "") == issue_title and not row.get("rejected")
        for row in issues
    )
    person_rows = origin_effects.get("applied_person_changes") or []
    assert any(
        str(row.get("name") or "") == minister
        and str(row.get("new_office") or "") == new_office
        and not row.get("rejected")
        for row in person_rows
    )
    assert not any("旧职方司主事" in str(row) for row in person_rows)
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,),
    ).fetchone()["office"] == new_office
    commitments = db.list_commitments_for_dossier(dossier_id)
    assert any(str(row.get("title") or "") == issue_title for row in commitments)
    assert not hasattr(db, "list_this_turn_origin_effects")
    segments = (month_chain._load_chain(db, turn).get("segment_applied_results") or [])
    assert any(seg.get("kind") == "world_post" for seg in segments)


def test_step_4a_feed_keeps_rejections_out_of_origin_effects(game, monkeypatch):
    """问后续推：已落效果入 origin_effects；拒收另入 origin_rejections，不得冒充已落。

    覆盖 *_rejections 键、inline rejected 标记、以及 issue_summary 拒收同形入供料。
    """
    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    order_id = db.create_secret_order(
        state, minister, "辽饷清核", "查清兵部饷银", [],
        deadline_months=2,
        covert_task={
            "kind": "差务", "axes": ["实务事功"], "direction": 1,
            "delivery": {
                "unit": "万两", "target_units": 5.0, "effect_sign": -1,
                "purpose": "其它", "category": "密令差务", "account": "内库",
            },
        },
    )
    db.conn.execute(
        "UPDATE secret_orders SET turn_issued=? WHERE id=?",
        (turn - 1, order_id),
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.commit()

    captured_feed = {}

    def supply_run(db_, state_, llm_config, chain):
        feed = month_chain.build_secret_orders_supply_feed(db_, state_, chain)
        captured_feed.update(feed)
        return {
            "dossier_progress_reports": [{
                "dossier_id": dossier_id,
                "progress_band": "顺利",
                "memorial_text": "关外饷银如数盘点。",
            }],
            "covert_exec_selections": [{
                "order_id": order_id, "fidelity": "忠实", "note": "实办",
            }],
        }

    def translate(*_a, **kwargs):
        if "问后核银" not in str(kwargs.get("segment") or ""):
            return {"effects": {}}
        return {"effects": {
            "economy_moves": [{
                "account": "内库", "delta": -5, "category": "密令差务",
                "purpose": "其它", "reason": "问后实办内库出银",
                "origin_ref": f"dossier:{dossier_id}",
            }, {
                "account": "内库", "delta": -1, "category": "补饷坏目标",
                "purpose": "补饷", "reason": "查无此军",
                "target_kind": "army", "target_id": "no-such-army-1847-feed",
                "origin_ref": f"dossier:{dossier_id}",
            }],
            # inline rejected：人物变更写路径拒收 → applied_person_changes 带 rejected:True。
            "人物变更": [{
                "name": "查无此人1847-inline", "动作": "革职", "reason": "幻觉",
            }],
            # issue_summary.new_issues rejected：非预设 event_pool id。
            "new_issues": [{
                "origin_kind": "event_pool", "id": "no-such-event-1847-reject",
            }],
        }}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text", lambda *a, **k: "问后核银。",
    )
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_secret_orders_supply", supply_run)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session._write_gate = threading.Lock()

    paused = session.resolve_turn(allow_empty_decree=True)
    assert paused.awaiting is True
    session.submit_hitl_choices(
        [_choice(session.pending_decisions()[0])], write_gate=session._write_gate,
    )
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"

    origin_effects = captured_feed.get("origin_effects") or {}
    eco_moves = origin_effects.get("economy_moves") or []
    assert any(
        m.get("origin_ref") == f"dossier:{dossier_id}" and int(m.get("delta") or 0) == -5
        for m in eco_moves
    )
    assert not any("no-such-army-1847-feed" in str(m) for m in eco_moves)
    # inline rejected 不得冒充已落人物效果。
    assert not any(
        "查无此人1847-inline" in str(row) for row in (origin_effects.get("applied_person_changes") or [])
    )
    assert "issues" not in origin_effects or not any(
        row.get("rejected") or "no-such-event-1847-reject" in str(row)
        for row in (origin_effects.get("issues") or [])
    )
    rejections = captured_feed.get("origin_rejections") or []
    assert any(
        "no-such-army-1847-feed" in str(row.get("item") or row)
        for row in rejections
    )
    assert any(
        "查无此人1847-inline" in str(row.get("item") or row)
        for row in rejections
    ), rejections
    assert any(
        "no-such-event-1847-reject" in str(row.get("item") or row)
        or (
            str(row.get("section") or "") == "issues"
            and "非预设" in str(row.get("reason") or "")
        )
        for row in rejections
    ), rejections
    # entity_rejections 与 13 键同形入 origin_rejections（不静默丢）。
    _fx, entity_rejs = month_chain._aggregate_origin_from_segment_results([{
        "kind": "world_post",
        "applied": [{"issue_summary": {
            "entity_rejections": [{
                "item": {"account": "国库", "delta": -1},
                "reason": "坏目标",
                "category": "missing_ref",
            }],
        }}],
        "rejections": [],
    }])
    assert any(
        str(row.get("section") or "") == "entity_rejections"
        and "国库" in str(row.get("item") or row)
        for row in entity_rejs
    )
    assert db.sum_dossier_actual_progress_units(dossier_id) == 5.0


def test_segment_applied_results_share_commit_boundary_with_effects(game, monkeypatch):
    """效果应用与 segment_applied_results 同提交边界：alongside 失败则效果与段结果皆不半落。"""
    from types import SimpleNamespace

    from ming_sim.declaration_dispatch import stage_declaration
    from ming_sim.decree_forecast import pending_action_decree_ref
    from ming_sim.month_chain import _settle_edicts

    db, state, content = game
    turn = int(state.turn)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    treasury_before = int(state.metrics["国库"])
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "segment-result-atomic", "actor": minister, "mode": "ordinary",
            "text": "段结果原子探针",
        },
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="段结果原子探针",
        target_kind="issue", target_id="segment-result-atomic",
        pending_action_id=pending_id,
        payload={"text": "段结果原子探针"},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='promulgated', promulgation_decision='promulgated' "
        "WHERE id=?",
        (dossier_id,),
    )
    ref = pending_action_decree_ref(pending_id, 1)
    stage_declaration(
        db, decree_ref=ref, turn=turn,
        declaration={"effects": {"economy_moves": [{
            "origin_ref": f"dossier:{dossier_id}",
            "account": "国库", "delta": -17, "category": "段结果探针",
            "reason": "atomic segment result probe",
        }]}},
        verdict={"decision": "promulgated"},
        visible_refs={"issues": [], "affairs": [], "dossiers": [dossier_id]},
    )
    db.conn.commit()

    sess = SimpleNamespace(
        db=db, state=state, llm_config=None, agno_db=None, content=content,
    )
    chain: dict = {}
    real_save = month_chain._save_chain

    def boom_save(db_, turn_, chain_, **kwargs):
        segments = chain_.get("segment_applied_results") or []
        if any(seg.get("kind") == "decree_pre" for seg in segments):
            raise RuntimeError("injected segment result save failure")
        return real_save(db_, turn_, chain_, **kwargs)

    monkeypatch.setattr(month_chain, "_save_chain", boom_save)
    with pytest.raises(RuntimeError, match="injected segment result save failure"):
        _settle_edicts(sess, registry=None, chain=chain)

    assert not db.staged_declarations.is_settled(ref)
    assert int(state.metrics["国库"]) == treasury_before
    reloaded = month_chain._load_chain(db, turn)
    assert not (reloaded.get("segment_applied_results") or [])

    monkeypatch.setattr(month_chain, "_save_chain", real_save)
    _settle_edicts(sess, registry=None, chain={})
    assert db.staged_declarations.is_settled(ref)
    assert int(state.metrics["国库"]) == treasury_before - 17
    segments = month_chain._load_chain(db, turn).get("segment_applied_results") or []
    decree_pre = [s for s in segments if s.get("kind") == "decree_pre"]
    assert len(decree_pre) == 1
    applied = decree_pre[0].get("applied") or []
    assert any(
        any(int(m.get("delta") or 0) == -17 for m in (rep.get("economy_moves") or []))
        for rep in applied if isinstance(rep, dict)
    )
