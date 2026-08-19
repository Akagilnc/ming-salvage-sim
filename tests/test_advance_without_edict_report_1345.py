"""#1345/#1382 A2 — 快路 advance_without_edict 落正式月档（save_turn_report）。

接缝：
1. decree.advance_without_edict 快路 atomic 内补 save_turn_report（与推进同事务）
2. 史册 /api/history/turn exists:true；previous_turn_summary 首支命中原文
3. record_public_knowledge_event 邸报按既有先例落
4. 禁 save_turn_extraction / mark_directives_issued；不回填历史被吃月份
"""

from __future__ import annotations

import pytest

from ming_sim.constants import TURN_UNIT
from ming_sim.decree import advance_without_edict


EXPECTED_NO_EDICT_MESSAGE = f"本{TURN_UNIT}退朝未下正式圣旨，诸事仍待来{TURN_UNIT}处置。"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_fast_path_writes_turn_report_and_public_gazette(game):
    """快路推进后：closed turn 有正式 turn_report + 邸报公共知识事件。"""
    db, state, content = game
    closed_turn = int(state.turn)

    ok = advance_without_edict(state, db, content=content)
    assert ok is True
    assert int(state.turn) == closed_turn + 1

    report = db.get_turn_report(closed_turn)
    assert report == EXPECTED_NO_EDICT_MESSAGE

    # 史册读端：turn_reports 入月时间线 → exists 材料齐全
    archives = db.list_monthly_archives()
    month = next((row for row in archives if int(row["turn"]) == closed_turn), None)
    assert month is not None
    assert month["has_report"] is True

    # 邸报公共知识（save_turn_report 顺带）
    row = db.conn.execute(
        """
        SELECT title, body, source_id FROM character_knowledge_events
        WHERE character_name='' AND turn=? AND title=?
        ORDER BY id DESC LIMIT 1
        """,
        (closed_turn, "邸报"),
    ).fetchone()
    assert row is not None
    assert EXPECTED_NO_EDICT_MESSAGE in str(row["body"] or "")
    assert str(row["source_id"] or "") == f"turn_report:{closed_turn}:public"

    # 禁伪造 extractor / issued 草案
    assert db.get_turn_extraction(closed_turn) is None
    assert db.list_directives_by_turn(closed_turn) == []


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_fast_path_previous_turn_summary_hits_verbatim(game):
    """推进后 previous_turn_summary 首支命中「本月退朝未下正式圣旨」原文。"""
    db, state, content = game
    advance_without_edict(state, db, content=content)

    summary = db.previous_turn_summary(state)
    assert summary.startswith(EXPECTED_NO_EDICT_MESSAGE) or summary == EXPECTED_NO_EDICT_MESSAGE
    assert "本月退朝未下正式圣旨" in summary


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_fast_path_history_turn_api_exists_true(game, monkeypatch):
    """Web 史册单月读口：exists:true 且 report 为正式档原文。"""
    import web_app

    db, state, content = game
    closed_turn = int(state.turn)
    advance_without_edict(state, db, content=content)

    runtime = type("R", (), {"db": db, "state": state})()
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    # api_history_turn 是 async def
    import asyncio
    payload = asyncio.run(web_app.api_history_turn(closed_turn))
    assert payload["exists"] is True
    assert payload["report"] == EXPECTED_NO_EDICT_MESSAGE


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_double_token_only_one_month_archive(game, monkeypatch):
    """A1×A2 联验：同令牌连发两次 → 第二次 409，史册只多一档月报。"""
    import contextlib
    from types import SimpleNamespace

    import web_app
    from fastapi import HTTPException

    db, state, content = game
    start = int(state.turn)
    before_archives = len(db.list_monthly_archives())

    session = SimpleNamespace(
        registry=None, llm_config=None, _scene_registry=None,
        resolve_turn=lambda **_k: (_ for _ in ()).throw(AssertionError("no resolve")),
    )
    runtime = SimpleNamespace(
        db=db, state=state, content=content, session=session,
        directive_rows=lambda: [], refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": int(state.turn)}},
        _write_gate=__import__("threading").Lock(),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)

    body = web_app.AdvanceWithoutEdictRequest(expected_turn=start)
    web_app.api_advance_without_edict(body)
    with pytest.raises(HTTPException) as ei:
        web_app.api_advance_without_edict(body)
    assert ei.value.status_code == 409
    assert int(state.turn) == start + 1
    assert len(db.list_monthly_archives()) == before_archives + 1
    assert db.get_turn_report(start) == EXPECTED_NO_EDICT_MESSAGE


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_fast_path_report_rolls_back_with_advance_atomic(game, monkeypatch):
    """save_turn_report 与推进同事务：中途崩则 report 不留盘。"""
    import sqlite3

    db, state, content = game
    closed_turn = int(state.turn)

    def _boom(*_a, **_k):
        raise RuntimeError("advance boom after report")

    monkeypatch.setattr(db, "clear_resolve_context", _boom)

    with pytest.raises(RuntimeError, match="advance boom"):
        advance_without_edict(state, db, content=content)

    other = sqlite3.connect(db.path)
    try:
        on_disk = other.execute(
            "SELECT report FROM turn_reports WHERE turn=?", (closed_turn,),
        ).fetchone()
    finally:
        other.close()
    assert on_disk is None
    assert int(state.turn) == closed_turn
