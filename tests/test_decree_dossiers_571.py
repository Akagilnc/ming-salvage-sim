import json

import pytest
import ming_sim.issues as issue_engine


def _active_minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def test_dossier_public_state_machine_and_hold_round_trip(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="着户部清核辽饷。",
        payload={"text": "着户部清核辽饷。"},
    )

    db.record_dossier_decision(
        dossier_id, "rejected", blocked_layer="six_offices", reason="科臣封驳",
    )
    rejected = db.get_decree_dossier(dossier_id)
    assert rejected["status"] == "proposed"
    assert rejected["promulgation_decision"] == "rejected"
    assert rejected["promulgation_blocked_layer"] == "six_offices"
    assert rejected["promulgation_reason"] == "科臣封驳"
    assert rejected["rescript_pending"] is True
    history = db.conn.execute(
        "SELECT blocked_layer,reason FROM decree_dossier_decisions "
        "WHERE dossier_id=? ORDER BY id DESC LIMIT 1",
        (dossier_id,),
    ).fetchone()
    assert dict(history) == {
        "blocked_layer": "six_offices", "reason": "科臣封驳",
    }

    db.record_dossier_decision(dossier_id, "hold", reason="留中")
    held = db.get_decree_dossier(dossier_id)
    assert held["status"] == "proposed"
    assert held["promulgation_decision"] == "rejected"
    assert held["rescript_pending"] is False

    db.record_dossier_decision(dossier_id, "promulgated", reason="下月重判顺颁")
    db.transition_decree_dossier(dossier_id, "executing")
    db.record_dossier_execution(
        dossier_id, "fulfilled", "差事办结", state.turn
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"
    with pytest.raises(ValueError):
        db.transition_decree_dossier(dossier_id, "promulgated")
    with pytest.raises(ValueError):
        db.record_dossier_execution(dossier_id, "completed", "", state.turn)


def test_committing_each_directive_creates_independent_restoreable_dossier(game):
    db, state, _content = game
    minister = _active_minister(db)
    ids = [
        db.stage_directive_candidate(
            state.turn, minister, {"text": text, "actor": minister}
        )
        for text in ("着户部清核辽饷。", "着兵部点验军械。")
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


def test_secret_order_materializes_with_promulgated_dossier_and_closes_together(game):
    db, state, _content = game
    minister = _active_minister(db)
    order_id = db.create_secret_order(
        state, minister, "密查饷银", "暗中核清关宁军饷", [], deadline_months=2
    )

    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier["status"] == "promulgated"
    assert dossier["secret_order_id"] == order_id
    assert dossier["decree_text"] == "暗中核清关宁军饷"
    assert json.loads(dossier["payload_json"])["content"] == "暗中核清关宁军饷"

    db.close_secret_order(order_id, "done", "查明属实", state.turn)
    assert db.get_dossier_for_secret_order(order_id)["status"] == "closed"


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


def test_dossier_type_and_initial_state_are_controlled(game):
    db, state, _content = game
    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type="made_up", decree_text="无效类型"
        )
    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type="appointment", decree_text="非法直入执行",
            status="executing",
        )
    dossier_id = db.create_decree_dossier(
        state, action_type="appointment", decree_text="任命某官"
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    with pytest.raises(ValueError):
        db.transition_decree_dossier(dossier_id, "closed")
    for action_type in (
        "punishment", "pacification", "referral", "revoke_decree",
        "revoke_authority", "dismiss_assignment",
    ):
        assert db.create_decree_dossier(
            state, action_type=action_type, decree_text=action_type,
        ) > 0


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


def test_commitments_bind_explicitly_when_multiple_dossiers_share_a_turn(game):
    db, state, content = game
    first_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="今后每月赈济灾民"
    )
    second_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="今后每月修河"
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
        payload={
            "account": "国库", "delta": -10, "category": "赈济",
            "reason": "奉旨赈济", "immediate_terminal": True,
        },
    )
    db.apply_dossier_verdicts(
        state, [{
            "dossier_id": dossier_id, "decision": "rejected",
            "blocked_layer": "six_offices", "reason": "科臣封驳",
            "legal_reason_code": "statute-review",
        }]
    )
    assert state.metrics["国库"] == before
    rejected = db.get_decree_dossier(dossier_id)
    assert rejected["promulgation_blocked_layer"] == "six_offices"
    assert rejected["promulgation_reason"] == "科臣封驳"
    assert rejected["legal_reason_code"] == "statute-review"

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


def test_authorization_materializes_only_after_batch_verdict(game):
    db, state, _content = game
    minister = _active_minister(db)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="特授理财权",
        target_kind="character",
        target_id=minister,
        payload={
            "character_id": minister,
            "skill_id": "理财",
            "immediate_terminal": True,
        },
    )
    assert db.active_skill_grants(minister) == []
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "promulgated"}]
    )
    assert db.active_skill_grants(minister)


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
    )
    db.record_dossier_decision(published_id, "promulgated")
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={
            "text": "拨国库十两赈济",
            "actor": actor,
            "dossier_action_type": "grant_allocation",
            "account": "国库",
            "delta": -10,
            "category": "赈济",
            "immediate_terminal": True,
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

    assert [row["id"] for row in seen["payload"]["decree_dossiers"]] == [published_id]
    assert seen["payload"]["decree_text"] == "本月已颁之旨"
    staged = db.list_decree_dossiers()[-1]
    assert staged["status"] == "proposed"


def test_legacy_directive_paths_create_one_addressable_dossier(game):
    db, state, _content = game
    draft_id = db.add_directive(state, None, "着核仓储", "手动新增")
    pending_id = db.add_directive(
        state, None, "着查河工", "大臣拟旨", status="pending",
    )

    assert db.get_dossier_for_directive(draft_id)["target_id"] == f"directive:{draft_id}"
    assert db.get_dossier_for_directive(pending_id) is None
    db.confirm_directive(pending_id)
    first = db.get_dossier_for_directive(pending_id)
    db.confirm_directive(pending_id)
    assert db.get_dossier_for_directive(pending_id)["id"] == first["id"]


def test_executing_execution_record_never_closes_or_stamps_closed_turn(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="着持续勘河",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    with pytest.raises(ValueError, match="非终态"):
        db.record_dossier_execution(
            dossier_id, "executing", "正在勘验", state.turn, close=True,
        )
    db.record_dossier_execution(
        dossier_id, "executing", "正在勘验", state.turn, close=False,
    )
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    assert row["closed_turn"] == 0


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
