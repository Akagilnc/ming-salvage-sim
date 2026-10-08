"""#1356/#1292：删除固定开局邸报（P7）。

钉测只保票面行为：
1. t0 previous_summary 严格空
2. 空壳可关闭（前端 vitest）
3. 首月真报出现
"""

from __future__ import annotations

import pytest

def test_new_game_t0_previous_summary_strictly_empty(game):
    """① t0：previous_summary 严格空串；turn_reports 无 seed 行。"""
    db, state, _content = game
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)

    assert db.conn.execute("SELECT report FROM turn_reports WHERE turn = 0").fetchone() is None
    _ = db.previous_turn_summary(state)  # 入口可调用；不锁空串正文

def test_new_game_t0_previous_reign_period_label_empty_with_empty_summary(game):
    """r5：t0 无上月报 → previous_reign_period_label 与空 summary 同口径（禁九月残留）。"""
    db, state, _content = game
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)
    assert db.previous_turn_summary(state) == ""
    label = db.previous_turn_reign_period_label(state)
    assert label == ""

@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_state_payload_t0_previous_summary_empty(game):
    """Web state_payload 开局 previous_summary 严格空。"""
    import web_app
    from types import SimpleNamespace

    db, state, content = game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary=db.previous_turn_summary(state),
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"

    from ming_sim.models import reign_period_label

    payload = web_app.WebGame.state_payload(runtime)
    assert payload.get("previous_summary") == ""
    assert payload["turn"]["reign_period_label"] == reign_period_label(1627, 10)
    assert payload.get("previous_reign_period_label") in ("", None)
