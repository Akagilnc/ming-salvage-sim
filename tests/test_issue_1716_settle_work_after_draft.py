"""#1716：场外已开夜「退朝」须 closed（grant 金额契约见 test_grant_allocation_materialize_518）。"""

from __future__ import annotations

from types import MethodType

from ming_sim.session import ChatTurnResult, GameSession
from tests.test_audience_travel_gating_670 import (
    _set_place,
    _web_hall_runtime,
)


def test_offsite_open_night_court_break_closes_night(game):
    """#1716：场外大臣已开夜后「退朝」须收夜，不得再被 SUMMON_* 短路。"""
    import ming_sim.audience_night as an

    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        raise AssertionError("场外记召不得调回话")

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)
    runtime.session._beat_generator = lambda _inputs: "场外传召途中。"

    first = runtime.chat(remote.name, "宣洪承畴")
    assert first.get("admission") == "SUMMON_FRESH"
    open_n = an.get_open_night(db)
    assert open_n is not None
    night_id = int(open_n["id"])

    consumed = []
    real_consume = runtime.session.consume_audience_admission

    def _spy_consume(character, **kwargs):
        consumed.append(str(character.name))
        return real_consume(character, **kwargs)

    runtime.session.consume_audience_admission = _spy_consume

    def _break_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        assert message.strip() == "退朝"
        result = ChatTurnResult(answer="臣等恭送陛下。")
        result.court_action = "court_break"
        return result

    runtime.session.chat = MethodType(
        lambda self, *a, **k: _break_chat(*a, **k), runtime.session,
    )
    runtime.session.close_night_after_chat_if_needed = MethodType(
        GameSession.close_night_after_chat_if_needed, runtime.session,
    )
    runtime.session._write_gate = getattr(runtime, "_write_gate", None) or __import__(
        "threading"
    ).Lock()

    payload = runtime.chat(remote.name, "退朝")
    assert consumed == [], f"退朝不得再 consume admission，got {consumed}"
    assert payload.get("court_action") == "court_break"
    assert not payload.get("admission"), payload.get("admission")
    assert an.get_open_night(db) is None
    row = db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert row is not None
    assert str(row["status"]) == "closed"
