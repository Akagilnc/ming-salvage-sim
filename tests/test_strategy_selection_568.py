"""#568 点策：场景交办明确陈策源轮，收夜案卷只指向那一轮。"""

from __future__ import annotations

import json

import ming_sim.audience_night as an
from ming_sim.declaration_dispatch import dispatch_declaration


def _actor(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.get_character_status(ch.name)[0] == "active"
        and getattr(ch, "office", "")
    )


def _chat_turn(db, state, night_id, actor, seq):
    user_id = db.append_chat_message(actor, state.turn, "user", "议策。")
    reply_id = db.append_chat_message(actor, state.turn, "minister", "臣奏请筹议。")
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name,turn,year,period,user_message_id,minister_message_id,"
        "night_id,night_seq,status,extract_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (actor, state.turn, state.year, state.period, user_id, reply_id,
         night_id, seq, "active", "done"),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def _selection(origin_id):
    return {"commissions": [{
        "text": "着倪黄二公先试畿辅清丈，盐课缓图。",
        "strategy_selection": {
            "target_id": "land-survey-pilot-jifu", "source_chat_turn_id": origin_id,
        },
    }]}


class _EmptyEndorsements:
    def run(self, materials):
        return json.dumps({"endorsements": []}, ensure_ascii=False)


def test_selected_strategy_retains_minister_presentation_turn_after_night_close(game):
    db, state, content = game
    actor = _actor(db, content)
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    presentation_id = _chat_turn(db, state, night_id, actor.name, 1)
    pick_id = _chat_turn(db, state, night_id, actor.name, 2)

    result = dispatch_declaration(
        db, state, _selection(presentation_id), minister_name=actor.name,
        night_id=night_id, chat_turn_id=pick_id,
    )
    assert len(result.commissions.applied) == 1 and not result.commissions.rejected
    pending_id = int(result.commissions.applied[0]["id"])
    pending = next(row for row in db.list_pending_actions(state.turn) if int(row["id"]) == pending_id)
    payload = json.loads(pending["payload_json"])
    assert payload["dossier_action_type"] == "strategy_selection"
    assert payload["source_chat_turn_id"] == presentation_id != pick_id

    approved = dispatch_declaration(
        db, state, {"promises": [{"decision": "应允", "action_id": pending_id}]},
        minister_name=actor.name, night_id=night_id,
    )
    assert len(approved.promises.applied) == 1 and not approved.promises.rejected
    an.close_night(db, state, night_id=night_id, content=content,
                   endorsement_extractor_agent=_EmptyEndorsements())
    dossiers = [row for row in db.list_decree_dossiers()
                if int(row.get("pending_action_id") or 0) == pending_id]
    assert len(dossiers) == 1
    assert dossiers[0]["action_type"] == "strategy_selection"
    assert int(dossiers[0]["source_chat_turn_id"]) == presentation_id


def test_pick_turn_cannot_claim_own_origin(game):
    db, state, content = game
    actor = _actor(db, content)
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    pick_id = _chat_turn(db, state, night_id, actor.name, 1)

    result = dispatch_declaration(
        db, state, _selection(pick_id), minister_name=actor.name,
        night_id=night_id, chat_turn_id=pick_id,
    )
    assert not result.commissions.applied and len(result.commissions.rejected) == 1
    assert not db.list_pending_actions(state.turn)


def test_other_minister_presentation_cannot_be_reused(game):
    db, state, content = game
    actor = _actor(db, content)
    other = next(
        ch for ch in content.characters.values()
        if ch.name != actor.name and getattr(ch, "power_id", "ming") == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    foreign_id = _chat_turn(db, state, night_id, other.name, 1)
    pick_id = _chat_turn(db, state, night_id, actor.name, 2)

    result = dispatch_declaration(
        db, state, _selection(foreign_id), minister_name=actor.name,
        night_id=night_id, chat_turn_id=pick_id,
    )
    assert not result.commissions.applied and len(result.commissions.rejected) == 1
    assert not db.list_pending_actions(state.turn)


def test_other_night_presentation_cannot_be_reused(game):
    db, state, content = game
    actor = _actor(db, content)
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    foreign_id = _chat_turn(db, state, night_id + 1000, actor.name, 1)
    pick_id = _chat_turn(db, state, night_id, actor.name, 2)

    result = dispatch_declaration(
        db, state, _selection(foreign_id), minister_name=actor.name,
        night_id=night_id, chat_turn_id=pick_id,
    )
    assert not result.commissions.applied and len(result.commissions.rejected) == 1
    assert not db.list_pending_actions(state.turn)
