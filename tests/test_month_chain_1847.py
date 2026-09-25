"""#1847：请旨停在问处 → 批红案头统一收口 → 答复后续推。

沿既有 HITL / pending_decisions / month_chain 接缝，不另造平行机制。
"""

from __future__ import annotations

import json
import threading

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
    db, state, content = game
    closed_turn = int(state.turn)
    continues = []
    translates = []

    def world(*_a, **_k):
        return _WORLD_WITH_QUESTION

    def translate(*_a, **kwargs):
        translates.append(kwargs.get("segment") or _a[2] if len(_a) > 2 else kwargs)
        return {"effects": {"economy_moves": [{
            "origin_ref": "affair:world-q", "account": "国库", "delta": -1,
            "category": "宁远续援", "reason": "准调关宁后落账",
        }]}} if continues else {"effects": {}}

    def continue_world(session, chain, *, answers, source):
        continues.append(list(answers))
        # 续推只交问后声明；前缀已落、世界段不重推。
        from ming_sim.month_translate import dispatch_month_segment
        from ming_sim.applier import Provenance
        result = dispatch_month_segment(
            session.db, session.state, segment="准调关宁，关宁增戍。",
            llm_config=session.llm_config, source=source or Provenance.system_simulation,
        )
        chain["world_questions"] = []
        chain["world_continued"] = True
        month_chain._save_chain(session.db, int(session.state.turn), chain, source=source)
        return result

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_translate, "translate_month_segment",
                        lambda *a, **k: {"effects": {}})
    monkeypatch.setattr(month_chain, "continue_world_after_answers", continue_world)
    session = make_light_session(db, state, content)
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

    assert continues and continues[0][0]["label"] == choice["label"]
    assert session.state.turn_phase == TurnPhase.SETTLING.value
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_questions") in (None, [], ())
    assert chain.get("world_continued") is True
    again = session.resolve_turn(allow_empty_decree=True)
    assert again.stage == "gazette"
    assert again.awaiting is False


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
