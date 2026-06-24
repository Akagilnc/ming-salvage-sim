"""Issue #348: commitment display uses relative durations + timed bar uses time progress."""

import json

import pytest

from ming_sim.issues import (
    commitment_display_text,
    commitment_timed_bar_value,
    commitment_progress_payload,
)
from ming_sim.decree import settle_with_delta


def _row(
    *,
    end_turn: int,
    origin_turn: int,
    ongoing_effects=None,
    stop_condition: str = "",
    resolve_condition: str = "",
):
    """Minimal dict that commitment_display_text/commitment_timed_bar_value accept as row."""
    return {
        "end_turn": end_turn,
        "origin_turn": origin_turn,
        "ongoing_effects": json.dumps(ongoing_effects or {}),
        "stop_condition": stop_condition,
        "resolve_condition": resolve_condition,
    }


def _progress(months_elapsed: int, paid_total: int = 0, **extra):
    p: dict = {"months_elapsed": months_elapsed, "paid_total": paid_total}
    p.update(extra)
    return p


# ---------------------------------------------------------------------------
# commitment_display_text — timed (case 4: ongoing effects + end_turn, no gate)
# ---------------------------------------------------------------------------


class TestTimedDisplayText:
    def test_no_absolute_month_in_text(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        text = commitment_display_text(_progress(1), row)
        # absolute turn 17 must not appear
        assert "17" not in text, f"Absolute turn leaked into display: {text!r}"

    def test_shows_total_duration(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        text = commitment_display_text(_progress(1), row)
        # duration = 17 - 5 = 12
        assert "12" in text, f"Total duration missing from: {text!r}"

    def test_shows_elapsed_months(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        text = commitment_display_text(_progress(3), row)
        assert "3" in text, f"Elapsed months missing from: {text!r}"

    def test_shows_remaining_months(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        text = commitment_display_text(_progress(1), row)
        # remaining = 12 - 1 = 11
        assert "11" in text, f"Remaining months missing from: {text!r}"

    def test_remaining_clamps_to_zero(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        # elapsed overruns duration
        text = commitment_display_text(_progress(15), row)
        assert "0" in text, f"Clamped remaining (0) missing from: {text!r}"


# ---------------------------------------------------------------------------
# commitment_display_text — passive timed (case 1: no ongoing effects + end_turn)
# ---------------------------------------------------------------------------


class TestPassiveTimedDisplayText:
    def test_no_absolute_month_in_passive_text(self):
        row = _row(end_turn=17, origin_turn=5)
        text = commitment_display_text(_progress(0), row)
        assert "17" not in text, f"Absolute turn leaked into passive display: {text!r}"

    def test_shows_duration_in_passive_text(self):
        row = _row(end_turn=17, origin_turn=5)
        text = commitment_display_text(_progress(0), row)
        # duration = 12
        assert "12" in text, f"Duration missing from passive display: {text!r}"

    def test_passive_still_says_dao_qi_dai_cai(self):
        row = _row(end_turn=17, origin_turn=5)
        text = commitment_display_text(_progress(0), row)
        assert "到期待裁" in text, f"Expected '到期待裁' in: {text!r}"


# ---------------------------------------------------------------------------
# commitment_display_text — unchanged cases (arrears / goal-gate / open)
# ---------------------------------------------------------------------------


class TestUnchangedDisplayCases:
    def test_arrears_type_unchanged(self):
        row = _row(
            end_turn=0, origin_turn=5,
            ongoing_effects={"economy": [{"account": "国库", "delta": -10, "reason": "补饷"}]},
            stop_condition=json.dumps({"army.guanning.arrears": "<=0"}),
        )
        text = commitment_display_text(_progress(2, remaining_arrears=80), row)
        assert "直到补齐" in text

    def test_goal_gate_type_unchanged(self):
        row = _row(
            end_turn=0, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
            resolve_condition="character.毛文龙.loyalty >= 65",
        )
        text = commitment_display_text(_progress(2, remaining_to_goal=19), row)
        assert "直到达标" in text

    def test_open_commitment_unchanged(self):
        row = _row(end_turn=0, origin_turn=5, ongoing_effects={"metrics": {"皇威": 1}})
        text = commitment_display_text(_progress(3), row)
        assert "开放承诺" in text


# ---------------------------------------------------------------------------
# commitment_timed_bar_value
# ---------------------------------------------------------------------------


class TestCommitmentTimedBarValue:
    def test_returns_time_based_percentage(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        bar = commitment_timed_bar_value(_progress(3), row)  # 3/12 = 25%
        assert bar == 25

    def test_at_full_duration_returns_100(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        bar = commitment_timed_bar_value(_progress(12), row)
        assert bar == 100

    def test_clamps_to_100_when_overrun(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        bar = commitment_timed_bar_value(_progress(15), row)
        assert bar == 100

    def test_at_zero_elapsed_returns_zero(self):
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        bar = commitment_timed_bar_value(_progress(0), row)
        assert bar == 0

    def test_returns_none_for_no_end_turn(self):
        row = _row(end_turn=0, origin_turn=5, ongoing_effects={"metrics": {"皇威": 1}})
        bar = commitment_timed_bar_value(_progress(3), row)
        assert bar is None

    def test_returns_none_for_stop_gate(self):
        row = _row(
            end_turn=20, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
            resolve_condition="character.毛文龙.loyalty >= 65",
        )
        bar = commitment_timed_bar_value(_progress(3), row)
        assert bar is None

    def test_returns_none_for_arrears_gate(self):
        row = _row(
            end_turn=20, origin_turn=5,
            ongoing_effects={"economy": [{"account": "国库", "delta": -10, "reason": "补饷"}]},
            stop_condition=json.dumps({"army.guanning.arrears": "<=0"}),
        )
        bar = commitment_timed_bar_value(_progress(3, remaining_arrears=80), row)
        assert bar is None

    def test_returns_none_for_passive_timed(self):
        """Passive commitments have no ongoing effects → no monthly advances → bar stays 0."""
        row = _row(end_turn=17, origin_turn=5)  # no ongoing_effects
        bar = commitment_timed_bar_value(_progress(0), row)
        assert bar is None


# ---------------------------------------------------------------------------
# Integration: timed bar via real DB + commitment_progress_payload
# ---------------------------------------------------------------------------


class TestTimedBarIntegration:
    def test_bar_advances_by_wall_clock_when_ongoing_advance_is_rejected(self, game):
        db, state, _content = game
        db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
        db.conn.commit()

        issue_id = db.insert_issue(
            state,
            kind="initiative",
            title="赈抚陕西四月",
            origin_kind="decree",
            origin_ref="decree:turn-1:relief-4",
            bar_value=10,
            ongoing_effects={"metrics": {"皇威": 1}},
            end_turn=state.turn + 4,
            commitment_kind="until_stop",
        )
        state.turn += 2

        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress = commitment_progress_payload(db, state, row)
        assert progress is not None
        assert progress["months_elapsed"] == 2
        assert commitment_display_text(progress, row) == "限4月·已履行2月·还剩2月"

        bar = commitment_timed_bar_value(progress, row)
        assert bar == 50

    def test_bar_advances_with_time(self, game):
        db, state, content = game
        db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
        db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
        db.conn.commit()

        issue_id = db.insert_issue(
            state,
            kind="initiative",
            title="赈抚陕西四月",
            origin_kind="decree",
            origin_ref="decree:turn-1:relief-4",
            bar_value=10,
            ongoing_effects={"metrics": {"皇威": 1}},
            end_turn=state.turn + 4,
            commitment_kind="until_stop",
        )

        # Settle 2 months to create 'ongoing' advances
        for _ in range(2):
            before = state.turn
            settle_with_delta(state, db, {}, before_turn=before, content=content)

        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress = commitment_progress_payload(db, state, row)
        assert progress is not None
        assert progress["months_elapsed"] == 2

        bar = commitment_timed_bar_value(progress, row)
        assert bar == 50  # 2 out of 4 months = 50%

    def test_bar_at_initial_turn_is_zero(self, game):
        db, state, content = game
        db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
        db.conn.commit()

        issue_id = db.insert_issue(
            state,
            kind="initiative",
            title="赈抚陕西一年",
            origin_kind="decree",
            origin_ref="decree:turn-1:relief-12",
            bar_value=10,
            ongoing_effects={"metrics": {"皇威": 1}},
            end_turn=state.turn + 12,
            commitment_kind="until_stop",
        )

        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress = commitment_progress_payload(db, state, row)
        assert progress is not None

        bar = commitment_timed_bar_value(progress, row)
        assert bar == 0
