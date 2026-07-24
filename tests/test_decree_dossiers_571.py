import json

import pytest
import ming_sim.issues as issue_engine


def _active_minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def test_committing_each_directive_creates_independent_restoreable_dossier(game):
    db, state, _content = game
    minister = _active_minister(db)
    ids = [
        db.stage_directive_candidate(
            state.turn, minister, {
                "text": text, "actor": minister,
                "dossier_action_type": "policy",
                "target_kind": "issue", "target_id": target,
            }
        )
        for text, target in (
            ("着户部清核辽饷。", "liao-pay"),
            ("着兵部点验军械。", "arsenal"),
        )
    ]

    db.commit_pending_actions(
        state, kind_filter="directive", action_ids=ids, directive_status="draft"
    )

    dossiers = db.list_decree_dossiers(status="proposed")
    assert [row["decree_text"] for row in dossiers[-2:]] == [
        "着户部清核辽饷。",
        "着兵部点验军械。",
    ]
    assert len({row["id"] for row in dossiers[-2:]}) == 2
    assert all(row["pending_action_id"] in ids for row in dossiers[-2:])


def test_secret_pending_action_carries_chat_turn_and_pending_provenance(game):
    db, state, content = game
    minister = _active_minister(db)
    chat_turn_id = db.create_chat_turn(state, minister, "session-571", 0)
    message_id = db.conn.execute(
        """
        INSERT INTO chat_messages (minister_name,turn,role,content)
        VALUES (?,?,'user','卿暗中核清关宁军饷')
        """,
        (minister, state.turn),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(chat_turn_id, user_message_id=int(message_id))

    pending_id = db.stage_pending_action(
        state.turn,
        kind="secret_order",
        action="新建",
        minister_name=minister,
        payload={
            "title": "密查饷银",
            "content": "暗中核清关宁军饷",
            "assignee": minister,
            "origin_chat_message_id": int(message_id),
        },
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[pending_id]
    )

    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["pending_action_id"] == pending_id
    assert dossier["source_chat_turn_id"] == chat_turn_id
    assert dossier["executor_kind"] == "character"
    assert dossier["executor_id"] == minister
    assert dossier["decree_text"] == "暗中核清关宁军饷"


def test_terminal_target_does_not_interrupt_another_executor(game):
    db, state, _content = game
    people = [
        str(row["name"]) for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
        ).fetchall()
    ]
    assert len(people) == 2
    target, executor = people
    dossier_id = db.create_decree_dossier(
        state, action_type="punishment", decree_text="命查其罪",
        target_kind="character", target_id=target,
        executor_kind="character", executor_id=executor,
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    db.set_character_status(state, target, "imprisoned", reason="下狱")

    assert db.get_decree_dossier(dossier_id)["status"] == "executing"


def test_office_action_waits_for_verdict_then_materializes_from_same_payload(game):
    db, state, content = game
    minister = _active_minister(db)
    pending_id = db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=minister,
        target_id=None,
        payload={"name": minister, "office": "兵部主事"},
    )

    before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,)
    ).fetchone()["office"]
    db.commit_pending_actions(state, content=content, registry=None)

    dossier = next(
        row for row in db.list_decree_dossiers(target_kind="character", target_id=minister)
        if row["pending_action_id"] == pending_id
    )
    assert dossier["status"] == "proposed"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,)
    ).fetchone()["office"] == before

    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content, registry=None
    )
    dossier = db.get_decree_dossier(dossier["id"])
    assert dossier["status"] == "executing"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,)
    ).fetchone()["office"] == "兵部主事"


@pytest.mark.parametrize("status", ("executing", "closed"))
def test_dossier_cannot_start_in_execution_state(game, status):
    db, state, _content = game
    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type="appointment", decree_text="非法初态",
            target_kind="character", target_id="invalid",
            status=status,
        )


def test_secret_order_and_dossier_roll_back_as_one_unit(game, monkeypatch):
    db, state, _content = game
    minister = _active_minister(db)

    def fail_dossier(*_args, **_kwargs):
        raise RuntimeError("dossier write failed")

    monkeypatch.setattr(db, "create_decree_dossier", fail_dossier)
    with pytest.raises(RuntimeError):
        db.create_secret_order(state, minister, "密查", "查账", [])
    assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == 0


def test_character_terminal_state_closes_secret_order_and_execution_slot(game):
    db, state, _content = game
    minister = _active_minister(db)
    order_id = db.create_secret_order(state, minister, "密查", "查账", [])
    dossier = db.get_dossier_for_secret_order(order_id)
    db.transition_decree_dossier(dossier["id"], "executing")

    db.set_character_status(state, minister, "imprisoned", reason="下狱")

    order = db.get_secret_order(order_id)
    dossier = db.get_dossier_for_secret_order(order_id)
    assert order["status"] == "failed"
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    assert dossier["closed_turn"] == state.turn
    assert dossier["interruption_reason"]


def test_commitments_bind_explicitly_when_multiple_dossiers_share_a_turn(game):
    db, state, content = game
    first_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="今后每月赈济灾民",
        target_kind="issue", target_id="relief",
    )
    second_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="今后每月修河",
        target_kind="issue", target_id="river-works",
    )
    db.apply_dossier_verdicts(state, [
        {"dossier_id": first_id, "decision": "promulgated"},
        {"dossier_id": second_id, "decision": "promulgated"},
    ])

    issue_engine.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{second_id}",
                "kind": "initiative",
                "title": "每月赈济",
                "end_turn": state.turn + 2,
                "commitment_kind": "until_stop",
            }],
        },
        content=content,
    )

    commitments = db.list_commitments_for_dossier(second_id)
    assert len(commitments) == 1
    assert commitments[0]["origin_ref"] == f"dossier:{second_id}"
    assert db.list_commitments_for_dossier(first_id) == []


def test_allocation_rejected_is_zero_effect_and_force_promulgation_keeps_rejection(game):
    db, state, _content = game
    before = state.metrics["国库"]
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨国库十两赈济",
        target_kind="issue", target_id="relief",
        payload={
            "account": "国库", "amount": 10, "category": "赈济",
            "reason": "奉旨赈济", "execution_surface": "immediate",
        },
    )
    db.apply_dossier_verdicts(
        state, [{
            "dossier_id": dossier_id, "decision": "rejected",
            "blocked_layer": "six_offices", "reason": "科臣封驳",
        }]
    )
    assert state.metrics["国库"] == before
    rejected = db.get_decree_dossier(dossier_id)
    assert rejected["promulgation_blocked_layer"] == "six_offices"
    assert rejected["promulgation_reason"] == "科臣封驳"

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "force_promulgated"}]
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert state.metrics["国库"] == before - 10
    assert dossier["status"] == "closed"
    assert dossier["promulgation_decision"] == "rejected"
    moves = db.list_economy_moves_for_dossier(dossier_id)
    assert len(moves) == 1
    assert moves[0]["dossier_id"] == dossier_id


def test_assignment_promulgation_tracks_executor_until_terminal_state(game):
    db, state, content = game
    assignee = _active_minister(db)
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=assignee,
        payload={
            "text": "着其查核仓场", "actor": assignee,
            "assignee": assignee, "target_kind": "issue", "target_id": "warehouse",
        },
    )
    db.commit_pending_actions(state, content=content)
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["action_type"] == "assignment"
    assert dossier["executor_id"] == assignee

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"

    db.set_character_status(state, assignee, "dead", reason="病故")
    assert db.get_decree_dossier(dossier["id"])["status"] == "closed"


def test_real_resolve_entry_feeds_dossiers_without_future_judge(
    game, monkeypatch,
):
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = _active_minister(db)
    published_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="本月已颁之旨",
        target_kind="issue", target_id="published-policy",
    )
    db.record_dossier_decision(published_id, "promulgated")
    secret_order_id = db.create_secret_order(
        state, actor, "密查军饷", "暗中核清关宁军饷", [],
    )
    secret_dossier_id = db.get_dossier_for_secret_order(secret_order_id)["id"]
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={
            "text": "拨国库十两赈济",
            "actor": actor,
            "dossier_action_type": "grant_allocation",
            "account": "国库",
            "amount": 10,
            "category": "赈济",
        },
    )
    seen = {}

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (
            seen.setdefault("payload", k["simulator_payload"]) and "本月奉旨赈济。",
            k["simulator_payload"],
        ),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "", ""),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    decree_mod.resolve_directives(
        state, db, None, None, [object()], "不应作为真源",
        content=content,
    )

    staged = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] > 0
    )
    assert [row["id"] for row in seen["payload"]["decree_dossiers"]] == [
        published_id, staged["id"],
    ]
    db.update_secret_order_progress(
        secret_order_id, "密查仍在推进", state.year, state.period,
    )
    assert db.get_decree_dossier(secret_dossier_id)["status"] == "executing"
    assert seen["payload"]["decree_text"] == "不应作为真源"
    assert staged["status"] == "proposed"


def test_executing_execution_record_never_closes_or_stamps_closed_turn(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="持续办理",
        target_kind="issue", target_id="ongoing-policy",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    with pytest.raises(ValueError):
        db.record_dossier_execution(
            dossier_id, "executing", "仍在办理", state.turn, close=True,
        )
    db.record_dossier_execution(
        dossier_id, "executing", "仍在办理", state.turn, close=False,
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "executing"
    assert dossier["closed_turn"] == 0


def test_appointment_alias_uses_canonical_dossier_identity(game):
    db, state, content = game
    target = next(
        character for character in content.characters.values()
        if character.aliases and character.name != character.aliases[0]
        and db.conn.execute(
            "SELECT 1 FROM characters WHERE name=? AND status='active'",
            (character.name,),
        ).fetchone()
    )
    alias = target.aliases[0]
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=_active_minister(db), target_id=None,
        payload={"name": alias, "office": "兵部主事"},
    )
    db.commit_pending_actions(state, content=content, registry=None)
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["target_id"] == target.name
    assert dossier["executor_id"] == target.name
    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content, registry=None,
    )
    db.record_dossier_execution(
        dossier["id"], "fulfilled", "任事已毕", state.turn,
    )
    assert db.get_decree_dossier(dossier["id"])["status"] == "closed"


def test_real_allocation_capture_materializes_one_negative_treasury_move(
    game, monkeypatch,
):
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    actor = _active_minister(db)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps({
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "目标类型": "account",
            "目标ID": "国库",
            "金额": 10,
            "账户": "国库",
        }, ensure_ascii=False), 1),
    )
    captured = cli_backend.extract_draft_intent(
        "拟旨拨帑赈济", "着拨国库十万两赈济",
    )
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={"text": captured["draft_text"], "actor": actor, **{
            key: captured[key] for key in (
                "dossier_action_type", "target_kind", "target_id",
                "amount", "account",
            )
        }},
    )
    before = state.metrics["国库"]
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content,
    )
    assert state.metrics["国库"] == before - 10
    assert db.list_economy_moves_for_dossier(dossier["id"])[0]["delta"] == -10


def test_real_authorization_capture_resolves_assignee_before_grant(
    game, monkeypatch,
):
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    actor = _active_minister(db)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps({
            "拟旨意图": "拟旨",
            "动作类型": "authorization",
            "目标类型": "character",
            "目标ID": actor,
            "承办人": actor,
            "授权ID": "理财",
        }, ensure_ascii=False), 1),
    )
    captured = cli_backend.extract_draft_intent(
        "拟旨授权其理财", "特授理财之权",
    )
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={"text": captured["draft_text"], "actor": actor, **{
            key: captured[key] for key in (
                "dossier_action_type", "target_kind", "target_id",
                "assignee", "authorization_id",
            )
        }},
    )
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    payload = json.loads(dossier["payload_json"])
    assert payload["assignee_id"] == actor
    assert "assignee" not in payload
    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content,
    )
    assert "理财" in db.active_skill_grants(actor)


def test_extractor_context_origin_ref_round_trips_to_commitment(game):
    from ming_sim.simulation import build_extractor_shared_context

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="今后每月修河",
        target_kind="issue", target_id="river-works",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    extractor_context = build_extractor_shared_context(
        db, state, "河工已经开办", "今后每月修河", module="issues",
    )
    origin_ref = next(
        row["origin_ref"] for row in extractor_context["decree_dossiers"]
        if row["id"] == dossier_id
    )

    issue_engine.apply_score_extraction(
        db, state, {"new_issues": [{
            "origin_kind": "decree",
            "origin_ref": origin_ref,
            "kind": "initiative",
            "title": "逐月修河",
            "end_turn": state.turn + 2,
            "commitment_kind": "until_stop",
        }]}, content=content,
    )

    assert db.list_commitments_for_dossier(dossier_id)[0]["origin_ref"] == origin_ref


def test_real_controlled_verb_capture_keeps_secret_investigation(game, monkeypatch):
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    actor = _active_minister(db)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps({
            "拟旨意图": "拟旨",
            "动作类型": "secret_investigation",
            "目标类型": "issue",
            "目标ID": "granary-corruption",
        }, ensure_ascii=False), 1),
    )
    captured = cli_backend.extract_draft_intent(
        "拟旨密查仓弊", "着密查仓场侵冒",
    )
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={"text": captured["draft_text"], "actor": actor, **{
            key: captured[key] for key in (
                "dossier_action_type", "target_kind", "target_id",
            )
        }},
    )
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["action_type"] == "secret_investigation"
    assert dossier["target_id"] == "granary-corruption"


def test_secret_order_progress_persists_executing_until_terminal(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    order_id = db.create_secret_order(state, actor, "密查仓储", "核清仓储", [])
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
    order_id = db.create_secret_order(
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
    order_id = db.create_secret_order(
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    dossier_before = db.get_dossier_for_secret_order(order_id)

    def fail_execution(*_args, **_kwargs):
        raise RuntimeError("dossier close failed")

    monkeypatch.setattr(db, "record_dossier_execution", fail_execution)
    with atomic(db):
        with pytest.raises(RuntimeError, match="dossier close failed"):
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
    order_id = db.create_secret_order(
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


def test_legacy_secret_orders_restore_with_unique_resumable_dossiers(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    order_ids = {}
    for status in ("active", "pending_review", "done", "failed"):
        order_ids[status] = int(db.conn.execute(
            """
            INSERT INTO secret_orders
                (turn_issued,year_issued,period_issued,minister_name,title,
                 content,status,result,turn_closed)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                state.turn, state.year, state.period, actor, status,
                f"{status}密令", status,
                "已有进展" if status != "active" else "",
                state.turn if status in {"done", "failed"} else None,
            ),
        ).lastrowid)
    db.conn.commit()

    restored = GameDB(db.path, content=content)
    try:
        assert {
            status: restored.get_dossier_for_secret_order(order_id)["status"]
            for status, order_id in order_ids.items()
        } == {
            "active": "promulgated",
            "pending_review": "executing",
            "done": "closed",
            "failed": "closed",
        }
        assert restored.update_secret_order_progress(
            order_ids["active"], "继续查办", state.year, state.period,
        )
        assert restored.get_dossier_for_secret_order(
            order_ids["active"]
        )["status"] == "executing"
    finally:
        restored.close()

    reopened = GameDB(db.path, content=content)
    try:
        assert len([
            row for row in reopened.list_decree_dossiers()
            if row["secret_order_id"] in order_ids.values()
        ]) == len(order_ids)
    finally:
        reopened.close()


def test_legacy_secret_order_migration_ignores_free_text_progress(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    ids = []
    for result, sim_note in (("", ""), ("任意说明", "另一段任意说明")):
        ids.append(int(db.conn.execute(
            """
            INSERT INTO secret_orders
                (turn_issued,year_issued,period_issued,minister_name,title,
                 content,status,result,sim_note)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                state.turn, state.year, state.period, actor, "旧密令",
                "相同结构化密令", "active", result, sim_note,
            ),
        ).lastrowid))
    db.conn.commit()

    restored = GameDB(db.path, content=content)
    try:
        assert [
            restored.get_dossier_for_secret_order(order_id)["status"]
            for order_id in ids
        ] == ["promulgated", "promulgated"]
    finally:
        restored.close()


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

    db, state, content = game
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("add_directive 不得触发 backend")
        ),
    )
    session = GameSession(
        db.path,
        LLMConfig(
            api_key="", base_url="http://unused", model="unused", channel="api",
        ),
        content=content,
        verify_llm=False,
    )
    try:
        directive = session.add_directive(
            "着查河南河工",
            dossier_payload={
                "dossier_action_type": "assignment",
                "target_kind": "region",
                "target_id": "河南",
                "assignee": _active_minister(session.db),
            },
        )
        assert session.db.get_dossier_for_directive(directive.id) is None

        session.db.ensure_dossiers_for_draft_directives(session.state)
        reopened = GameDB(db.path, content=content)
        try:
            dossier = reopened.get_dossier_for_directive(directive.id)
            assert dossier["action_type"] == "assignment"
            assert dossier["target_kind"] == "region"
            assert dossier["target_id"] == "河南"
            assert dossier["directive_id"] == directive.id
        finally:
            reopened.close()
    finally:
        session.db.close()


def test_directive_freezes_at_dossier_birth_and_formal_withdrawal_closes_it(game):
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

    db.withdraw_directive(state, directive_id)
    assert db.get_dossier_for_directive(directive_id)["status"] == "closed"
    assert [
        row["id"] for row in db.list_directives(state, statuses=("withdrawn",))
    ] == [directive_id]


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
    order_id = db.create_secret_order(
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
