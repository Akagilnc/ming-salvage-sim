import json

import pytest
import ming_sim.cli_backend as cli_backend
import ming_sim.draft_intent as draft_intent
import ming_sim.issues as issue_engine
from ming_sim.session import GameSession
from tests.conftest import covering_monthly_extract
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order as _create_secret_order, rejected_verdict as _rejected_verdict
from tests.conftest import wait_for_background_jobs

def _active_people(db, count):
    people = [
        str(row["name"]) for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT ?",
            (count,),
        ).fetchall()
    ]
    assert len(people) == count
    return people

def _active_minister(db):
    return _active_people(db, 1)[0]

def test_dossier_roster_preserves_multiple_leads_support_roles_and_knowers(game):
    db, state, _content = game
    people = _active_people(db, 4)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="倪黄合力，杨某接应。",
        target_kind="issue", target_id="land-survey",
        participants=[
            {"character_id": people[0], "tier": "主办", "role": "主持清丈"},
            {"character_id": people[1], "tier": "主办", "role": "会同清丈"},
            {"character_id": people[2], "tier": "协办", "role": "接应钱粮"},
            {"character_id": people[3], "tier": "知情", "role": "备悉"},
        ],
    )

    restored = db.get_decree_dossier(dossier_id)
    assert restored["participant_roster"] == [
        {"character_id": people[0], "tier": "主办", "role": "主持清丈", "delegator_id": None},
        {"character_id": people[1], "tier": "主办", "role": "会同清丈", "delegator_id": None},
        {"character_id": people[2], "tier": "协办", "role": "接应钱粮", "delegator_id": None},
        {"character_id": people[3], "tier": "知情", "role": "备悉", "delegator_id": None},
    ]


def test_secret_order_progress_persists_executing_until_terminal(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    order_id = _create_secret_order(db, state, actor, "密查仓储", "核清仓储", [])
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier["status"] == "promulgated"

    db.update_secret_order_progress(
        order_id, "已开始核账", state.year, state.period,
    )
    assert db.get_dossier_for_secret_order(order_id)["status"] == "executing"
    reopened = GameDB(db.path, content=content)
    try:
        assert reopened.get_dossier_for_secret_order(order_id)["status"] == "executing"
    finally:
        reopened.close()

    db.close_secret_order(order_id, "done", "账目核清", state.turn)
    terminal = db.get_dossier_for_secret_order(order_id)
    assert terminal["status"] == "closed"
    assert terminal["execution_outcome"] == "fulfilled"

def test_secret_order_progress_undo_restores_order_and_dossier_axes(game):
    db, state, _content = game
    actor = _active_minister(db)
    order_id = _create_secret_order(db,
        state, actor, "密查仓储", "核清仓储", [],
    )
    chat_turn_id = db.create_chat_turn(state, actor, "dossier-undo", 0)
    db.update_chat_turn_messages(
        chat_turn_id,
        db.append_chat_message(actor, state.turn, "user", "继续查办"),
        db.append_chat_message(actor, state.turn, "minister", "臣遵旨"),
    )
    before = db.capture_chat_rollback_snapshot()
    db.update_secret_order_progress(
        order_id, "已开始核账", state.year, state.period,
    )
    db.record_chat_turn_rollback_diffs(
        chat_turn_id, before, db.capture_chat_rollback_snapshot(),
    )

    db.undo_chat_turn(chat_turn_id)

    assert db.get_secret_order(order_id)["result"] == ""
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier["status"] == "promulgated"
    assert dossier["execution_outcome"] == ""

def test_secret_order_close_failure_rolls_back_only_its_two_axes(game, monkeypatch):
    from ming_sim.applier import atomic

    db, state, _content = game
    order_id = _create_secret_order(db,
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    dossier_before = db.get_dossier_for_secret_order(order_id)

    def fail_execution(*_args, **_kwargs):
        raise RuntimeError("dossier close failed")

    monkeypatch.setattr(db, "record_dossier_execution", fail_execution)
    with atomic(db):
        with pytest.raises(RuntimeError):
            db.close_secret_order(
                order_id, "done", "账目核清", state.turn, commit=False,
            )
        db.conn.execute(
            "UPDATE game_state SET ending_status='caller-continued' WHERE id=1"
        )

    assert db.get_secret_order(order_id)["status"] == "active"
    assert db.get_secret_order(order_id)["result"] == ""
    assert db.get_dossier_for_secret_order(order_id) == dossier_before
    assert db.conn.execute(
        "SELECT ending_status FROM game_state WHERE id=1"
    ).fetchone()["ending_status"] == "caller-continued"

def test_secret_order_progress_rolls_back_both_axes_in_outer_atomic(game):
    from ming_sim.applier import atomic

    db, state, _content = game
    order_id = _create_secret_order(db,
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    with pytest.raises(RuntimeError):
        with atomic(db):
            db.update_secret_order_sim_note(
                order_id, "已惊动仓场", state.year, state.period,
            )
            raise RuntimeError("rollback")

    assert db.get_secret_order(order_id)["sim_note"] == ""
    assert db.get_dossier_for_secret_order(order_id)["status"] == "promulgated"

@pytest.mark.parametrize(
    "action_type",
    (
        "extraordinary_summons", "summons", "inquiry",
        "pressure_inquiry", "public_support",
    ),
)
def test_dialogue_and_engine_action_types_cannot_create_dossiers(
    game, action_type,
):
    db, state, _content = game
    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type=action_type, decree_text="非旨意动作",
            target_kind="issue", target_id="not-a-decree",
        )

def test_create_secret_order_has_resumable_dossier(game):
    db, state, _content = game
    actor = _active_minister(db)
    order_id = _create_secret_order(db,
        state, actor, "在办密令", "成案即有案卷", [], deadline_months=1,
    )
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier is not None
    assert dossier["status"] in {"promulgated", "executing"}

def test_held_dossier_reenters_only_for_next_month_rejudgment(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="着核边饷",
        target_kind="issue", target_id="frontier-pay",
    )
    db.record_dossier_decision(
        dossier_id, "rejected", blocked_layer="six_offices",
        reason="封驳",
    )
    db.record_dossier_decision(dossier_id, "hold")

    assert dossier_id not in {
        row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(
            state, [{"dossier_id": dossier_id, "decision": "promulgated"}],
        )
    state.next_period()
    db.save_state(state)
    assert dossier_id in {
        row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    db.apply_dossier_verdicts(
        state, [{
            "dossier_id": dossier_id, "decision": "promulgated",
        }],
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"

def test_interim_verdict_rejects_reserved_legal_reason_code(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="着核边饷",
        target_kind="issue", target_id="frontier-pay",
    )
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(state, [{
            "dossier_id": dossier_id, "decision": "rejected",
            "legal_reason_code": "statute-42",
        }])

def test_session_manual_directive_keeps_structured_action_at_submission(
    game, monkeypatch,
):
    from ming_sim.db import GameDB
    from ming_sim.models import LLMConfig
    from ming_sim.session import GameSession
    import ming_sim.cli_backend as cli_backend

    import ming_sim.draft_intent as draft_intent
    db, state, content = game
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("落草案不得触发 backend")
        ),
    )
    session = GameSession(
        db.path,
        LLMConfig(
            api_key="", base_url="http://unused", model="unused", channel="api",
        ),
        content=content,
    )
    try:
        directive_id = session.db.add_directive(
            session.state, None, "着查河南河工", "手动新增",
            dossier_payload={
                "dossier_action_type": "assignment",
                "target_kind": "region",
                "target_id": "河南",
                "locality_scope": "single",
                "assignee": _active_minister(session.db),
            },
        )
        assert session.db.get_dossier_for_directive(directive_id) is None

        session.db.ensure_dossiers_for_draft_directives(session.state)
        reopened = GameDB(db.path, content=content)
        try:
            dossier = reopened.get_dossier_for_directive(directive_id)
            assert dossier["action_type"] == "assignment"
            assert dossier["target_kind"] == "region"
            assert dossier["target_id"] == "河南"
            assert dossier["directive_id"] == directive_id
        finally:
            reopened.close()
    finally:
        session.db.close()

def test_probe_directive_shared_entry_creates_and_settles_structured_dossier(game, monkeypatch):
    from ming_sim.decree_forecast import decree_ref_for_dossier
    from tests.test_month_chain_1843 import _prepare_player_month
    from ming_sim.session import GameSession
    from scripts.probe_directive_contract import add_narrative_probe_directive

    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state

    directive = add_narrative_probe_directive(
        session,
        "着有司整饬河工",
        probe_id="contract-smoke",
        notes="probe smoke",
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive.id)
    assert dossier["action_type"] == "policy"
    assert dossier["target_kind"] == "issue"
    assert dossier["target_id"] == "probe:contract-smoke:1"

    db.staged_declarations.stage(
        decree_ref=decree_ref_for_dossier(db, dossier), declaration={},
        turn=int(state.turn), verdict={"decision": "promulgated"}, forecast_text="",
    )
    player = _prepare_player_month(db, state, content, monkeypatch)
    player.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    player.resolve_turn(allow_empty_decree=True)

    assert state.turn == 2
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"

def test_directive_freezes_at_dossier_birth(game):
    db, state, _content = game
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "river-works",
    }
    editable_id = db.add_directive(
        state, None, "河工初稿", "手动新增", dossier_payload=payload,
    )
    db.update_directive_text(
        editable_id, "河工改稿", dossier_payload=payload,
    )
    db.delete_directive(editable_id)

    directive_id = db.add_directive(
        state, None, "着修河工", "手动新增", dossier_payload=payload,
    )
    db.ensure_dossiers_for_draft_directives(state)
    with pytest.raises(ValueError):
        db.update_directive_text(directive_id, "成案后改稿")
    with pytest.raises(ValueError):
        db.delete_directive(directive_id)

def test_directive_edit_replaces_mechanical_payload_before_submission(game):
    db, state, _content = game
    before = state.metrics["国库"]
    ten = {
        "dossier_action_type": "grant_allocation",
        "target_kind": "issue", "target_id": "relief",
        "account": "国库", "amount": 10, "execution_surface": "immediate",
    }
    hundred = {**ten, "amount": 100}
    directive_id = db.add_directive(
        state, None, "拨十两赈济", "手动新增", dossier_payload=ten,
    )

    db.update_directive_text(
        directive_id, "改拨百两赈济", dossier_payload=hundred,
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    assert json.loads(dossier["payload_json"])["amount"] == 100

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
    )
    assert state.metrics["国库"] == before - 100

def test_allocation_rejects_unknown_economy_account_before_dossier_birth(game):
    db, state, _content = game
    # #1716：太仓是 resolve_grant_account 合法别名→国库；未知账户才在 shape 边界拒。
    directive_id = db.add_directive(
        state, None, "发外库银十两赈济", "手动新增",
        dossier_payload={
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief",
            "account": "外库", "amount": 10, "execution_surface": "immediate",
        },
    )

    # #654 路3：成案失败记 rejection、保持 draft，不向外抛
    # #1902 R2：钉 category/source/原子性结构化终态；不锁诊断 reason 词面。
    db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None
    status = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
    ).fetchone()["status"]
    assert status == "draft"
    rej = db.conn.execute(
        "SELECT category, source, item_json FROM rejection_reports "
        "WHERE section='directive_locality'",
    ).fetchall()
    assert rej
    assert all(r["category"] == "locality_fanout_failed" for r in rej)
    assert all(r["source"] == "player_decree" for r in rej)
    assert any(
        json.loads(r["item_json"]).get("directive_id") == directive_id for r in rej
    )

def test_underfunded_in_transit_allocation_closes_from_execution_state(game):
    db, state, _content = game
    state.metrics["国库"] = 5
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银十两押解赴陕",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "in_transit",
            "locality_scope": "single",
            "target_kind": "region",
            "target_id": "shaanxi",
        },
    )

    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert state.metrics["国库"] == 0
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    # #1902 N6：结构化终态已钉；不足额说明词面非契约。

def test_underfunded_immediate_allocation_is_not_recorded_as_fulfilled(game):
    db, state, _content = game
    state.metrics["国库"] = 5
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银十两赈济",
        target_kind="issue",
        target_id="relief",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "immediate",
        },
    )

    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert state.metrics["国库"] == 0
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"

@pytest.mark.parametrize(
    "payload",
    (
        {
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief", "account": "国库",
        },
        {
            "dossier_action_type": "assignment",
            "assignee": "不存在的人",
        },
    ),
)
def test_incomplete_mechanical_directive_is_rejected_instead_of_retyped(
    game, payload,
):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "不完整机械旨意", "手动新增", dossier_payload=payload,
    )
    # #654 路3：校验失败不抛穿；零行 + draft/rejection
    db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None
    status = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
    ).fetchone()["status"]
    assert status == "draft"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM rejection_reports "
        "WHERE section='directive_locality'",
    ).fetchone()["n"] >= 1

def test_mechanical_directive_missing_target_fails_loudly_at_real_entry(game):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "拨银十两但未指明去处", "手动新增",
        dossier_payload={
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue",
            "account": "国库",
            "amount": 10,
            "execution_surface": "immediate",
        },
    )
    # #654 路3：缺 canonical target → rejection，不抛穿
    # #1902 R2：钉 category/source/原子性结构化终态；不锁诊断 reason 词面。
    db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None
    status = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
    ).fetchone()["status"]
    assert status == "draft"
    reasons = db.conn.execute(
        "SELECT category, source, item_json FROM rejection_reports "
        "WHERE section='directive_locality'",
    ).fetchall()
    assert reasons
    assert all(r["category"] == "locality_fanout_failed" for r in reasons)
    assert all(r["source"] == "player_decree" for r in reasons)
    assert any(
        json.loads(r["item_json"]).get("directive_id") == directive_id for r in reasons
    )

def test_secret_order_commitment_origin_maps_to_its_own_dossier(game):
    db, state, _content = game
    order_id = _create_secret_order(db,
        state, _active_minister(db), "安抚诸将", "每月拨银安抚诸将", [],
        deadline_months=3,
    )
    dossier = db.get_dossier_for_secret_order(order_id)
    assert db.resolve_commitment_origin_ref(
        state, f"secret_order:{order_id}", origin_kind="decree",
    ) == f"dossier:{dossier['id']}"

def test_military_directive_projects_normalized_due_turn_to_dossier(game):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "命洪承畴四月内出师", "手动新增",
        dossier_payload={
            "dossier_action_type": "military_order",
            "target_kind": "army", "target_id": "guanning",
            "assignee": _active_minister(db),
            "deadline_months": 4,
        },
    )

    db.ensure_dossiers_for_draft_directives(state)

    dossier = db.get_dossier_for_directive(directive_id)
    payload = json.loads(dossier["payload_json"])
    assert payload["due_turn"] == state.turn + 4
    assert dossier["due_turn"] == state.turn + 4

def test_draft_extraction_does_not_capture_acting_appointment(monkeypatch):
    """现役单旨：署理不入草案（#1902 N5 多旨批抽已退役）。"""
    import ming_sim.cli_backend as cli_backend

    import ming_sim.draft_intent as draft_intent
    acting = {
        "拟旨意图": "拟旨",
        "正文": "命洪承畴暂署兵部尚书",
        "动作类型": "acting_appointment",
        "目标类型": "office",
        "目标ID": "兵部尚书",
    }
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_args, **_kwargs: (json.dumps(acting, ensure_ascii=False), {}),
    )

    result = draft_intent.extract_draft_intent(
        "命洪承畴暂署兵部尚书", "臣已拟妥",
    )

    assert result["draft_action"] == "无"
    assert result.get("dossier_action_type") != "acting_appointment"

def test_executing_dossier_stays_visible_and_extractor_can_close_it(game):
    from ming_sim.issues import apply_score_extraction

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="military_order", decree_text="三月后出师",
        target_kind="region", target_id="shaanxi",
        executor_kind="character", executor_id=_active_minister(db),
        due_turn=state.turn + 3,
        payload={
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single",
        },
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "promulgated"}],
    )
    state.turn += 1
    db.save_state(state)
    assert dossier_id in {
        row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    result = apply_score_extraction(
        db, state, {
            "dossier_executions": [{
                "dossier_id": dossier_id,
                "outcome": "fulfilled",
                "note": "奉旨出师，军令已毕",
            }],
        },
        content=content,
    )
    assert result["dossier_executions"] == [{
        "dossier_id": dossier_id, "outcome": "fulfilled",
    }]
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"

@pytest.mark.parametrize("origin_ref", (
    "dossier:not-a-number", "dossier:1:extra", f"dossier:{2 ** 63}",
))
def test_malformed_dossier_origin_is_rejected_fail_closed(game, origin_ref):
    from ming_sim.issues import apply_score_extraction

    db, state, content = game
    before = state.metrics["国库"]
    result = apply_score_extraction(db, state, {
        "economy_moves": [{
            "account": "国库", "delta": -9, "category": "伪造案卷",
            "origin_ref": origin_ref,
        }],
    }, content=content)

    assert state.metrics["国库"] == before
    assert result["economy_moves"] == []
    # #1902 N6：钉实际拒收 category，禁全 JSON 字串搜索假绿。
    assert result["economy_moves_rejections"][0]["category"] == "invalid_origin_ref"

def test_withdrawn_rescript_records_closed_turn(game):
    from ming_sim.db import GameDB

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="暂缓河工",
        target_kind="issue", target_id="river-works",
    )
    db.record_dossier_decision(
        dossier_id, "rejected", blocked_layer="six_offices", reason="封驳",
    )
    db.record_dossier_decision(dossier_id, "withdrawn", reason="收回成命")
    restored = GameDB(db.path, content=content)
    try:
        dossier = restored.get_decree_dossier(dossier_id)
        assert dossier["status"] == "closed"
        assert dossier["closed_turn"] == state.turn
    finally:
        restored.close()

def test_secret_order_target_survives_restore_and_is_queryable(game):
    from ming_sim.db import GameDB

    db, state, content = game
    order_id = _create_secret_order(db,
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    restored = GameDB(db.path, content=content)
    try:
        matches = restored.list_decree_dossiers(
            target_kind="secret_order", target_id=order_id,
        )
        assert [row["secret_order_id"] for row in matches] == [order_id]
    finally:
        restored.close()

def test_allocation_candidate_edit_preserves_mechanical_payload(game):
    db, state, content = game
    actor = _active_minister(db)
    before = state.metrics["国库"]
    candidate_id = db.stage_directive_candidate(
        state.turn, actor, {
            "text": "初稿拨帑", "actor": actor,
            "dossier_action_type": "grant_allocation",
            "target_kind": "account", "target_id": "国库",
            "amount": 10, "account": "国库",
            "execution_surface": "immediate",
        },
    )
    db.update_directive_candidate(
        candidate_id, {"text": "改稿拨帑赈济", "actor": actor},
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[candidate_id],
    )
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == candidate_id
    )
    payload = json.loads(dossier["payload_json"])
    assert payload["amount"] == 10
    assert payload["account"] == "国库"
    assert dossier["decree_text"] == "改稿拨帑赈济"
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
    )
    assert state.metrics["国库"] == before - 10

def test_immediate_terminal_payload_cannot_bypass_execution_surface(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="着查仓储",
        target_kind="issue", target_id="granary-audit",
        executor_kind="character",
        executor_id=_active_minister(db),
        payload={"immediate_terminal": True},
    )
    db.record_dossier_decision(dossier_id, "promulgated")

    with pytest.raises(ValueError):
        db.record_dossier_execution(
            dossier_id, "fulfilled", "伪造直结", state.turn,
        )
    with pytest.raises(ValueError):
        db.transition_decree_dossier(dossier_id, "closed")

    db.transition_decree_dossier(dossier_id, "executing")
    db.record_dossier_execution(
        dossier_id, "fulfilled", "真实执行完毕", state.turn,
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"

@pytest.mark.parametrize(("balance", "expected_actual", "status", "outcome"), [
    (20, -10, "executing", ""),
    (4, -4, "closed", "failed"),
    (0, 0, "closed", "failed"),
])
def test_inner_treasury_admission_uses_actual_once_and_preserves_surface(
    game, balance, expected_actual, status, outcome,
):
    db, state, _content = game
    state.metrics["内库"] = balance
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="内帑拨银押解赈济",
        target_kind="issue", target_id="relief",
        payload={
            "account": "内库", "amount": 10,
            "execution_surface": "in_transit",
        },
    )

    assert state.metrics["内库"] == max(0, balance - 10)
    assert [row["delta"] for row in db.list_economy_moves_for_dossier(dossier_id)] == (
        [] if expected_actual == 0 else [expected_actual]
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == status
    assert dossier["execution_outcome"] == outcome
    assert state.metrics["内库"] == max(0, balance - 10)
    assert len(db.list_economy_moves_for_dossier(dossier_id)) == int(expected_actual != 0)
    # #1902 N6：失败终态已由 status/outcome/金额钉住；不锁说明有无/词面。
    if outcome != "failed":
        assert status == "executing"
        assert dossier_id in {
            row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
        }
        db.record_dossier_execution(
            dossier_id, "fulfilled", "赈银押解到达", state.turn,
        )
        assert db.get_decree_dossier(dossier_id)["status"] == "closed"

def test_secret_authorization_dossier_does_not_map_payload_to_skill_grant(game):
    db, state, content = game
    character = next(
        item for item in content.characters.values()
        if item.aliases and db.conn.execute(
            "SELECT 1 FROM characters WHERE name=? AND status='active'",
            (item.name,),
        ).fetchone()
    )
    directive_id = db.add_directive(
        state, None, "密授权理财", "player_decree",
        dossier_payload={
            "dossier_action_type": "secret_authorization",
            "target_kind": "character", "target_id": character.aliases[0],
            "assignee": character.aliases[0], "authorization_id": "理财",
            "authorization_ids": ["伪授权"],
        },
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    assert dossier is not None
    assert dossier["target_id"] == character.name
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    stored_payload = json.loads(dossier["payload_json"])
    assert "authorization_id" not in stored_payload
    assert "authorization_ids" not in stored_payload

def test_secret_authorization_rejects_missing_assignee_without_grant(game):
    db, state, content = game
    actor = _active_minister(db)
    payload = {
        "dossier_action_type": "secret_authorization",
        "target_kind": "character", "target_id": actor,
        "assignee": actor, "authorization_id": "理财",
    }
    payload.pop("assignee")
    directive_id = db.add_directive(
        state, None, "残缺密授权", "player_decree", dossier_payload=payload,
    )
    # #654 路3：缺 assignee → rejection 保持 draft，不抛穿
    # #1902 R2：钉 category/source/原子性结构化终态；不锁诊断 reason 词面。
    db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None
    status = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
    ).fetchone()["status"]
    assert status == "draft"
    reasons = db.conn.execute(
        "SELECT category, source, item_json FROM rejection_reports "
        "WHERE section='directive_locality'",
    ).fetchall()
    assert reasons
    assert all(r["category"] == "locality_fanout_failed" for r in reasons)
    assert all(r["source"] == "player_decree" for r in reasons)
    assert any(
        json.loads(r["item_json"]).get("directive_id") == directive_id for r in reasons
    )

def test_in_transit_allocation_requires_execution_verdict(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银押解赴陕",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "in_transit",
            "locality_scope": "single",
            "target_kind": "region",
            "target_id": "shaanxi",
        },
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "promulgated"}],
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    with pytest.raises(ValueError):
        db.close_decree_dossier(dossier_id)
    db.record_dossier_execution(
        dossier_id, "fulfilled", "押解到陕", state.turn,
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "closed"
    assert dossier["execution_note"] == "押解到陕"
    assert dossier["interruption_reason"] == ""

@pytest.mark.parametrize("value", [True, 1.5, 2.9])
def test_durable_allocation_rejects_non_integer_amount_without_downgrade(game, value):
    db, state, _content = game
    minister = _active_minister(db)
    candidate_id = db.stage_directive_candidate(state.turn, minister, {
        "text": "拨帑赈济。", "actor": minister,
        "dossier_action_type": "grant_allocation",
        "target_kind": "issue", "target_id": "invalid-allocation",
        "amount": value, "account": "国库", "execution_surface": "immediate",
    })

    db.commit_pending_actions(
        state, kind_filter="directive", action_ids=[candidate_id],
        directive_status="draft",
    )

    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (candidate_id,)
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        row["pending_action_id"] == candidate_id for row in db.list_decree_dossiers()
    )

def test_durable_military_order_without_assignee_fails_loudly(game):
    db, state, _content = game
    minister = _active_minister(db)
    candidate_id = db.stage_directive_candidate(state.turn, minister, {
        "text": "三月内整军。", "actor": minister,
        "dossier_action_type": "military_order",
        "target_kind": "army", "target_id": "capital-army",
        "deadline_months": 3, "assignee": "",
    })

    db.commit_pending_actions(
        state, kind_filter="directive", action_ids=[candidate_id],
        directive_status="draft",
    )

    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (candidate_id,)
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        row["pending_action_id"] == candidate_id for row in db.list_decree_dossiers()
    )

def test_complete_rejection_verdict_is_restoreable_audit_record(game):
    from ming_sim.db import GameDB

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict["gatekeeper_id"] = _active_minister(db)
    verdict["criteria_snapshot"]["endorsement_entry_ids"] = [1]
    db.apply_dossier_verdicts(state, [verdict])

    restored = GameDB(db.path, content=content)
    try:
        row = restored.list_decree_dossier_decisions(dossier_id)[-1]
        assert row["primary_opponents"] == verdict["primary_opponents"]
        assert row["gatekeeper_id"] == verdict["gatekeeper_id"]
        assert row["criteria_snapshot"] == verdict["criteria_snapshot"]
        assert row["affected_parties"] == verdict["affected_parties"]
        assert row["midzhi_unpromulgatable"] is False
        assert restored.get_decree_dossier(dossier_id)["promulgation_reason"] == verdict["reason"]
    finally:
        restored.close()

def test_rejection_verdict_defaults_omitted_midzhi_marker_to_false(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    assert "midzhi_unpromulgatable" not in verdict

    db.apply_dossier_verdicts(state, [verdict])

    row = db.list_decree_dossier_decisions(dossier_id)[-1]
    assert row["midzhi_unpromulgatable"] is False

@pytest.mark.parametrize("missing", [
    "blocked_layer", "primary_opponents", "gatekeeper_id", "reason", "criteria_snapshot",
])
def test_rejection_runtime_contract_rejects_each_missing_field(game, missing):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict.pop(missing)
    # #1902 R2：钉拒收+原子性+结构化终态；不锁诊断词面。
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(state, [verdict])
    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"

@pytest.mark.parametrize(("field", "bad_value"), [
    ("primary_opponents", [{"kind": "faction", "key": "not-a-real-faction"}]),
    ("primary_opponents", [{"kind": "class", "key": "士绅"}]),
    ("primary_opponents", [{"kind": "faction", "key": "东林", "score": 1}]),
    ("gatekeeper_id", "not-a-real-character"),
])
def test_rejection_runtime_contract_rejects_unknown_references(game, field, bad_value):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict[field] = bad_value
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(state, [verdict])
    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"

@pytest.mark.parametrize(("field", "bad_value"), [
    ("imperial_authority_band", "low"),
    ("appointment_tenure", "临时"),
    ("authorization_ids", [{}]),
    ("endorsement_entry_ids", [True]),
    ("endorsement_entry_ids", ["1"]),
])
def test_rejection_snapshot_rejects_malformed_typed_values(game, field, bad_value):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict["criteria_snapshot"][field] = bad_value
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(state, [verdict])
    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"

@pytest.mark.parametrize("contamination", [
    {"primary_opponents": [{"kind": "faction", "key": 1}]},
    {"primary_opponents": [{"kind": "faction", "key": 1.5}]},
    {"primary_opponents": [{"kind": "faction", "key": True}]},
    {"resistance_scores": [99.5]},
    {"resistance_detail": {"score": 99.5}},
    {"resistance_detail": {"nested": [{"blocked": True}]}},
])
def test_rejection_contract_rejects_numeric_contamination_without_history(
    game, contamination,
):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict.update(contamination)

    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(state, [verdict])

    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"
