from ming_sim.audience_night import open_night
from ming_sim.audience_translate import build_night_said_so_far


def _persist_round(db, state, night_id, user_text, reply):
    speaker = "殿上"
    uid = int(db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'user', ?, 'held')",
        (speaker, int(state.turn), user_text),
    ).lastrowid)
    mid = int(db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'minister', ?, 'held')",
        (speaker, int(state.turn), reply),
    ).lastrowid)
    ctid = int(db.create_chat_turn(
        state, speaker, "s", 0, night_id=int(night_id), status="active",
    ))
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=?, minister_message_id=? WHERE id=?",
        (uid, mid, ctid),
    )
    db.conn.commit()
    return ctid


def test_said_so_far_strictly_precedes_source_turn(game):
    """Structured history excludes the source turn and every later turn."""
    db, state, _content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _persist_round(db, state, nid, "第一句已说", "第一答")
    source = _persist_round(db, state, nid, "第二句本轮", "第二答")
    _persist_round(db, state, nid, "第三句后轮", "第三答")

    said = "\n".join(build_night_said_so_far(
        db, nid, until_chat_turn_id=source,
    ))

    assert "第一句已说" in said or "第一答" in said
    assert "第二句本轮" not in said and "第二答" not in said
    assert "第三句后轮" not in said and "第三答" not in said
