"""Issue #348: commitment timed bar + progress payload (structured), no display-text digit pins."""

from __future__ import annotations

import json

from ming_sim.issues import (
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
    """Minimal dict that commitment_timed_bar_value accepts as row."""
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

        # Non-timed types never get a timed bar.
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
        assert commitment_timed_bar_value(_progress(2, remaining_arrears=80), arrears_row) is None
        assert commitment_timed_bar_value(_progress(2, remaining_to_goal=19), goal_row) is None
        assert commitment_timed_bar_value(_progress(2), open_row) is None


class TestTimedBarIntegration:
    def test_bar_tracks_elapsed_via_wall_clock(self, game):
        """Bar follows months_elapsed/duration from the current turn."""
        db, state, _content = game
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

        state.turn = origin + 2
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress_wall = commitment_progress_payload(db, state, row)
        assert progress_wall is not None
        assert progress_wall["months_elapsed"] == 2
        assert commitment_timed_bar_value(progress_wall, row) == 50

    def test_origin_turn_unset_falls_back_to_state_turn(self, game):
        """NULL/0/missing origin_turn → months_elapsed=0."""
        db, state, _content = game
        state.turn = 7

        base = {
            "id": -1,
            "commitment_kind": "until_stop",
            "end_turn": 0,
            "ongoing_effects": "{}",
            "stop_condition": "",
            "resolve_condition": "",
        }
        cases = (
            {**base, "origin_turn": None},
            {**base, "origin_turn": 0},
            dict(base),
        )
        for row in cases:
            progress = commitment_progress_payload(db, state, row)
            assert progress is not None
            assert progress["months_elapsed"] == 0, (
                f"origin_turn unset should fall back to state.turn (0 elapsed), "
                f"got {progress['months_elapsed']} for row={row!r}"
            )
