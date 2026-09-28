"""#1855 F7 — 重开落点三种：后端状态口投影，前端不猜。

接缝：
- state_payload.reopen_landing ∈ {audience, settlement, month}
- 夜未收 → audience；核账期（快照在）→ settlement；其余 → month
- 邸报写成推进后（settlement_display 清）→ month；旧月邸报不另驱自动弹窗
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase


def _runtime(db, state, *, pending_decisions=None) -> web_app.WebGame:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=SimpleNamespace(characters={}),
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: list(pending_decisions or []),
        victory=lambda: {"status": "ongoing", "summary": ""},
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime


def test_open_night_projects_audience_landing(game):
    db, state, _content = game
    an.open_night(db, state, location="乾清宫", time_of_day="夜")

    payload = _runtime(db, state).state_payload()

    assert payload["reopen_landing"] == "audience"
    assert payload["turn"]["settlement_display"] is False


def test_settlement_period_projects_settlement_landing(game):
    db, state, _content = game
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    payload = _runtime(db, state).state_payload()

    assert payload["turn"]["settlement_display"] is True
    assert payload["reopen_landing"] == "settlement"


def test_paused_settlement_still_projects_settlement_landing(game):
    db, state, _content = game
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    payload = _runtime(db, state).state_payload()

    assert payload["turn"]["settlement_display"] is True
    assert payload["reopen_landing"] == "settlement"


def test_ordinary_month_board_projects_month_landing(game):
    db, state, _content = game
    assert an.get_open_night(db) is None
    assert db.get_month_open_snapshot(int(state.turn)) is None

    payload = _runtime(db, state).state_payload()

    assert payload["reopen_landing"] == "month"
    assert payload["turn"]["settlement_display"] is False


def test_after_gazette_advance_projects_month_not_settlement(game):
    """邸报写成推进后：快照过期 → 落本月盘面；不回核账期。"""
    db, state, _content = game
    db.capture_month_open_snapshot(state)
    assert _runtime(db, state).state_payload()["reopen_landing"] == "settlement"

    # 推进月份：清快照（与 next_period / 展示边界同形）
    from ming_sim.month_open_snapshot import clear_orphan_month_open_snapshot

    state.turn = int(state.turn) + 1
    state.period = int(state.period) % 12 + 1
    if state.period == 1:
        state.year = int(state.year) + 1
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    clear_orphan_month_open_snapshot(db, state)

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["reopen_landing"] == "month"


def test_open_night_wins_over_settlement_display_if_both(game):
    """票面序：夜未收优先于核账期；前端不得自判优先级。"""
    db, state, _content = game
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    db.capture_month_open_snapshot(state)

    payload = _runtime(db, state).state_payload()

    assert payload["turn"]["settlement_display"] is True
    assert payload["reopen_landing"] == "audience"
