"""#1847：请旨停在问处 → 批红案头统一收口 → 答复后续推。

沿既有 HITL / pending_decisions / month_chain 接缝，不另造平行机制。
LLM 外缝可打；续推函数本身保持真实实现。
"""

from __future__ import annotations

import json
import threading

import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import TurnPhase
from tests.settlement_seam_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor, _stage_edict


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
    affair = db.affairs.open(
        name="打回三选", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    pending_id, ref = _stage_edict(db, state, minister, "河工", "河工", -1, affair.id)
    # 预推打回：过月落判决后应进批红三选，不得直接落账。
    db.conn.execute(
        "UPDATE staged_declarations SET verdict_json=? WHERE decree_ref=?",
        (json.dumps({
            "decision": "rejected",
            "reason": "科参未允",
            "blocked_layer": "six_offices",
            "primary_opponents": [{"kind": "faction", "key": "东林"}],
        }, ensure_ascii=False), ref),
    )
    db.conn.commit()
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


def test_answering_triad_applies_and_releases_rescript_gate(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="收回放行", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    pending_id, ref = _stage_edict(db, state, minister, "河工", "河工", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET verdict_json=? WHERE decree_ref=?",
        (json.dumps({
            "decision": "rejected",
            "reason": "科参未允",
            "blocked_layer": "six_offices",
            "primary_opponents": [{"kind": "faction", "key": "东林"}],
        }, ensure_ascii=False), ref),
    )
    db.conn.commit()
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
