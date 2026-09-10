"""#1831 事务记录与指向：收夜同生、新指旧、当前情况可恢复、代码不判了结。"""

from __future__ import annotations

import ming_sim.audience_night as audience_night
from ming_sim.db import GameDB


NINGYUAN = "宁远护送"
ORIGIN = "拨银、调将、派兵去宁远"
BIRTH_KEY = "ningyuan-escort"
PROGRESS = "护送银两已出京，尚未抵宁远"
ARRIVED = "银两已抵宁远，洪承畴接管防务"


def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _declaration(*, attach="new", birth_key=BIRTH_KEY, affair_id=None):
    body = {"attach": attach}
    if attach == "new":
        body["name"] = NINGYUAN
        body["origin"] = ORIGIN
        if birth_key:
            body["birth_key"] = birth_key
    else:
        body["affair_id"] = int(affair_id)
    return body


def _stage_three(db, state, minister, declaration):
    payloads = (
        {
            "text": "拨银三十万解往宁远",
            "actor": minister,
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue",
            "target_id": "ningyuan-silver",
            "amount": 300000,
            "account": "国库",
            "affair_declaration": declaration,
        },
        {
            "text": "调洪承畴赴宁远",
            "actor": minister,
            "dossier_action_type": "assignment",
            "assignee": minister,
            "target_kind": "issue",
            "target_id": "ningyuan-general",
            "affair_declaration": declaration,
        },
        {
            "text": "派兵护送去宁远",
            "actor": minister,
            "dossier_action_type": "military_order",
            "assignee": minister,
            "target_kind": "army",
            "target_id": "guanning",
            "deadline_months": 2,
            "affair_declaration": declaration,
        },
    )
    return [
        db.stage_pending_action(
            state.turn, kind="directive", action="拟旨",
            minister_name=minister, payload=payload,
        )
        for payload in payloads
    ]


def test_ningyuan_close_night_one_affair_three_dossiers(game):
    db, state, content = game
    minister = _minister(db)
    night = audience_night.open_night(db, state)
    pending_ids = _stage_three(db, state, minister, _declaration())
    db.mark_pending_night_approved(pending_ids, night_id=night["id"])
    audience_night.close_night(db, state, night_id=night["id"], content=content)

    open_affairs = db.affairs.list_open()
    assert len(open_affairs) == 1
    affair = open_affairs[0]
    assert affair.name == NINGYUAN
    assert affair.origin == ORIGIN
    assert affair.status == "open"

    dossiers = db.affairs.dossiers(affair.id)
    assert len(dossiers) == 3
    assert {row["action_type"] for row in dossiers} == {
        "grant_allocation", "assignment", "military_order",
    }
    assert all(int(row["affair_id"]) == affair.id for row in dossiers)


def test_ledger_points_at_dossier_issue_points_at_affair(game):
    db, state, _ = game
    minister = _minister(db)
    affair = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银三十万解往宁远",
        target_kind="issue",
        target_id="ningyuan-silver",
        payload={
            "account": "国库",
            "amount": 300000,
            "affair_declaration": _declaration(attach="existing", affair_id=affair.id),
        },
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert int(dossier["affair_id"]) == affair.id

    db.record_issue_economy_move(
        state, "国库", -1, "奉旨拨帑", "宁远护送银",
        origin_ref=f"dossier:{dossier_id}",
    )
    origin = db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE origin_ref=?",
        (f"dossier:{dossier_id}",),
    ).fetchone()["origin_ref"]
    assert origin == f"dossier:{dossier_id}"

    issue_id = db.insert_issue(state, kind="situation", title="宁远护送未达")
    db.affairs.point_issue(issue_id, affair.id)
    assert db.affairs.affair_id_for_issue(issue_id) == affair.id


def test_bulk_existing_dossier_receives_declared_affair(game):
    db, state, _ = game
    minister = _minister(db)
    pending_id = 91001
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        pending_action_id=pending_id,
        payload={"assignee_id": minister},
    )
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == 0
    affair = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    ids = db.create_decree_dossiers(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        pending_action_id=pending_id,
        payload={
            "assignee_id": minister,
            "affair_declaration": _declaration(attach="existing", affair_id=affair.id),
        },
    )
    assert ids == [dossier_id]
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == affair.id


def test_affair_current_situation_survives_reopen(game, content):
    db, state, _ = game
    path = db.path
    affair = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair",
        subject_id=str(affair.id),
        body=PROGRESS,
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair",
        subject_id=str(affair.id),
        body=ARRIVED,
        year=state.year,
        period=state.period + 1,
        turn=state.turn + 1,
    )
    db.close()

    restored = GameDB(path, content)
    try:
        loaded = restored.affairs.get(affair.id)
        assert loaded.name == NINGYUAN
        assert loaded.origin == ORIGIN
        materials = restored.affairs.current_situation(restored.textual_facts, affair.id)
        assert [fact.body for fact in materials] == [PROGRESS, ARRIVED]
    finally:
        restored.close()


def test_code_does_not_auto_close_or_merge_affairs(game):
    db, state, _content = game
    minister = _minister(db)
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    second = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    assert first.id != second.id
    assert [row.id for row in db.affairs.list_open()] == [first.id, second.id]

    db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        payload={
            "assignee_id": minister,
            "affair_declaration": _declaration(attach="existing", affair_id=first.id),
        },
    )
    still = db.affairs.get(first.id)
    assert still.status == "open"

    closed = db.affairs.declare_closed(first.id, turn=state.turn)
    assert closed.status == "closed"
    assert [row.id for row in db.affairs.list_open()] == [second.id]
