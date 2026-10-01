"""承诺进度：真实账本投影按经过月份读取，不扫描展示文本。"""

from ming_sim.issues import commitment_progress_payload, commitment_timed_bar_value


class TestTimedBarIntegration:
    def test_bar_tracks_elapsed_via_wall_clock(self, game):
        db, state, _content = game
        db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
        db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
        db.conn.commit()
        origin = state.turn
        duration = 4
        issue_id = db.insert_issue(
            state, kind="initiative", title="赈抚陕西四月",
            origin_kind="decree", origin_ref="decree:turn-1:relief-4",
            bar_value=10, ongoing_effects={"metrics": {"皇威": 1}},
            end_turn=origin + duration, commitment_kind="until_stop",
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
