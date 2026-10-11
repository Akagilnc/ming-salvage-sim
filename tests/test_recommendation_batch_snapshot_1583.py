"""#1583：同批连续任命 — 批前统一荐人快照校验，批内有序物化。

验收：同一批两份任命案卷，候选为同一在职人物、均携相同批前快照，
目标官职依次不同；经玩家过月入口按序生效，末职=第二条目标，
turn 恰好推进 1；批外真实陈旧快照仍拒。
"""

from __future__ import annotations

import pytest

from tests.test_month_chain_1843 import _prepare_player_month
from ming_sim.decree_forecast import decree_ref_for_dossier
from ming_sim.exceptions import SettlementAbort


def _pick_recommender(content):
    return next(
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
    )


def _stage_recommendation(db, state, recommender_name, row, office, reason, region_id=""):
    payload = {
        "name": row["name"], "office": office,
        "faction": row["faction"], "reason": reason,
        "text": f"准荐{row['name']}任{office}",
        "recommendation": {
            "candidate": dict(row),
            "recommender": recommender_name,
        },
    }
    # Controlled fixture: local seats (e.g. 河道总督) carry typed 任所.
    seat = str(region_id or "").strip() or {
        "河道总督": "henan",
        "陕西巡抚": "shaanxi",
    }.get(str(office or "").strip(), "")
    if seat:
        payload["region_id"] = seat
    return db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=recommender_name,
        target_id=None,
        payload=payload,
    )


def _proposed_appointment_dossier_id(db, pending_id):
    return next(
        row["id"] for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == int(pending_id)
    )


@pytest.mark.parametrize("stale", [False, True])
def test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch(game, monkeypatch, stale):
    """批内两次任命共用批前快照；批外陈旧快照仍拒绝。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = next(
        r for r in db.list_recommendation_candidates(state, recommender.name)
        if r["status"] != "dismissed" and r["name"] != recommender.name
    )
    action_id = _stage_recommendation(
        db, state, recommender.name, row, "巡盐御史", "边才可用",
    )
    if not stale:
        first_office = "巡盐御史"
        second_office = "河道总督"

        id1 = action_id
        id2 = _stage_recommendation(
            db, state, recommender.name, row, second_office, "再调河道，接续核查",
        )
        committed = db.commit_pending_actions(
            state, content=content, action_ids=[id1, id2],
        )
        assert {item["id"] for item in committed} == {id1, id2}

        # 第一案夜里已有判决，第二案过月时补跑判官（首案已改盘面）。
        did = _proposed_appointment_dossier_id(db, id1)
        ref = decree_ref_for_dossier(db, db.get_decree_dossier(did))
        db.staged_declarations.stage(
            decree_ref=ref, declaration={}, turn=int(state.turn),
            verdict={"decision": "promulgated"}, forecast_text="",
        )
        monkeypatch.setattr("ming_sim.decree_forecast.produce_forecast_product", lambda *_a: {
            "declaration": {}, "verdict": {"decision": "promulgated"},
            "questions": None, "forecast_text": "",
        })
        before_turn = int(state.turn)
        session = _prepare_player_month(db, state, content, monkeypatch)
        session.llm_config = object()  # enable the month-chain's exhausted forecast branch
        session.resolve_turn(allow_empty_decree=True)
        db.save_turn_report(state, "邸报", knowledge_items=[], attendant_message="")
        session.resolve_turn(allow_empty_decree=True)

        assert state.turn == before_turn + 1

        char = db.conn.execute(
            "SELECT office, status FROM characters WHERE name=?", (row["name"],),
        ).fetchone()
        assert char is not None
        assert char["status"] == "active"
        assert char["office"] == second_office

        events = db.conn.execute("SELECT target_office, candidate FROM recommendation_events WHERE recommender=? ORDER BY id", (recommender.name,)).fetchall()
        assert [(r["target_office"], r["candidate"]) for r in events] == [(first_office, row["name"]), (second_office, row["name"])]
        return
    # 批外盘面先变：快照相对当前盘面已陈旧。
    db.conn.execute(
        "UPDATE characters SET status='dismissed', office='', reason_code='获罪削籍' "
        "WHERE name=?",
        (row["name"],),
    )
    db.conn.commit()

    result = db.commit_pending_actions(
        state, content=content, action_ids=[action_id],
    )
    assert result and result[0]["id"] == action_id

    did = _proposed_appointment_dossier_id(db, action_id)
    ref = decree_ref_for_dossier(db, db.get_decree_dossier(did))
    db.staged_declarations.stage(
        decree_ref=ref, declaration={}, turn=int(state.turn),
        verdict={"decision": "promulgated"}, forecast_text="",
    )
    session = _prepare_player_month(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
    assert db.get_decree_dossier(did)["status"] == "proposed"

    assert db.conn.execute("SELECT COUNT(*) AS n FROM recommendation_events WHERE recommender=?", (recommender.name,)).fetchone()["n"] == 0
    char = db.conn.execute(
        "SELECT office, status FROM characters WHERE name=?", (row["name"],),
    ).fetchone()
    assert char["status"] == "dismissed"
    assert char["office"] != "巡盐御史"
