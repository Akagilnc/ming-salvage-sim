"""QA 包乙刀② #1343/#1378/#1379/#1388：核账遮罩生命周期（快照清理时点）。

单谓词不动：settlement_display ⇔ 当前回合快照在。
修「不该在的时刻在」：summoning/issued 且无入口在办时，残留快照须清。
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app
from ming_sim.models import TurnPhase
from ming_sim.month_open_snapshot import MONTH_OPEN_KEYS, clear_orphan_month_open_snapshot


def _click_before(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}


def _shell(db, state, content, *, inflight: int = 0):
    """轻壳 WebGame：session.db/state 真源，走真实 refresh_turn 属性缝。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        begin_turn=lambda: None,  # 隔离：本刀只证孤儿清，不重跑 registry
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
    )
    runtime._settlement_entry_inflight = inflight
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime


def test_refresh_turn_clears_orphan_snapshot_on_summoning(game):
    """#1343 族：summoning + 无入口在办 + 残留快照 → refresh_turn 清，拟诏门开。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    assert db.get_month_open_snapshot(int(state.turn)) == before

    runtime = _shell(db, state, content, inflight=0)
    assert web_app._settlement_entry_inflight(runtime) == 0
    runtime.refresh_turn()

    assert db.get_month_open_snapshot(int(state.turn)) is None
    payload = runtime.state_payload()
    assert payload["turn"]["settlement_display"] is False


def test_refresh_turn_keeps_snapshot_while_entry_inflight(game):
    """点即入在办窗：summoning 有快照属故意展示，refresh 不得代清。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)

    runtime = _shell(db, state, content, inflight=1)
    runtime.refresh_turn()
    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_refresh_turn_keeps_awaiting_snapshot(game):
    """awaiting_decision 恢复窗：快照保留（AC3 / FRONT_HALF 不清）。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    runtime = _shell(db, state, content, inflight=0)
    runtime.refresh_turn()
    assert db.get_month_open_snapshot(int(state.turn)) == before
    # 与启动孤儿清同谓词
    assert clear_orphan_month_open_snapshot(db, state) is False
