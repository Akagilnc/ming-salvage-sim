"""#1583：同批连续任命 — 批前统一荐人快照校验，批内有序物化。

验收：同一批两份任命案卷，候选为同一在职人物、均携相同批前快照，
目标官职依次不同；经 apply_dossier_verdicts 真入口按序生效，末职=第二条目标；
批外真实陈旧快照仍拒。
"""

from __future__ import annotations

import pytest

from tests.dossier_test_helpers import promulgate_proposed_appointments


def _pick_recommender(content):
    return next(
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
    )


def _stage_recommendation(db, state, recommender_name, row, office, reason):
    return db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=recommender_name,
        target_id=None,
        payload={
            "name": row["name"], "office": office,
            "faction": row["faction"], "reason": reason,
            "recommendation": {
                "candidate": dict(row),
                "recommender": recommender_name,
            },
        },
    )


def test_same_batch_consecutive_appointments_keep_prebatch_recommendation_snapshot(game):
    """tracer：同人同批两任命、同批前快照 → 按序物化，末职=第二条，不卡物化。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = next(
        r for r in db.list_recommendation_candidates(state, recommender.name)
        if r["candidate_kind"] == "荐在职" and r["status"] == "active"
        and r["name"] != recommender.name
    )
    # 冻结批前快照：两条载荷都带这份生成当时的同一候选行。
    snapshot = dict(row)
    name = row["name"]
    first_office = "巡盐御史"
    second_office = "河道总督"

    id1 = _stage_recommendation(
        db, state, recommender.name, snapshot, first_office, "先调巡盐，旧任可迁",
    )
    id2 = _stage_recommendation(
        db, state, recommender.name, snapshot, second_office, "再调河道，接续核查",
    )
    committed = db.commit_pending_actions(
        state, content=content, registry=None, action_ids=[id1, id2],
    )
    assert {item["id"] for item in committed} == {id1, id2}

    # 真入口：批量判决顺颁（非直测 helper）。第一条物化后候选人现职已变，
    # 若仍按批内中间态二次校验，第二条会误判快照过期并抛物化失败。
    promulgate_proposed_appointments(db, state, content)

    char = db.conn.execute(
        "SELECT office, status FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert char is not None
    assert char["status"] == "active"
    assert char["office"] == second_office

    events = db.list_recommendation_events(state, recommender.name)
    by_office = {event["target_office"]: event for event in events}
    assert first_office in by_office
    assert second_office in by_office
    assert by_office[first_office]["candidate"] == name
    assert by_office[second_office]["candidate"] == name


def test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch(game):
    """批外真实陈旧快照仍按既有契约拒绝——不得为点绿放松校验。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = next(
        r for r in db.list_recommendation_candidates(state, recommender.name)
        if r["status"] != "dismissed" and r["name"] != recommender.name
    )
    action_id = _stage_recommendation(
        db, state, recommender.name, row, "巡盐御史", "边才可用",
    )
    # 批外盘面先变：快照相对当前盘面已陈旧。
    db.conn.execute(
        "UPDATE characters SET status='dismissed', office='', reason_code='获罪削籍' "
        "WHERE name=?",
        (row["name"],),
    )
    db.conn.commit()

    result = db.commit_pending_actions(
        state, content=content, registry=None, action_ids=[action_id],
    )
    assert result and result[0]["id"] == action_id

    with pytest.raises(ValueError, match="任免案卷载荷物化失败"):
        promulgate_proposed_appointments(db, state, content)

    assert db.list_recommendation_events(state, recommender.name) == []
    char = db.conn.execute(
        "SELECT office, status FROM characters WHERE name=?", (row["name"],),
    ).fetchone()
    assert char["status"] == "dismissed"
    assert char["office"] != "巡盐御史"
