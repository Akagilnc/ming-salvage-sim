"""#1855 F7 — 重开落点三种：后端状态口投影，前端不猜。

接缝：
- state_payload.reopen_landing ∈ {audience, settlement, month}
- 夜未收 → audience；核账期（快照在）→ settlement；其余 → month
- 真实点即入会先收夜，夜+核账不可持久并存（无人为并存优先级面）
- 邸报写成并经 resolve 推进后 → month（真实入口，非手清快照）
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from types import SimpleNamespace

import web_app
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase


def _runtime(db, state, *, pending_decisions=None, content=None) -> web_app.WebGame:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content if content is not None else SimpleNamespace(characters={}),
        begin_turn=lambda: None,
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: list(pending_decisions or []),
        victory=lambda: {"status": "ongoing", "summary": ""},
        await_translations_before_month=lambda after_drain=None: (
            after_drain() if after_drain else None
        ),
    )
    runtime._write_gate = threading.Lock()
    runtime._settlement_entry_lock = threading.Lock()
    runtime._settlement_entry_inflight = 0
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime


@contextmanager
def _blocking_gate(game):
    gate = web_app._game_write_gate(game)
    gate.acquire()
    try:
        yield
    finally:
        gate.release()


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


def test_real_settlement_entry_closes_night_no_durable_coexistence(game):
    """真实点即入：开夜先收；持久态不并存夜+核账，故删人为并存优先级测。"""
    db, state, content = game
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    assert an.get_open_night(db) is not None

    runtime = _runtime(db, state, content=content)
    mid: dict = {}

    with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
        # body 前 entry 已 accept+auto_close；置 settling 使成功支不清快照，保留核账脸。
        state.turn_phase = TurnPhase.SETTLING.value
        db.save_state(state)
        mid["open_night"] = an.get_open_night(db)
        mid["snap"] = db.get_month_open_snapshot(int(state.turn))
        mid["payload"] = runtime.state_payload()

    assert mid["open_night"] is None
    assert mid["snap"] is not None
    assert mid["payload"]["turn"]["settlement_display"] is True
    assert mid["payload"]["reopen_landing"] == "settlement"
    assert an.get_open_night(db) is None
    assert runtime.state_payload()["reopen_landing"] == "settlement"


def test_after_gazette_written_resolve_advances_to_month_landing(game, monkeypatch):
    """邸报写成 → 真实 resolve 推进后落 month；非手清快照/手改月历。"""
    import ming_sim.decree as dm
    import ming_sim.month_chain as month_chain
    from tests.test_advance_paths_atomic import _recovery_session

    db, state, content = game
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert _runtime(db, state).state_payload()["reopen_landing"] == "settlement"

    dm.persist_resolve_context(
        db, turn, {"metric_delta": {}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    sess = _recovery_session(db, state, content, monkeypatch)
    result = sess.resolve_turn()
    assert result.awaiting is False
    assert result.stage == "gazette"
    assert state.turn == turn
    assert _runtime(db, state).state_payload()["reopen_landing"] == "settlement"

    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (turn, state.year, state.period, "邸报已成"),
    )
    db.conn.commit()
    result = sess.resolve_turn()
    assert result.advanced is True
    assert state.turn == turn + 1
    assert db.get_month_open_snapshot(turn) is None

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["reopen_landing"] == "month"
    assert an.get_open_night(db) is None
