"""Issue #348: persisted commitment time progress and typed bar projection."""

from __future__ import annotations

from ming_sim.entities.issue.commitment_display import (
    commitment_progress_payload,
    commitment_timed_bar_value,
)








# ---------------------------------------------------------------------------
# commitment_display_text — timed (case 4: ongoing effects + end_turn, no gate)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# commitment_display_text — passive timed (case 1: no ongoing effects + end_turn)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# commitment_display_text — non-timed types (arrears / goal-gate / open)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# commitment_timed_bar_value — percentage / clamp / None discrimination
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Integration: timed bar via real DB + commitment_progress_payload
# ---------------------------------------------------------------------------


class TestTimedBarIntegration:
    def test_bar_tracks_elapsed_via_wall_clock(self, game):
        """Bar follows months_elapsed/duration from the current turn; display countable."""
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

        # wall-clock advance (no settle / ongoing advance)
        state.turn = origin + 2
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress_wall = commitment_progress_payload(db, state, row)
        assert progress_wall is not None
        assert progress_wall["months_elapsed"] == 2
        assert commitment_timed_bar_value(progress_wall, row) == 50


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
