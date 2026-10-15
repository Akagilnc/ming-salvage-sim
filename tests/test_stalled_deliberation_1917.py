"""#1917：月末转译声明「无人站台」→ 原案标记、批红两选、御笔强推／留中。"""
from __future__ import annotations

import copy

import pytest

from tests.month_chain_helpers import canned_full_settlement, make_light_session
from tests.test_web_audience_night_498 import _fake_settlement_llm


_ROSTER = [{
    "character_id": "毕自严", "tier": "主办", "role": "总核", "delegator_id": None,
}]


def _plant_proposed_decree(db, state, *, title="廷议原案"):
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=title,
        target_kind="issue",
        target_id=f"deliberation-case-{state.turn}",
        payload={
            "dossier_action_type": "policy",
            "mode": "ordinary",
            "target_kind": "issue",
            "target_id": f"deliberation-case-{state.turn}",
            "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
        },
    )
    return int(did)


def test_month_translate_stalled_marks_dossier_and_opens_rescript_desk(game, monkeypatch):
    """经真实过月入口：转译声明无人站台后，原案 stalled、不颁布，批红出现两选。"""
    db, state, content = game
    did = _plant_proposed_decree(db, state, title="议饷无人")
    note = "廷议冷场，无大臣肯站台"

    def translate(request, config=None):
        return {
            "effects": {
                "deliberation_outcomes": [{
                    "dossier_id": did,
                    "outcome": "stalled",
                    "note": note,
                }],
            },
        }

    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(
        "ming_sim.month_translate._default_month_translate_runner", translate,
    )
    session = make_light_session(db, state, content)
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.awaiting is True
    row = db.dossiers.get(did)
    assert row["status"] == "proposed"
    assert row["payload"].get("deliberation_state") == "stalled"
    assert not db.dossiers.authorizes_effects(did)
    issue = db.conn.execute(
        "SELECT id, status, title FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone()
    assert issue is not None
    desk = session.pending_decisions()
    event = next(r for r in desk if r["event_id"] == f"deliberation:{did}")
    actions = {opt.get("action") for opt in event["options"]}
    assert actions == {"imperial_push", "hold"}


def test_imperial_push_reuses_stalled_original(game, monkeypatch):
    """选御笔强推：原案追加御笔手敕、backed、照常颁布，不另建案卷。"""
    db, state, content = game
    did = _plant_proposed_decree(db, state, title="强推原案")
    db.dossiers.update_payload(
        did, {**db.dossiers.get(did)["payload"], "deliberation_state": "stalled"},
    )
    db.insert_issue(
        state, kind="situation", title="强推原案",
        origin_kind="deliberation", origin_ref=f"dossier:{did}",
    )
    _fake_settlement_llm(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    row = next(r for r in session.pending_decisions() if r["event_id"] == f"deliberation:{did}")
    choice = {
        "decision_key": row["decision_key"],
        "action": "imperial_push",
        "note": "朕独担此旨",
    }
    before_ids = {int(d["id"]) for d in db.dossiers.list_dossiers()}
    session.submit_hitl_choices([choice], write_gate=session._write_gate)
    pushed = db.dossiers.get(did)
    assert pushed["payload"]["deliberation_state"] == "backed"
    assert pushed["payload"]["imperial_push_note"] == choice["note"]
    assert pushed["promulgation_decision"] == "promulgated"
    assert pushed["status"] != "proposed"
    assert {int(d["id"]) for d in db.dossiers.list_dossiers()} == before_ids
    endorsements = db.dossiers.endorsements(did)
    assert len(endorsements) == 1
    assert endorsements[0]["form"] == "御笔手敕"
    assert endorsements[0]["decision_key"] == choice["decision_key"]
    assert int(endorsements[0]["source_chat_turn_id"] or 0) == 0
    assert not db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone()


def test_hold_keeps_stalled_original_and_ends_wait(game, monkeypatch):
    """选留中：原案留存 stalled，本次等待结束。"""
    db, state, content = game
    did = _plant_proposed_decree(db, state, title="留中原案")
    db.dossiers.update_payload(
        did, {**db.dossiers.get(did)["payload"], "deliberation_state": "stalled"},
    )
    db.insert_issue(
        state, kind="situation", title="留中原案",
        origin_kind="deliberation", origin_ref=f"dossier:{did}",
    )
    _fake_settlement_llm(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    row = next(r for r in session.pending_decisions() if r["event_id"] == f"deliberation:{did}")
    choice = {"decision_key": row["decision_key"], "action": "hold", "note": "暂留"}
    result = session.submit_hitl_choices([choice], write_gate=session._write_gate)
    kept = db.dossiers.get(did)
    assert kept["status"] == "proposed"
    assert kept["payload"].get("deliberation_state") == "stalled"
    assert not db.dossiers.authorizes_effects(did)
    assert db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone() is not None
    # 本次等待结束：同 key 已答，不再阻塞当月（无其它案头则非 awaiting）。
    answered = db.issues.get_rescript_desk_rows_by_keys([choice["decision_key"]])
    assert answered and answered[0]["choice"]
    assert result.awaiting is False or not any(
        r["event_id"] == f"deliberation:{did}" and not r.get("choice")
        for r in session.pending_decisions()
    )


def test_deliberation_outcome_rejects_non_proposed(game):
    """只有 proposed 原案可被标为无人站台。"""
    from ming_sim.applier import Provenance
    from ming_sim.settlement.run import SettlementContext, settle_delta
    from ming_sim.settlement.views import section

    db, state, content = game
    did = _plant_proposed_decree(db, state)
    db.dossiers.record_dossier_decision(did, "promulgated")
    result = settle_delta(
        state, db,
        {"deliberation_outcomes": [{
            "dossier_id": did, "outcome": "stalled", "note": "冷场",
        }]},
        SettlementContext(content=content, source=Provenance.system_simulation),
    )
    rejected = section(result, "deliberation_outcomes").rejected
    assert rejected
    assert db.dossiers.get(did)["payload"].get("deliberation_state") != "stalled"
