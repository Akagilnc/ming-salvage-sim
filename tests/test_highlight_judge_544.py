"""Issue #544 behavior at judge and durable night-scroll seams."""
import threading
import time
from types import SimpleNamespace

import pytest

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


def _chat_result(answer):
    return SimpleNamespace(
        answer=answer, court_action="", next_minister="", proposed_directive=None,
        appointed_minister="", registered_minister="", displaced_minister="",
        secret_order_id=0, pending_action_id=0, pending_action_failures=[],
        directive_confirmation_ambiguous=None,
    )


def _raise_disk_full(*_args):
    raise RuntimeError("disk full")


def test_web_chat_slow_success_starts_other_tails_and_returns_highlighted_history(game):
    """Real non-streaming entry waits only for the bounded judge, after starting both tails."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请据实核账。")
    judge_started = threading.Event()
    release_judge = threading.Event()
    mind_started = threading.Event()
    extraction_started = threading.Event()

    def slow_judge(*_args):
        judge_started.set()
        release_judge.wait(timeout=2)
        return '["据实核账"]'

    runtime.highlight_judge_invoke = slow_judge
    runtime.highlight_judge_timeout = 1
    runtime._trail_mindreading_after_reply = lambda *_a, **_k: mind_started.set()
    runtime._trail_extraction_after_reply = lambda *_a, **_k: extraction_started.set()
    outcome = {}
    call = threading.Thread(
        target=lambda: outcome.setdefault("payload", runtime.chat(minister, "钱粮如何？")),
    )
    call.start()
    assert judge_started.wait(.5)
    assert mind_started.wait(.5)
    assert extraction_started.wait(.5)
    release_judge.set()
    call.join(1)

    assert not call.is_alive()
    history = outcome["payload"]["history"]
    assert next(m for m in history if m["role"] == "minister")["highlights"] == ["据实核账"]


def test_real_chat_highlights_survive_database_reopen_and_scroll(content, tmp_path):
    """Persist through WebGame.chat, close the save, then observe both restored public projections."""
    from ming_sim.db import GameDB
    from tests.test_audience_background import _FakeAgent, _web_game

    path = str(tmp_path / "highlight-restore.db")
    db = GameDB(path, content)
    db.seed_static_data()
    state = db.load_state()
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请据实核账。")
    runtime.highlight_judge_invoke = lambda *_a: '["据实核账"]'
    runtime._start_reply_tail_tasks = lambda *_a: None
    payload = runtime.chat(minister, "钱粮如何？")
    night_id = int(payload["night_id"])
    db.close()

    reopened = GameDB(path, content)
    try:
        history = reopened.build_chat_projection(minister, night_id)
        scroll = an.read_night_scroll(reopened, night_id)
        assert next(m for m in history if m["role"] == "minister")["highlights"] == ["据实核账"]
        assert next(m for m in scroll if m["role"] == "minister")["highlights"] == ["据实核账"]
        assert all(m["highlights"] == [] for m in history + scroll if m["role"] != "minister")
    finally:
        reopened.close()


def test_web_chat_highlight_persistence_failure_is_loud(game, monkeypatch):
    """A DB failure is not an authorized silent judge failure on the non-streaming entry."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请核账。")
    runtime.highlight_judge_invoke = lambda *_a: '["核账"]'
    runtime._start_reply_tail_tasks = lambda *_a: None
    monkeypatch.setattr(db, "set_minister_message_highlights", _raise_disk_full)

    with pytest.raises(RuntimeError, match="disk full"):
        runtime.chat("温体仁", "钱粮如何？")


def test_chat_stream_highlight_persistence_failure_emits_terminal_error(game, monkeypatch):
    """The streaming entry sends done then an explicit terminal error, never hangs awaiting end."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent(chunks=["臣请核账。"]))
    runtime.highlight_judge_invoke = lambda *_a: '["核账"]'
    runtime._trail_mindreading_after_reply = lambda *_a, **_k: None
    runtime._trail_extraction_after_reply = lambda *_a, **_k: None
    monkeypatch.setattr(db, "set_minister_message_highlights", _raise_disk_full)

    events = list(runtime.chat_stream("温体仁", "钱粮如何？"))
    kinds = [event["type"] for event in events]
    assert kinds[-2:] == ["done", "error"]
    assert events[-1]["message"] == "disk full"
    assert "end" not in kinds


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
