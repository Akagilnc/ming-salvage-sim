"""Issue #544 behavior at judge and durable night-scroll seams."""
import time

from ming_sim import audience_night as an
from ming_sim.highlight_judge import judge_highlights, parse_highlights


def test_bad_judge_output_silently_degrades_to_no_highlights():
    for raw in ("", "not json", "{}", '["ok", 3]', None):
        assert parse_highlights(raw) == []


def test_judge_success_and_timeout_are_bounded_without_real_llm():
    assert judge_highlights("臣请核账", object(), timeout=.1,
                            invoke=lambda *_: '["核账"]') == ["核账"]
    started = time.monotonic()
    result = judge_highlights("臣请核账", object(), timeout=.02,
                              invoke=lambda *_: (time.sleep(.2), '["核账"]')[1])
    assert result == []
    assert time.monotonic() - started < .12


def test_highlights_persist_on_message_and_restore_only_for_minister(game):
    db, state, _ = game
    night_id = int(an.open_night(db, state, time_of_day="戌时", location="乾清宫")["id"])
    uid = db.append_chat_message("杨嗣昌", state.turn, "user", "辽饷如何？")
    mid = db.append_chat_message("杨嗣昌", state.turn, "minister", "臣请据实核账。")
    cur = db.conn.execute(
        "INSERT INTO chat_turns (minister_name,turn,year,period,user_message_id,minister_message_id,night_id,night_seq) VALUES (?,?,?,?,?,?,?,?)",
        ("杨嗣昌", state.turn, state.year, state.period, uid, mid, night_id, 1),
    )
    db.conn.commit()
    turn_id = int(cur.lastrowid)

    assert db.set_minister_message_highlights(turn_id, ["据实核账"])
    projection = db.build_chat_projection("杨嗣昌", night_id)
    scroll = an.read_night_scroll(db, night_id)

    assert [m["highlights"] for m in projection] == [[], ["据实核账"]]
    assert next(m for m in scroll if m["role"] == "minister")["highlights"] == ["据实核账"]
    assert all(m["highlights"] == [] for m in scroll if m["role"] != "minister")
