"""#1917：月末转译声明「无人站台」→ 原案标记、批红两选、御笔强推／留中。

贯穿：pending-action 本旨身份暂存声明 → resolve_turn 真入口 → 案头 → 选择后结构化结果。
"""
from __future__ import annotations

import copy

import pytest

from ming_sim.declaration_dispatch import pending_action_decree_ref, stage_declaration
from tests.month_chain_helpers import canned_full_settlement, make_light_session
from tests.test_web_audience_night_498 import _fake_settlement_llm


_ROSTER = [{
    "character_id": "毕自严", "tier": "主办", "role": "总核", "delegator_id": None,
}]


def _minister_name(db) -> str:
    return db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()[0]


def _plant_proposed_with_pending_stalled_stage(db, state, *, title="廷议原案"):
    """真实生产前置：案卷挂 pending_action，暂存声明用 pending-action 本旨身份写 stalled。"""
    minister = _minister_name(db)
    pending_id = int(db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": f"deliberation-case-{state.turn}",
            "actor": minister,
            "mode": "ordinary",
            "text": title,
            "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
        },
    ))
    did = int(db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=title,
        target_kind="issue",
        target_id=f"deliberation-case-{state.turn}",
        pending_action_id=pending_id,
        payload={
            "dossier_action_type": "policy",
            "mode": "ordinary",
            "target_kind": "issue",
            "target_id": f"deliberation-case-{state.turn}",
            "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
            "text": title,
        },
    ))
    # 已成案：pending 标 committed，避免 resolve_turn 再提交造第二案卷。
    db.conn.execute(
        "UPDATE pending_actions SET status='committed' WHERE id=?", (pending_id,),
    )
    ref = pending_action_decree_ref(pending_id, 1)
    # 夜里预推形态：本旨身份是 pending-action ref，不是成案后的整数 id。
    stage_declaration(
        db,
        decree_ref=ref,
        turn=int(state.turn),
        declaration={
            "effects": {
                "deliberation_outcomes": [{
                    "dossier_id": ref,
                    "outcome": "stalled",
                    "note": "廷议冷场，无大臣肯站台",
                }],
            },
        },
        verdict={"decision": "promulgated"},
        visible_refs={"dossiers": [], "affairs": [], "issues": []},
    )
    db.conn.commit()
    return did, ref


def test_month_entry_stalled_declaration_opens_desk_not_promulgated(game, monkeypatch):
    """经真实过月入口：pending-action 身份 stalled 声明 → 原案 stalled、不颁布、案头两选。"""
    db, state, content = game
    did, ref = _plant_proposed_with_pending_stalled_stage(db, state, title="议饷无人")
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.awaiting is True
    row = db.dossiers.get(did)
    assert row["status"] == "proposed"
    assert row["payload"].get("deliberation_state") == "stalled"
    assert not row.get("promulgation_decision")
    assert not db.dossiers.authorizes_effects(did)
    assert db.staged_declarations.is_settled(ref)
    issue = db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone()
    assert issue is not None
    event = next(
        r for r in session.pending_decisions()
        if r["event_id"] == f"deliberation:{did}"
    )
    assert {opt.get("action") for opt in event["options"]} == {"imperial_push", "hold"}


def test_month_entry_stalled_then_imperial_push_promulgates_same_dossier(game, monkeypatch):
    """贯通：生产 stalled → 案头强推 → backed + 颁布，旧声明不回写，不另建案卷。"""
    db, state, content = game
    did, ref = _plant_proposed_with_pending_stalled_stage(db, state, title="强推原案")
    _fake_settlement_llm(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    assert db.dossiers.get(did)["payload"].get("deliberation_state") == "stalled"
    assert db.staged_declarations.is_settled(ref)
    row = next(
        r for r in session.pending_decisions()
        if r["event_id"] == f"deliberation:{did}"
    )
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
    assert not db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone()
    # 旧 stalled 声明已消费，不得把强推结果打回 stalled。
    assert pushed["payload"].get("deliberation_state") == "backed"


def test_month_entry_stalled_then_hold_keeps_original(game, monkeypatch):
    """贯通：生产 stalled → 留中 → 原案留存，本次等待结束。"""
    db, state, content = game
    did, ref = _plant_proposed_with_pending_stalled_stage(db, state, title="留中原案")
    _fake_settlement_llm(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    row = next(
        r for r in session.pending_decisions()
        if r["event_id"] == f"deliberation:{did}"
    )
    choice = {"decision_key": row["decision_key"], "action": "hold", "note": "暂留"}
    result = session.submit_hitl_choices([choice], write_gate=session._write_gate)
    kept = db.dossiers.get(did)
    assert kept["status"] == "proposed"
    assert kept["payload"].get("deliberation_state") == "stalled"
    assert not kept.get("promulgation_decision")
    assert not db.dossiers.authorizes_effects(did)
    assert db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone() is not None
    assert db.staged_declarations.is_settled(ref)
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
    minister = _minister_name(db)
    did = int(db.create_decree_dossier(
        state, action_type="policy", decree_text="已颁",
        target_kind="issue", target_id="done",
        payload={"text": "已颁", "actor": minister},
    ))
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


def test_bad_stalled_item_does_not_swallow_other_effects(game, monkeypatch):
    """F5：stalled 坏项拒收留痕，不 mark settled，合法 economy_moves 仍可落。"""
    db, state, content = game
    minister = _minister_name(db)
    pending_id = int(db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "bad-stalled", "actor": minister, "mode": "ordinary",
            "text": "坏项探针", "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
        },
    ))
    did = int(db.create_decree_dossier(
        state, action_type="policy", decree_text="坏项探针",
        target_kind="issue", target_id="bad-stalled",
        pending_action_id=pending_id,
        payload={
            "dossier_action_type": "policy", "mode": "ordinary",
            "target_kind": "issue", "target_id": "bad-stalled",
            "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER), "text": "坏项探针",
        },
    ))
    db.conn.execute(
        "UPDATE pending_actions SET status='committed' WHERE id=?", (pending_id,),
    )
    ref = pending_action_decree_ref(pending_id, 1)
    before = int(state.metrics["国库"])
    stage_declaration(
        db, decree_ref=ref, turn=int(state.turn),
        declaration={
            "effects": {
                # note 空 → stalled 拒收
                "deliberation_outcomes": [{
                    "dossier_id": ref, "outcome": "stalled", "note": "",
                }],
                "economy_moves": [{
                    "origin_ref": ref, "account": "国库", "delta": -3,
                    "category": "坏项旁合法支出", "reason": "应落",
                }],
            },
        },
        verdict={"decision": "promulgated"},
        visible_refs={"dossiers": [], "affairs": [], "issues": []},
    )
    db.conn.commit()
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.resolve_turn(allow_empty_decree=True)
    row = db.dossiers.get(did)
    # 坏 stalled 不得拦颁布；合法支出须落；拒收留痕。
    assert row["payload"].get("deliberation_state") != "stalled"
    assert db.dossiers.authorizes_effects(did)
    assert db.staged_declarations.is_settled(ref)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='坏项旁合法支出'",
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE category='坏项旁合法支出'",
    ).fetchone()[0] == -3
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='deliberation_outcomes'",
    ).fetchone()[0] >= 1
    del before  # 国库另有月初财政 tick，不以总额断言


def test_imperial_push_uses_real_promulgation_judge(game, monkeypatch):
    """F6：强推后接回现行颁布关，不伪造顺颁；判官可打回。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    did, ref = _plant_proposed_with_pending_stalled_stage(db, state, title="强推过判")
    judge_calls: list = []

    def reject_all(dossiers, *a, **k):
        judge_calls.append([int(r["id"]) for r in dossiers])
        prepared = k.get("prepared_context") or decree_mod.build_promulgation_judge_context(
            db, state, list(dossiers),
        )
        by_id = {int(item["id"]): item for item in prepared.get("dossiers") or []}
        faction = db.conn.execute("SELECT name FROM factions LIMIT 1").fetchone()["name"]
        out = []
        for row in dossiers:
            did_i = int(row["id"])
            src = (by_id.get(did_i) or {}).get("criteria_snapshot_source") or {
                "imperial_authority_band": "中等",
                "appointment_tenure": "",
                "authorization_ids": [],
                "endorsement_entry_ids": [],
            }
            out.append({
                "dossier_id": did_i,
                "decision": "rejected",
                "blocked_layer": "six_offices",
                "reason": "科道封驳",
                "primary_opponents": [{"kind": "faction", "key": faction}],
                "affected_parties": [{
                    "kind": "faction", "key": faction,
                    "direction": "negative", "intensity": "weak",
                }],
                "gatekeeper_id": None,
                "criteria_snapshot": src,
            })
        return out

    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", reject_all)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    assert db.dossiers.get(did)["payload"].get("deliberation_state") == "stalled"
    row = next(
        r for r in session.pending_decisions()
        if r["event_id"] == f"deliberation:{did}"
    )
    session.submit_hitl_choices(
        [{
            "decision_key": row["decision_key"],
            "action": "imperial_push",
            "note": "朕独担",
        }],
        write_gate=session._write_gate,
    )
    pushed = db.dossiers.get(did)
    assert pushed["payload"]["deliberation_state"] == "backed"
    assert judge_calls and did in judge_calls[0]
    # 判官打回：不得被默认顺颁洗成 promulgated。
    assert pushed.get("promulgation_decision") == "rejected"
    assert pushed["status"] == "proposed"
    assert not db.dossiers.authorizes_effects(did)
