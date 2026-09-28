import json

import pytest

from tests.section_rejection_helpers import game


def _reports(db):
    return [dict(r) for r in db.conn.execute("SELECT turn, section, item_json, reason, category, source, attempt FROM rejection_reports ORDER BY id")]


def test_persist_resolve_context_rejects_bad_items_and_saves_sanitized_delta(game, tmp_path, monkeypatch):
    from ming_sim.applier import Provenance
    from ming_sim.decree import persist_resolve_context

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, _ = game
    turn = state.turn
    extracted = {
        "economy_moves": [
            {"account": "国库", "delta": 1, "category": "ok"},
            "坏项",
        ],
        "region_delta": {
            "shaanxi": "坏地区",
            "henan": {"unrest": -1},
        },
    }

    persist_resolve_context(
        db,
        turn,
        extracted,
        decree_text="诏",
        narrative="邸报",
        simulator_payload={},
        secret_orders={},
        relevant_memories=[],
        source=Provenance.player_decree,
    )

    ctx = db.get_resolve_context(turn)
    assert ctx["extracted"]["economy_moves"] == [{"account": "国库", "delta": 1, "category": "ok"}]
    assert ctx["extracted"]["region_delta"] == {"henan": {"unrest": -1}}
    rows = _reports(db)
    assert [(r["section"], json.loads(r["item_json"])) for r in rows] == [
        ("economy_moves", {"raw_value": "坏项"}),
        ("region_delta", {"entity_id": "shaanxi", "raw_value": "坏地区"}),
    ]
    assert {r["source"] for r in rows} == {"player_decree"}




def test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate(game):
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector

    db, state, _ = game
    collector = RejectionCollector()
    collector.record(
        "new_issues",
        RejectedItem({"title": "中文\ud800"}, "坏", "invalid_enum", Provenance.player_decree),
        state.turn,
    )
    collector.flush_to_db(db)
    row = db.conn.execute("SELECT item_json FROM rejection_reports").fetchone()
    assert "中文" in row["item_json"]
    assert "\\ud800" in row["item_json"]






def test_sqlite_text_sanitization_covers_issue_rows_and_advances(game):
    db, state, _ = game
    bad_text = "中文\ud800"

    issue_id = db.insert_issue(
        state,
        kind="situation",
        title=bad_text,
        bar_good_meaning=bad_text,
        bar_bad_meaning=bad_text,
        stage_text=bad_text,
        region_hint=bad_text,
        faction_hint=bad_text,
        tags=[bad_text],
        ongoing_effects={"note": bad_text},
        cancel_cost={"note": bad_text},
        effect_on_resolve={"note": bad_text},
        effect_on_fail={"metrics": {"民心": -1}, "note": bad_text},
        resolve_condition=bad_text,
        fail_condition=bad_text,
    )
    issue_row = db.conn.execute("SELECT title, tags, ongoing_effects, effect_on_fail FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert "\\ud800" in issue_row["title"]
    assert "\\ud800" in issue_row["tags"]
    assert "中文" in issue_row["effect_on_fail"]

    db.advance_issue(state, issue_id, trigger_kind=bad_text, trigger_ref=bad_text, stage_text=bad_text, narrative=bad_text, metric_delta={"note": bad_text})
    adv_row = db.conn.execute("SELECT trigger_kind, trigger_ref, to_stage_text, narrative, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id DESC", (issue_id,)).fetchone()
    assert all("中文" in adv_row[col] and "\\ud800" in adv_row[col] for col in adv_row.keys() if isinstance(adv_row[col], str))

    db.close_issue(state, issue_id, reason="failed", narrative=bad_text)
    close_row = db.conn.execute("SELECT narrative FROM issue_advances WHERE issue_id=? ORDER BY id DESC", (issue_id,)).fetchone()
    assert "中文" in close_row["narrative"] and "\\ud800" in close_row["narrative"]
