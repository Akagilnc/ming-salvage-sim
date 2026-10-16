"""#1917：月末转译声明「无人站台」→ 原案标记、批红两选、御笔强推／留中。

贯穿：pending-action 本旨身份暂存声明 → resolve_turn 真入口 → 案头 → 选择后结构化结果。
"""
from __future__ import annotations

import copy

import pytest

from ming_sim.applier import Provenance
from ming_sim.declaration_dispatch import pending_action_decree_ref, stage_declaration
from ming_sim.month_chain import _DECREE_QUESTION_PREFIX, _load_chain, _save_chain
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


def _plant_proposed(db, state, *, title="廷议原案", target_id=None):
    """成案 + pending-action 本旨身份；不暂存声明。"""
    minister = _minister_name(db)
    tid = target_id or f"deliberation-case-{state.turn}-{title}"
    pending_id = int(db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": tid, "actor": minister, "mode": "ordinary",
            "text": title, "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER),
        },
    ))
    did = int(db.create_decree_dossier(
        state, action_type="policy", decree_text=title,
        target_kind="issue", target_id=tid, pending_action_id=pending_id,
        payload={
            "dossier_action_type": "policy", "mode": "ordinary",
            "target_kind": "issue", "target_id": tid, "locality_scope": "none",
            "participant_roster": copy.deepcopy(_ROSTER), "text": title,
        },
    ))
    db.conn.execute(
        "UPDATE pending_actions SET status='committed' WHERE id=?", (pending_id,),
    )
    return did, pending_action_decree_ref(pending_id, 1)


def _stage(db, state, ref, declaration, *, verdict="promulgated", questions=None):
    kwargs = {
        "db": db, "decree_ref": ref, "turn": int(state.turn),
        "declaration": declaration,
        "visible_refs": {"dossiers": [], "affairs": [], "issues": []},
    }
    if verdict == "promulgated":
        kwargs["verdict"] = {"decision": "promulgated"}
    elif verdict is not None:
        kwargs["verdict"] = verdict
    if questions is not None:
        kwargs["questions"] = questions
    stage_declaration(**kwargs)
    db.conn.commit()


def _stage_stalled(db, state, ref, *, note="廷议冷场，无大臣肯站台", verdict="promulgated"):
    _stage(db, state, ref, {
        "effects": {
            "deliberation_outcomes": [{
                "dossier_id": ref, "outcome": "stalled", "note": note,
            }],
        },
    }, verdict=verdict)


def _deliberation_desk_row(session, did: int):
    return next(
        r for r in session.pending_decisions()
        if r["event_id"] == f"deliberation:{did}"
    )


def _seed_continuation(db, state, monkeypatch, row, declaration):
    chain = _load_chain(db, int(state.turn))
    chain.setdefault("rescript_continuation_texts", {})[row["event_id"]] = "续。"
    _save_chain(db, int(state.turn), chain, source=Provenance.player_decree)
    monkeypatch.setattr(
        "ming_sim.month_translate._default_month_translate_runner",
        lambda *_a, **_k: declaration,
    )


def test_month_entry_stalled_then_imperial_push_promulgates_same_dossier(game, monkeypatch):
    """贯通：生产 stalled 开案头两选 → 强推 backed+颁布；旧声明不回写，不另建案卷；不重开判官。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    did, ref = _plant_proposed(db, state, title="强推原案")
    _stage_stalled(db, state, ref)
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
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.awaiting is True
    stalled = db.dossiers.get(did)
    assert stalled["status"] == "proposed"
    assert stalled["payload"].get("deliberation_state") == "stalled"
    assert not stalled.get("promulgation_decision")
    assert not db.dossiers.authorizes_effects(did)
    assert db.staged_declarations.is_settled(ref)
    assert db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone() is not None
    row = _deliberation_desk_row(session, did)
    assert {opt.get("action") for opt in row["options"]} == {"imperial_push", "hold"}
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
    assert judge_calls == []


def test_month_entry_stalled_then_hold_keeps_original(game, monkeypatch):
    """贯通：生产 stalled → 留中 → 原案留存，本次等待结束（无新案头）。"""
    db, state, content = game
    did, ref = _plant_proposed(db, state, title="留中原案")
    _stage_stalled(db, state, ref)
    _fake_settlement_llm(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    row = _deliberation_desk_row(session, did)
    choice = {"decision_key": row["decision_key"], "action": "hold", "note": "暂留"}
    result = session.submit_hitl_choices([choice], write_gate=session._write_gate)
    kept = db.dossiers.get(did)
    assert kept["status"] == "proposed"
    assert kept["payload"].get("deliberation_state") == "held"
    assert not any(
        str(r.get("event_id") or "").startswith(f"deliberation:{did}")
        and str(r.get("status") or "") == "pending"
        for r in session.pending_decisions()
    )
    assert db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? AND status='active'",
        (f"dossier:{did}",),
    ).fetchone() is None
    assert db.staged_declarations.is_settled(ref)
    answered = db.issues.get_rescript_desk_rows_by_keys([choice["decision_key"]])
    assert answered and answered[0]["choice"]
    assert result.awaiting is False or not result.decisions


def test_hold_then_restall_push_does_not_replay_old_hold(game, monkeypatch):
    """C7：历史留中不重消费；再次 stalled 后新强推可兑现。"""
    db, state, content = game
    did, ref = _plant_proposed(db, state, title="留中再 stalled", target_id="hold-restall")
    _stage(db, state, ref, {"effects": {}}, questions=[
        {"title": "问一", "context": "c", "options": [{"label": "甲", "hint": "h"}]},
        {"title": "问二", "context": "c", "options": [{"label": "丙", "hint": "h"}]},
    ])
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting

    q1 = next(
        r for r in session.pending_decisions()
        if str(r.get("event_id") or "").startswith(_DECREE_QUESTION_PREFIX)
    )
    _seed_continuation(db, state, monkeypatch, q1, {"effects": {"deliberation_outcomes": [{
        "dossier_id": did, "outcome": "stalled", "note": "先冷场",
    }]}})
    session.submit_hitl_choices([
        {"decision_key": q1["decision_key"], "label": "甲", "note": "答一"},
    ], write_gate=session._write_gate)
    desk1 = [
        r for r in session.pending_decisions()
        if str(r.get("status") or "") == "pending"
        and str(r.get("event_id") or "").startswith(f"deliberation:{did}")
    ]
    assert desk1
    session.submit_hitl_choices([
        {"decision_key": desk1[0]["decision_key"], "action": "hold", "note": "先留中"},
    ], write_gate=session._write_gate)
    assert db.dossiers.get(did)["payload"].get("deliberation_state") == "held"

    q2 = next(
        r for r in session.pending_decisions()
        if str(r.get("event_id") or "").startswith(_DECREE_QUESTION_PREFIX)
        and not r.get("choice")
    )
    _seed_continuation(db, state, monkeypatch, q2, {"effects": {"deliberation_outcomes": [{
        "dossier_id": did, "outcome": "stalled", "note": "再冷场",
    }]}})
    session.submit_hitl_choices([
        {"decision_key": q2["decision_key"], "label": "丙", "note": "答二"},
    ], write_gate=session._write_gate)
    desk2 = [
        r for r in session.pending_decisions()
        if str(r.get("status") or "") == "pending"
        and str(r.get("event_id") or "").startswith(f"deliberation:{did}")
    ]
    assert desk2
    session.submit_hitl_choices([
        {
            "decision_key": desk2[0]["decision_key"],
            "action": "imperial_push",
            "note": "后道强推",
        },
    ], write_gate=session._write_gate)
    pushed = db.dossiers.get(did)
    assert pushed["payload"].get("deliberation_state") == "backed"
    assert pushed["status"] != "proposed"
    assert any(
        e.get("decision_key") == desk2[0]["decision_key"]
        for e in db.dossiers.endorsements(did)
    )


def test_deliberation_outcome_rejects_missing_dossier(game):
    """不存在的案卷不可标无人站台。"""
    from ming_sim.settlement.run import SettlementContext, settle_delta
    from ming_sim.settlement.views import section

    db, state, content = game
    result = settle_delta(
        state, db,
        {"deliberation_outcomes": [{
            "dossier_id": 10**9, "outcome": "stalled", "note": "冷场",
        }]},
        SettlementContext(content=content, source=Provenance.system_simulation),
    )
    rejected = section(result, "deliberation_outcomes").rejected
    assert rejected


@pytest.mark.parametrize(
    "bad_item,spend_category,spend_delta",
    [
        (
            {"dossier_id": "__ref__", "outcome": "stalled", "note": ""},
            "坏项旁合法支出",
            -3,
        ),
        (
            {"dossier_id": float("inf"), "outcome": "stalled", "note": "冷场"},
            "坏编号旁合法支出",
            -2,
        ),
    ],
    ids=["empty_note", "bad_dossier_id"],
)
def test_bad_stalled_item_does_not_swallow_other_effects(
    game, monkeypatch, bad_item, spend_category, spend_delta,
):
    """F5/C2：不同负向 stalled 输入共用主干——拒收恰好一次，合法支出仍落，不中止整月。"""
    db, state, content = game
    did, ref = _plant_proposed(
        db, state, title=f"坏项-{spend_category}", target_id=f"bad-{spend_category}",
    )
    item = dict(bad_item)
    if item.get("dossier_id") == "__ref__":
        item["dossier_id"] = ref
    _stage(db, state, ref, {
        "effects": {
            "deliberation_outcomes": [item],
            "economy_moves": [{
                "origin_ref": ref, "account": "国库", "delta": spend_delta,
                "category": spend_category, "reason": "应落",
            }],
        },
    })
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.resolve_turn(allow_empty_decree=True)
    row = db.dossiers.get(did)
    assert row["payload"].get("deliberation_state") != "stalled"
    assert db.dossiers.authorizes_effects(did)
    assert db.staged_declarations.is_settled(ref)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category=?",
        (spend_category,),
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE category=?",
        (spend_category,),
    ).fetchone()[0] == spend_delta
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='deliberation_outcomes'",
    ).fetchone()[0] == 1


def test_mixed_stalled_items_record_rejection_once_and_settle(game, monkeypatch):
    """F5：同批合法+非法 stalled，成功落标并记坏项拒收一次，整旨 settled。"""
    db, state, content = game
    did, ref = _plant_proposed(db, state, title="混合探针", target_id="mixed-stalled")
    _stage(db, state, ref, {
        "effects": {
            "deliberation_outcomes": [
                {"dossier_id": ref, "outcome": "stalled", "note": "合法冷场"},
                {"dossier_id": ref, "outcome": "stalled", "note": ""},
            ],
        },
    })
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


def test_imperial_push_without_model_does_not_stub_promulgate(game, monkeypatch):
    """F6：缺模型且需外廷过判时，不得 stub 自动顺颁。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    did, ref = _plant_proposed(db, state, title="缺模型强推", target_id="no-model-push")
    _stage_stalled(db, state, ref, note="无人站台", verdict=None)
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    assert db.dossiers.get(did)["payload"].get("deliberation_state") == "stalled"
    row = _deliberation_desk_row(session, did)
    db.conn.execute(
        "UPDATE staged_declarations SET verdict_json=NULL WHERE decree_ref=?", (ref,),
    )
    db.conn.commit()
    session.llm_config = None
    with pytest.raises(SettlementAbort):
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


def test_continuation_bad_stalled_does_not_swallow_legal_decree_spend(game, monkeypatch):
    """续推非法 stalled 不得牵连同批本旨合法支出；问清后唯一颁布关落账。"""
    db, state, content = game
    did, ref = _plant_proposed(db, state, title="坏stalled旁支", target_id="bad-st-spend")
    _stage(db, state, ref, {"effects": {}}, questions=[{
        "title": "一问", "context": "c",
        "options": [{"label": "准", "hint": "h"}],
    }])
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    qrow = next(
        r for r in session.pending_decisions()
        if str(r.get("event_id") or "").startswith(_DECREE_QUESTION_PREFIX)
    )
    _seed_continuation(db, state, monkeypatch, qrow, {"effects": {
        "deliberation_outcomes": [{
            "dossier_id": did, "outcome": "stalled", "note": "",
        }],
        "economy_moves": [{
            "origin_ref": ref, "account": "国库", "delta": -4,
            "category": "续推坏项旁合法", "reason": "应落",
        }],
    }})
    session.submit_hitl_choices([
        {"decision_key": qrow["decision_key"], "label": "准", "note": "办"},
    ], write_gate=session._write_gate)
    assert db.dossiers.get(did)["payload"].get("deliberation_state") != "stalled"
    assert db.dossiers.authorizes_effects(did)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='续推坏项旁合法'",
    ).fetchone()[0] == 1


def test_two_questions_first_lands_then_second_stalled_keeps_ledger(game, monkeypatch):
    """同旨两问贯通：来源引用别名先入账；案卷编号 stalled 开案头；强推颁布；已落不回滚不重落。"""
    db, state, content = game
    did, ref = _plant_proposed(db, state, title="两问交叉", target_id="two-q-cross")
    _stage(db, state, ref, {"effects": {}}, questions=[
        {"title": "问一", "context": "c", "options": [{"label": "甲", "hint": "h"}]},
        {"title": "问二", "context": "c", "options": [{"label": "丙", "hint": "h"}]},
    ])
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    desk = [
        r for r in session.pending_decisions()
        if str(r.get("event_id") or "").startswith(_DECREE_QUESTION_PREFIX)
    ]
    assert len(desk) == 2

    def answer(row, declaration):
        _seed_continuation(db, state, monkeypatch, row, declaration)
        session.submit_hitl_choices([
            {
                "decision_key": row["decision_key"],
                "label": row["options"][0]["label"],
                "note": "办",
            },
        ], write_gate=session._write_gate)

    def ledger_deltas():
        return [
            int(r[0]) for r in db.conn.execute(
                "SELECT delta FROM economy_ledger WHERE category='两问交叉支' ORDER BY id",
            )
        ]

    # 第一问：来源引用别名入账（承接原独立别名案）。
    answer(desk[0], {"effects": {"economy_moves": [{
        "来源引用": ref, "account": "国库", "delta": -5,
        "category": "两问交叉支", "reason": "第一问",
    }]}})
    assert ledger_deltas() == [-5]
    remain = [
        r for r in session.pending_decisions()
        if str(r.get("event_id") or "").startswith(_DECREE_QUESTION_PREFIX)
    ]
    assert len(remain) == 1
    # 第二问前主状态：stalled 后必须保持（禁回拨 proposed）。
    status_before_stall = db.dossiers.get(did)["status"]
    # 第二问：案卷编号别名 stalled → 案头两选（承接续推待裁与编号别名）。
    answer(remain[0], {"effects": {"deliberation_outcomes": [{
        "案卷编号": did, "outcome": "stalled", "note": "后道无人站台",
    }]}})
    row = db.dossiers.get(did)
    assert row["payload"].get("deliberation_state") == "stalled"
    assert row["status"] == status_before_stall
    assert not db.dossiers.authorizes_effects(did)
    assert ledger_deltas() == [-5]
    desk_open = [
        r for r in session.pending_decisions()
        if str(r.get("status") or "") == "pending"
        and str(r.get("event_id") or "").startswith(f"deliberation:{did}")
    ]
    assert desk_open
    assert {opt.get("action") for opt in desk_open[0]["options"]} == {
        "imperial_push", "hold",
    }
    before_ids = {int(d["id"]) for d in db.dossiers.list_dossiers()}
    session.submit_hitl_choices([
        {
            "decision_key": desk_open[0]["decision_key"],
            "action": "imperial_push",
            "note": "朕独担",
        },
    ], write_gate=session._write_gate)
    pushed = db.dossiers.get(did)
    assert pushed["payload"].get("deliberation_state") == "backed"
    assert pushed.get("promulgation_decision") == "promulgated"
    assert pushed["status"] != "proposed"
    assert {int(d["id"]) for d in db.dossiers.list_dossiers()} == before_ids
    assert ledger_deltas() == [-5]
