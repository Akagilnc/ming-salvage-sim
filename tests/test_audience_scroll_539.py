"""Issue #539: night-scroll read contract at the audience-night public seam."""

from ming_sim import audience_night as an


def _night(db, state):
    return int(an.open_night(db, state, time_of_day="戌时", location="乾清宫")["id"])


def _chat(db, state, night_id, minister, user_text, answer, seq):
    uid = db.append_chat_message(minister, state.turn, "user", user_text)
    mid = db.append_chat_message(minister, state.turn, "minister", answer)
    cur = db.conn.execute(
        "INSERT INTO chat_turns (minister_name,turn,year,period,user_message_id,minister_message_id,night_id,night_seq) VALUES (?,?,?,?,?,?,?,?)",
        (minister, state.turn, state.year, state.period, uid, mid, night_id, seq),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def test_scroll_contract_merges_both_stores_with_container_and_coda(game):
    db, state, _ = game
    night_id = _night(db, state)
    an.append_ledger_entry(db, night_id, body="帘外风紧。", tags=[an.TAG_ENTER], person_names=["杨嗣昌"])
    _chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"] == {"time_of_day": "戌时", "location": "乾清宫", "audience_type": "召对"}
    assert [(m["role"], m["speaker"], m["content"]) for m in scroll if m["role"] != "scene"] == [
        ("user", "朕", "辽饷如何？"),
        ("minister", "杨嗣昌", "臣请据实核账。"),
    ]
    assert all({"role", "speaker", "audibility", "time", "soft_boundary", "beat", "highlights", "container"} <= set(m) for m in scroll)
    assert scroll[-1]["beat"] == "coda"
    assert scroll[-1]["content"] == ""


def test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action(game):
    db, state, _ = game
    night_id = _night(db, state)
    first_turn = _chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
    an.append_ledger_entry(db, night_id, body="臣告退。", tags=["人际动作"], person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10)
    an.append_ledger_entry(db, night_id, body="杨嗣昌退下。", tags=[an.TAG_EXIT], person_names=["杨嗣昌"])
    an.append_ledger_entry(db, night_id, body="洪承畴入殿。", tags=[an.TAG_ENTER], person_names=["洪承畴"])

    scroll = an.read_night_scroll(db, night_id)

    assert [m["content"] for m in scroll].count("臣告退。") == 1
    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["soft_boundary"] is True
    assert divider["speaker"] == "洪承畴"


def test_scroll_merges_mindreading_and_uses_structured_dedup_boundaries(game):
    db, state, _ = game
    night_id = _night(db, state)
    turn_id = _chat(db, state, night_id, "杨嗣昌", "卿可担名？", "臣愿当面作保。", 10)
    db.record_mindreading(turn_id, {
        "reader": "王承恩", "target": "杨嗣昌", "source": "察言观色",
        "precision": "约略", "narration": "万岁爷，他这话留了半分。",
    })
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌以身家作保。", tags=["站台", "作保"],
        person_names=["杨嗣昌"], source_chat_turn_id=turn_id, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="帘外忽起雨声。", tags=["天气"],
        person_names=[], source_chat_turn_id=turn_id, order_key=10,
    )

    scroll = an.read_night_scroll(db, night_id)

    aside = next(message for message in scroll if message["role"] == "attendant")
    assert (aside["speaker"], aside["beat"], aside["audibility"]) == ("王承恩", "aside", an.AUDIBILITY_PRIVATE)
    assert aside["content"] == "万岁爷，他这话留了半分。"
    assert "杨嗣昌以身家作保。" not in [message["content"] for message in scroll]
    assert "帘外忽起雨声。" in [message["content"] for message in scroll]


def test_extractor_open_tags_do_not_drive_beat_or_soft_boundary(game):
    db, state, _ = game
    night_id = _night(db, state)
    turn_id = _chat(db, state, night_id, "杨嗣昌", "说下去。", "臣遵旨。", 10)
    an.append_ledger_entry(
        db, night_id, body="只是提到了入殿旧事。", tags=[an.TAG_ENTER],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="又提到了告退旧事。", tags=[an.TAG_EXIT],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )

    scroll = an.read_night_scroll(db, night_id)

    by_content = {message["content"]: message["beat"] for message in scroll}
    assert by_content["只是提到了入殿旧事。"] == "scene"
    assert by_content["又提到了告退旧事。"] == "scene"
    assert not any(message["beat"] == "divider" and message["speaker"] == "洪承畴" for message in scroll)


def test_scroll_container_uses_persisted_summon_method(game):
    db, state, _ = game
    night_id = _night(db, state)
    an.summon_enter(db, night_id, "杨嗣昌", method=an.METHOD_YUECI)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"]["audience_type"] == an.METHOD_YUECI


def test_scroll_without_next_entrance_has_unnamed_boundary(game):
    db, state, _ = game
    night_id = _night(db, state)
    an.append_ledger_entry(db, night_id, body="众臣告退。", tags=[an.TAG_EXIT], person_names=["杨嗣昌"])

    scroll = an.read_night_scroll(db, night_id)

    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["speaker"] == ""
