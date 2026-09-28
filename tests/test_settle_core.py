"""玩家月链 pre_settle 行为测试。"""

from __future__ import annotations

from __future__ import annotations
from contextlib import contextmanager
import pytest
import ming_sim.decree as decree
from ming_sim.decree import pre_settle
from ming_sim.models import Event
from ming_sim import issues
from tests.conftest import active_ming_character, covering_monthly_extract, with_monthly_reports
from tests.dossier_test_helpers import create_test_secret_order

def test_pre_settle_runs_fixed_fiscal_tick(game):
    """pre_settle 跑固定月度财政 tick（落 economy_ledger 行）+ 返回 auto_triggered 清单。"""
    db, state, content = game
    turn = state.turn
    before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]

    auto = pre_settle(state, db)

    after = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]
    assert after > before
    assert isinstance(auto, list)

def test_pre_settle_persists_event_terminal_states_in_write_path(game):
    """PR review：事件过期终态由 pre_settle 写路径落库，候选查询本身不写 DB。"""
    db, state, content = game
    issues.bind_content(content)
    ev = Event(
        id="__test_pre_settle_expiring_event__",
        title="测试·pre_settle 过期事件",
        kind="situation",
        summary="x",
        urgency=50,
        severity=50,
        credibility=50,
        interests=[],
        audiences=[],
        trigger_year=1629,
        trigger_month=1,
        trigger_end_year=1629,
        trigger_end_month=2,
        trigger_gate={"民心": "<=5"},
    )
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 60

        assert all(c.id != ev.id for c in issues.gather_candidate_events(state, db))
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            (ev.id,),
        ).fetchone() is None

        pre_settle(state, db)

        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            (ev.id,),
        ).fetchone()
        assert row["terminal_state"] == "expired"
    finally:
        content.events.remove(ev)
