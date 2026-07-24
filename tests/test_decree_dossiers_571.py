import json

import pytest


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
        action_type="directive",
        decree_text="着户部清核辽饷。",
        payload={"text": "着户部清核辽饷。"},
    )

    db.record_dossier_decision(dossier_id, "rejected", reason="科臣封驳")
    rejected = db.get_decree_dossier(dossier_id)
    assert rejected["status"] == "proposed"
    assert rejected["promulgation_decision"] == "rejected"
    assert rejected["rescript_pending"] is True

    db.record_dossier_decision(dossier_id, "hold", reason="留中")
    held = db.get_decree_dossier(dossier_id)
    assert held["status"] == "proposed"
    assert held["promulgation_decision"] == "rejected"
    assert held["rescript_pending"] is False

    db.record_dossier_decision(dossier_id, "promulgated", reason="下月重判顺颁")
    db.transition_decree_dossier(dossier_id, "executing")
    db.close_decree_dossier(dossier_id, "差事办结")
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"
    with pytest.raises(ValueError):
        db.transition_decree_dossier(dossier_id, "promulgated")


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
    assert json.loads(dossier["payload_json"])["content"] == "暗中核清关宁军饷"

    db.close_secret_order(order_id, "done", "查明属实", state.turn)
    assert db.get_dossier_for_secret_order(order_id)["status"] == "closed"


def test_terminal_character_state_closes_live_dossiers_without_ghost_work(game):
    db, state, _content = game
    minister = _active_minister(db)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="office",
        target_kind="character",
        target_id=minister,
        decree_text=f"着{minister}承办清查。",
        payload={"name": minister},
        status="executing",
    )

    db.set_character_status(state, minister, "dead", reason="阵亡")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "closed"
    assert "人物终态" in dossier["interruption_reason"]


def test_office_action_enters_executing_dossier_instead_of_direct_close(game):
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

    db.commit_pending_actions(state, content=content, registry=None)

    dossier = next(
        row for row in db.list_decree_dossiers(target_kind="character", target_id=minister)
        if row["pending_action_id"] == pending_id
    )
    assert dossier["status"] == "executing"
