"""同夜撤回排队轮后，后续转译仍须等前轮落账。"""

import threading

from ming_sim.audience_night import list_ledger, open_night
from ming_sim.audience_translation import (
    cancel_turn_translation,
    schedule_audience_turn_translation,
)
from ming_sim.session_write_queue import SessionWriteQueue
from tests.conftest import offline_empty_audience_translate


def test_cancelled_middle_round_keeps_successor_behind_predecessor(game):
    db, state, _ = game
    night_id = int(open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    turns = []
    for reply in ("甲奏。", "乙奏。", "丙奏。"):
        turn = db.create_chat_turn(state, "殿上", "sess", 0, night_id=night_id)
        db.persist_minister_reply("殿上", state.turn, reply, turn, mindreading_status="skip")
        turns.append(turn)

    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    def translate(prompt, config):
        reply = prompt.split("【本轮回话】", 1)[1].removesuffix("\n")
        calls.append(reply)
        if reply == "甲奏。":
            first_started.set()
            assert release_first.wait(5)
        return offline_empty_audience_translate(prompt, config)

    queue = SessionWriteQueue()
    def schedule(turn, reply):
        return schedule_audience_turn_translation(
            db, state, emperor_message="问", reply=reply,
            night_id=night_id, chat_turn_id=turn, translate_fn=translate,
            write_gate=queue.write_gate, write_queue=queue,
        )

    first = schedule(turns[0], "甲奏。")
    try:
        assert first_started.wait(5)
        middle = schedule(turns[1], "乙奏。")
        last = schedule(turns[2], "丙奏。")
        cancel_turn_translation(turns[1], write_queue=queue)
        assert calls == ["甲奏。"]
    finally:
        release_first.set()
    first.result(timeout=5)
    last.result(timeout=5)
    assert middle.cancelled()
    assert calls == ["甲奏。", "丙奏。"]
    assert [e["body"] for e in list_ledger(db, night_id) if e.get("body") in {"甲奏。", "乙奏。", "丙奏。"}] == ["甲奏。", "丙奏。"]
