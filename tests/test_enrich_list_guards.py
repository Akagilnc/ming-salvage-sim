"""Effects retain dirty child values for durable refusal; persisted corruption aborts."""
from __future__ import annotations

import json
import pytest

from ming_sim.applier import Provenance
from ming_sim.declaration_dispatch import dispatch_declaration


@pytest.mark.parametrize("bad", [True, 5, "oops", "  中文\ud800\n", {"原文": "  中文\ud800\n"}])
def test_bad_buildings_rejected_without_losing_good_metrics(game, bad):
    db, state, _ = game
    iid = db.insert_issue(
        state, kind="situation", title="待结局势",
        effect_on_resolve={"buildings": bad, "metrics": {"民心": 1}},
    )
    before = state.metrics["民心"]
    dispatch_declaration(db, state, {"effects": [{"close_issues": [
        {"issue_id": iid, "reason": "resolved"},
    ]}]}, source=Provenance.system_simulation)
    assert state.metrics["民心"] == before + 1
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (iid,)).fetchone()[0] == "resolved"
    row = db.conn.execute("SELECT category, source, item_json FROM rejection_reports").fetchone()
    assert row["category"] == "invalid_shape"
    assert row["source"] == "system_simulation"
    item = json.loads(row["item_json"])
    assert item == {"raw_value": bad}
    assert type(item["raw_value"]) is type(bad)


@pytest.mark.parametrize("bad", ['"oops"', "5", "true", "[1,2]", "not-json"])
def test_persisted_effect_corruption_aborts_without_data_refusal(game, bad):
    db, state, _ = game
    dispatch_declaration(db, state, {"effects": []}, source=Provenance.system_simulation)
    iid = db.insert_issue(state, kind="situation", title="存库后损坏的局势")
    db.conn.execute("UPDATE issues SET effect_on_resolve=? WHERE id=?", (bad, iid))
    db.conn.commit()
    before = dict(state.metrics)
    with pytest.raises(ValueError):
        dispatch_declaration(db, state, {"effects": [
            {"metric_delta": {"民心": 2}},
            {"close_issues": [{"issue_id": iid, "reason": "resolved"}]},
        ]}, source=Provenance.system_simulation)
    assert state.metrics == before
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (iid,)).fetchone()[0] == "active"
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 0
