"""#348: structured time progress, percentage clamps and origin fallback.

Display prose is observational, not a source of numeric truth.
"""
from __future__ import annotations

import json

from ming_sim.entities.issue.commitment_display import (
    commitment_progress_payload,
    commitment_timed_bar_value,
)


def _row(*, end_turn, origin_turn, ongoing_effects=None, stop_condition=""):
    return {
        "end_turn": end_turn,
        "origin_turn": origin_turn,
        "ongoing_effects": json.dumps(ongoing_effects or {}),
        "stop_condition": stop_condition,
    }



def _progress(months_elapsed, paid_total=0, **extra):
    return {"months_elapsed": months_elapsed, "paid_total": paid_total, **extra}



class TestCommitmentTimedBarValue:
    def test_timed_bar_percentage_clamp_and_none_cases(self):
        """负向/不适用边界：无时限条时返回 None（正向百分比由 insert_issue+墙钟案覆盖）。"""
        assert commitment_timed_bar_value(
            _progress(3),
            _row(end_turn=0, origin_turn=5, ongoing_effects={"metrics": {"皇威": 1}}),
        ) is None
        # 仅 resolve_condition 串不再冒充 typed stop_gate。
        assert commitment_timed_bar_value(
            _progress(3, remaining_arrears=80),
            _row(end_turn=20, origin_turn=5,
                 ongoing_effects={"economy": [{"account": "国库", "delta": -10, "reason": "补饷"}]},
                 stop_condition=json.dumps({"army.guanning.arrears": "<=0"})),
        ) is None
        assert commitment_timed_bar_value(_progress(0), _row(end_turn=17, origin_turn=5)) is None



class TestTimedBarIntegration:
    def test_bar_tracks_elapsed_via_wall_clock(self, game):
        db, state, _content = game
        db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
        db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
        db.conn.commit()
        origin = state.turn
        duration = 4
        issue_id = db.insert_issue(
            state, kind="initiative", title="赈抚陕西四月", origin_kind="decree",
            origin_ref="decree:turn-1:relief-4", bar_value=10,
            ongoing_effects={"metrics": {"皇威": 1}}, end_turn=origin + duration,
            commitment_kind="until_stop",
        )
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress = commitment_progress_payload(db, state, row)
        assert progress is not None
        assert progress["months_elapsed"] == 0
        assert commitment_timed_bar_value(progress, row) == 0
        state.turn = origin + 2
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        progress_wall = commitment_progress_payload(db, state, row)
        assert progress_wall is not None
        assert progress_wall["months_elapsed"] == 2
        assert commitment_timed_bar_value(progress_wall, row) == 50

    def test_origin_turn_null_or_zero_falls_back_to_state_turn(self, game):
        """合法 NULL/0 回落当前 turn；字段必须在场（完整行契约，非缺字段兼容）。"""
        db, state, _content = game
        state.turn = 7
        base = {
            "id": -1, "commitment_kind": "until_stop", "end_turn": 0,
            "ongoing_effects": "{}", "stop_condition": "", "resolve_condition": "",
        }
        for origin_turn in (None, 0):
            progress = commitment_progress_payload(
                db, state, {**base, "origin_turn": origin_turn},
            )
            assert progress is not None
            assert progress["months_elapsed"] == 0
