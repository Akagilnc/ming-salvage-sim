"""Malformed LLM collections at enrichment and persisted-issue application entries."""
from __future__ import annotations

import json

import ming_sim.cli_backend as cb
from ming_sim.issues import apply_issue_inertia_and_ongoing


def test_enrich_buildings_non_list_no_crash(monkeypatch):
    for bad in ("true", "5", '"oops"'):
        raw = ('{"effect_on_resolve": {"buildings": ' + bad +
               ', "metrics": {"民心": 1}}, "ongoing_effects": {}, "effect_on_fail": {}}')
        monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (raw, 1))
        out = cb.enrich_initiative_effects("练新军", "现状", llm_config=None)
        assert isinstance(out["effect_on_resolve"], dict)
        assert out["effect_on_resolve"].get("buildings") == []


def test_inertia_ongoing_non_dict_no_crash(game):
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    iid = db.insert_issue(state, kind="situation", title="畸形ongoing测试", bar_value=50, inertia=1)
    metrics = dict(state.metrics)
    for index, bad in enumerate(("oops", 5, True, [1, 2]), start=1):
        db.conn.execute("UPDATE issues SET ongoing_effects=? WHERE id=?", (json.dumps(bad), iid))
        db.conn.commit()
        assert apply_issue_inertia_and_ongoing(db, state) == []
        assert state.metrics == metrics
        row = db.conn.execute("SELECT status, bar_value FROM issues WHERE id=?", (iid,)).fetchone()
        assert (row["status"], row["bar_value"]) == ("active", 50 + index)

    for economy, delta in (
        (True, 0), (5, 0), ("oops", 0), ({"account": "国库", "delta": -10}, 0),
        ([{"account": "国库", "delta": -5, "reason": "测试"}], -5),
        ([1, "x", None, {"account": "国库", "delta": -3, "reason": "测试"}], -3),
    ):
        issue_id = db.insert_issue(
            state, kind="situation", title="结案集合", bar_value=99, inertia=1,
            effect_on_resolve={"economy": economy},
        )
        before = state.metrics["国库"]
        apply_issue_inertia_and_ongoing(db, state)
        row = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
        assert row["status"] == "resolved"
        assert state.metrics["国库"] == before + delta
