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


def test_mixed_stalled_items_record_rejection_once_and_settle(game, monkeypatch):
    """F5：同批合法+非法 stalled，成功落标并记坏项拒收一次，整旨 settled。"""
    db, state, content = game
    minister = _minister_name(db)
    pending_id = int(db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "mixed-stalled", "actor": minister, "mode": "ordinary",
            "text": "混合探针", "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
        },
    ))
    did = int(db.create_decree_dossier(
        state, action_type="policy", decree_text="混合探针",
        target_kind="issue", target_id="mixed-stalled",
        pending_action_id=pending_id,
        payload={
            "dossier_action_type": "policy", "mode": "ordinary",
            "target_kind": "issue", "target_id": "mixed-stalled",
            "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER), "text": "混合探针",
        },
    ))
    db.conn.execute(
        "UPDATE pending_actions SET status='committed' WHERE id=?", (pending_id,),
    )
    ref = pending_action_decree_ref(pending_id, 1)
    stage_declaration(
        db, decree_ref=ref, turn=int(state.turn),
        declaration={
            "effects": {
                "deliberation_outcomes": [
                    {"dossier_id": ref, "outcome": "stalled", "note": "合法冷场"},
                    {"dossier_id": ref, "outcome": "stalled", "note": ""},
                ],
            },
        },
        verdict={"decision": "promulgated"},
        visible_refs={"dossiers": [], "affairs": [], "issues": []},
    )
    db.conn.commit()
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    row = db.dossiers.get(did)
    assert row["payload"].get("deliberation_state") == "stalled"
    assert not db.dossiers.authorizes_effects(did)
    assert db.staged_declarations.is_settled(ref)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='deliberation_outcomes'",
    ).fetchone()[0] == 1


def test_imperial_push_reuses_persisted_verdict_without_rejudge(game, monkeypatch):
    """F6：强推复用已持久判决，不重开判官（#1846）。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    did, ref = _plant_proposed_with_pending_stalled_stage(db, state, title="强推复用判决")
    judge_calls: list = []

    def track_judge(dossiers, *a, **k):
        judge_calls.append([int(r["id"]) for r in dossiers])
        return [
            {"dossier_id": int(row["id"]), "decision": "promulgated"}
            for row in dossiers
        ]

    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", track_judge)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
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
    assert pushed.get("promulgation_decision") == "promulgated"
    # 预推已持久 verdict=promulgated；强推不得再调判官。
    assert judge_calls == []


def test_imperial_push_without_model_does_not_stub_promulgate(game, monkeypatch):
    """F6：缺模型且需外廷过判时，不得 stub 自动顺颁。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    minister = _minister_name(db)
    pending_id = int(db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "no-model-push", "actor": minister, "mode": "ordinary",
            "text": "缺模型强推", "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
        },
    ))
    did = int(db.create_decree_dossier(
        state, action_type="policy", decree_text="缺模型强推",
        target_kind="issue", target_id="no-model-push",
        pending_action_id=pending_id,
        payload={
            "dossier_action_type": "policy", "mode": "ordinary",
            "target_kind": "issue", "target_id": "no-model-push",
            "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER), "text": "缺模型强推",
        },
    ))
    db.conn.execute(
        "UPDATE pending_actions SET status='committed' WHERE id=?", (pending_id,),
    )
    ref = pending_action_decree_ref(pending_id, 1)
    # 无 verdict：强推后必须过判，缺模型不得 stub。
    stage_declaration(
        db, decree_ref=ref, turn=int(state.turn),
        declaration={
            "effects": {
                "deliberation_outcomes": [{
                    "dossier_id": ref, "outcome": "stalled", "note": "无人站台",
                }],
            },
        },
        verdict=None,
        visible_refs={"dossiers": [], "affairs": [], "issues": []},
    )
    db.conn.commit()
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    assert db.dossiers.get(did)["payload"].get("deliberation_state") == "stalled"
    row = next(
        r for r in session.pending_decisions()
        if r["event_id"] == f"deliberation:{did}"
    )
    from ming_sim.month_chain import _persisted_staged_verdict
    assert _persisted_staged_verdict(db, ref, int(state.turn)) is None
    # 强推续跑时去掉模型配置。
    session.llm_config = None
    with pytest.raises(SettlementAbort, match="缺少模型配置"):
        session.submit_hitl_choices(
            [{
                "decision_key": row["decision_key"],
                "action": "imperial_push",
                "note": "朕独担",
            }],
            write_gate=session._write_gate,
        )
    kept = db.dossiers.get(did)
    assert kept["payload"]["deliberation_state"] == "backed"
    assert not kept.get("promulgation_decision")
    assert not db.dossiers.authorizes_effects(did)
