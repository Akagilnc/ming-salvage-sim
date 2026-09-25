"""#1847：请旨停在问处 → 批红案头统一收口 → 答复后续推。

沿既有 HITL / pending_decisions / month_chain 接缝，不另造平行机制。
LLM 外缝可打；续推函数本身保持真实实现。
"""

from __future__ import annotations

import json
import threading

import ming_sim.declaration_dispatch as declaration_dispatch
import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
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

    real_dispatch = declaration_dispatch.dispatch_declaration

    def spy_dispatch(db_, state_, declaration, *, source):
        dispatch_count.append(dict(declaration) if isinstance(declaration, dict) else declaration)
        return real_dispatch(db_, state_, declaration, source=source)

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
    monkeypatch.setattr(declaration_dispatch, "dispatch_declaration", spy_dispatch)

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
