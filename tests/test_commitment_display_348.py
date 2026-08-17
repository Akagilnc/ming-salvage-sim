"""Issue #348: commitment display uses relative durations + timed bar uses time progress.

#1185: no exact Chinese free-copy pins. Assert countable relative numbers,
typed bar percentages / None discrimination, and origin_turn fallback on
progress payload. Keep absolute-turn non-leak gates.
"""

from __future__ import annotations

import json
import re

from ming_sim.decree import settle_with_delta
from ming_sim.issues import (
    commitment_display_text,
    commitment_progress_payload,
    commitment_timed_bar_value,
)


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


def _ints(text: str) -> list[int]:
    """Countable integers surfaced in display text (no free-copy pins)."""
    return [int(tok) for tok in re.findall(r"\d+", text)]


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

    def test_timed_text_exposes_relative_duration_elapsed_remaining(self):
        """Timed text surfaces relative duration/elapsed/remaining; remaining clamps ≥0."""
        row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        # duration=12, elapsed=3 → remaining=9
        mid = commitment_display_text(_progress(3), row)
        assert {12, 3, 9} <= set(_ints(mid))

        # duration=12, elapsed=1 → remaining=11
        early = commitment_display_text(_progress(1), row)
        assert {12, 1, 11} <= set(_ints(early))

        # overrun → remaining clamps to 0; duration still countable
        over = commitment_display_text(_progress(15), row)
        over_nums = set(_ints(over))
        assert 0 in over_nums and 12 in over_nums and 15 in over_nums


# ---------------------------------------------------------------------------
# commitment_display_text — passive timed (case 1: no ongoing effects + end_turn)
# ---------------------------------------------------------------------------


class TestPassiveTimedDisplayText:
    def test_no_absolute_month_in_passive_text(self):
        row = _row(end_turn=17, origin_turn=5)
        text = commitment_display_text(_progress(0), row)
        assert "17" not in text, f"Absolute turn leaked into passive display: {text!r}"

    def test_passive_timed_exposes_duration_and_differs_from_active(self):
        """Passive (no ongoing) exposes duration; shape ≠ active timed at same anchors."""
        passive_row = _row(end_turn=17, origin_turn=5)
        active_row = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        passive = commitment_display_text(_progress(0), passive_row)
        active = commitment_display_text(_progress(0), active_row)
        assert 12 in _ints(passive)
        assert passive != active
        # active at zero elapsed still surfaces an elapsed counter (0) + remaining
        assert {12, 0} <= set(_ints(active))


# ---------------------------------------------------------------------------
# commitment_display_text — non-timed types (arrears / goal-gate / open)
# ---------------------------------------------------------------------------


class TestNonTimedDisplayCases:
    def test_arrears_goal_open_types_remain_distinct_and_unbarred(self):
        """Non-timed types stay pairwise distinct, expose months, and never get a timed bar."""
        arrears_row = _row(
            end_turn=0, origin_turn=5,
            ongoing_effects={"economy": [{"account": "国库", "delta": -10, "reason": "补饷"}]},
            stop_condition=json.dumps({"army.guanning.arrears": "<=0"}),
        )
        goal_row = _row(
            end_turn=0, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
            resolve_condition="character.毛文龙.loyalty >= 65",
        )
        open_row = _row(end_turn=0, origin_turn=5, ongoing_effects={"metrics": {"皇威": 1}})

        arrears_p = _progress(2, remaining_arrears=80)
        goal_p = _progress(2, remaining_to_goal=19)
        open_p = _progress(3)

        arrears_t = commitment_display_text(arrears_p, arrears_row)
        goal_t = commitment_display_text(goal_p, goal_row)
        open_t = commitment_display_text(open_p, open_row)

        assert 2 in _ints(arrears_t)
        assert 2 in _ints(goal_t)
        assert 3 in _ints(open_t)
        assert len({arrears_t, goal_t, open_t}) == 3

        assert commitment_timed_bar_value(arrears_p, arrears_row) is None
        assert commitment_timed_bar_value(goal_p, goal_row) is None
        assert commitment_timed_bar_value(open_p, open_row) is None


# ---------------------------------------------------------------------------
# commitment_timed_bar_value — percentage / clamp / None discrimination
# ---------------------------------------------------------------------------


class TestCommitmentTimedBarValue:
    def test_timed_bar_percentage_clamp_and_none_cases(self):
        """Timed bar = wall-clock % of duration; None for open/gate/arrears/passive."""
        timed = _row(
            end_turn=17, origin_turn=5,
            ongoing_effects={"metrics": {"皇威": 1}},
        )
        assert commitment_timed_bar_value(_progress(3), timed) == 25  # 3/12
        assert commitment_timed_bar_value(_progress(12), timed) == 100
        assert commitment_timed_bar_value(_progress(15), timed) == 100  # clamp
        assert commitment_timed_bar_value(_progress(0), timed) == 0

        assert commitment_timed_bar_value(
            _progress(3),
            _row(end_turn=0, origin_turn=5, ongoing_effects={"metrics": {"皇威": 1}}),
        ) is None
        assert commitment_timed_bar_value(
            _progress(3),
            _row(
                end_turn=20, origin_turn=5,
                ongoing_effects={"metrics": {"皇威": 1}},
                resolve_condition="character.毛文龙.loyalty >= 65",
            ),
        ) is None
        assert commitment_timed_bar_value(
            _progress(3, remaining_arrears=80),
            _row(
                end_turn=20, origin_turn=5,
                ongoing_effects={"economy": [{"account": "国库", "delta": -10, "reason": "补饷"}]},
                stop_condition=json.dumps({"army.guanning.arrears": "<=0"}),
            ),
        ) is None
        assert commitment_timed_bar_value(
            _progress(0), _row(end_turn=17, origin_turn=5),
        ) is None


# ---------------------------------------------------------------------------
# Integration: timed bar via real DB + commitment_progress_payload
# ---------------------------------------------------------------------------


class TestTimedBarIntegration:
    def test_bar_tracks_elapsed_via_wall_clock_and_settle(self, game):
        """Bar follows months_elapsed/duration on wall-clock and settle paths; display countable."""
        db, state, content = game
        db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
        db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
        db.conn.commit()

        origin = state.turn
        duration = 4
        issue_id = db.insert_issue(
            state,
            kind="initiative",
            title="赈抚陕西四月",
            origin_kind="decree",
            origin_ref="decree:turn-1:relief-4",
            bar_value=10,
            ongoing_effects={"metrics": {"皇威": 1}},
            end_turn=origin + duration,
            commitment_kind="until_stop",
        )

        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress0 = commitment_progress_payload(db, state, row)
        assert progress0 is not None
        assert progress0["months_elapsed"] == 0
        assert commitment_timed_bar_value(progress0, row) == 0

        # wall-clock advance (no settle / ongoing advance)
        state.turn = origin + 2
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress_wall = commitment_progress_payload(db, state, row)
        assert progress_wall is not None
        assert progress_wall["months_elapsed"] == 2
        assert commitment_timed_bar_value(progress_wall, row) == 50
        text = commitment_display_text(progress_wall, row)
        assert {duration, 2} <= set(_ints(text))
        assert str(origin + duration) not in text

        # settle path on a fresh timed issue also advances months_elapsed → bar
        state.turn = origin
        settle_id = db.insert_issue(
            state,
            kind="initiative",
            title="赈抚陕西四月-settle",
            origin_kind="decree",
            origin_ref="decree:turn-1:relief-4-settle",
            bar_value=10,
            ongoing_effects={"metrics": {"皇威": 1}},
            end_turn=origin + duration,
            commitment_kind="until_stop",
        )
        for _ in range(2):
            before = state.turn
            settle_with_delta(state, db, {}, before_turn=before, content=content)

        settle_row = db.conn.execute(
            "SELECT * FROM issues WHERE id=?", (settle_id,),
        ).fetchone()
        progress_settle = commitment_progress_payload(db, state, settle_row)
        assert progress_settle is not None
        assert progress_settle["months_elapsed"] == 2
        assert commitment_timed_bar_value(progress_settle, settle_row) == 50

    def test_origin_turn_unset_falls_back_to_state_turn(self, game):
        """NULL/0/missing origin_turn → months_elapsed=0 (no absolute turn leak into bar)."""
        db, state, _content = game
        state.turn = 7  # well past 0 so absolute-turn leak would be observable

        base = {
            "id": -1,  # no advances rows → paid_total falls to 0
            "commitment_kind": "until_stop",
            "end_turn": 0,
            "ongoing_effects": "{}",
            "stop_condition": "",
            "resolve_condition": "",
        }
        cases = (
            {**base, "origin_turn": None},
            {**base, "origin_turn": 0},
            dict(base),  # key absent
        )
        for row in cases:
            progress = commitment_progress_payload(db, state, row)
            assert progress is not None
            assert progress["months_elapsed"] == 0, (
                f"origin_turn unset should fall back to state.turn (0 elapsed), "
                f"got {progress['months_elapsed']} for row={row!r}"
            )
