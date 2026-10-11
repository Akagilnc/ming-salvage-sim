import json
from tests.section_rejection_helpers import game  # noqa: F401  # pytest fixture discovery





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
    row = db.conn.execute(
        "SELECT item_json, reason, category, source FROM rejection_reports"
    ).fetchone()
    item = json.loads(row["item_json"])
    # 内容身份：坏 surrogate 经 sanitize 后字段值含转义序列；不钉 JSON 载体字面编码。
    assert item["title"] == "中文\\ud800"
    assert row["reason"] == "坏"
    assert row["category"] == "invalid_enum"
    assert row["source"] == "player_decree"


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
    issue_row = db.conn.execute(
        "SELECT title, tags, ongoing_effects, effect_on_fail FROM issues WHERE id=?",
        (issue_id,),
    ).fetchone()
    # 纯文本列与 JSON 列均核字段值，不扫序列化载体字面。
    escaped = "中文\\ud800"
    assert issue_row["title"] == escaped
    assert json.loads(issue_row["tags"]) == [escaped]
    assert json.loads(issue_row["effect_on_fail"]) == {"metrics": {"民心": -1}, "note": escaped}

    db.advance_issue(
        state, issue_id,
        trigger_kind=bad_text, trigger_ref=bad_text, stage_text=bad_text,
        narrative=bad_text, metric_delta={"note": bad_text},
    )
    adv_row = db.conn.execute(
        "SELECT trigger_kind, trigger_ref, to_stage_text, narrative, metric_delta "
        "FROM issue_advances WHERE issue_id=? ORDER BY id DESC",
        (issue_id,),
    ).fetchone()
    assert adv_row["trigger_kind"] == escaped
    assert adv_row["trigger_ref"] == escaped
    assert adv_row["to_stage_text"] == escaped
    assert adv_row["narrative"] == escaped
    assert json.loads(adv_row["metric_delta"]) == {"note": escaped}

    db.close_issue(state, issue_id, reason="failed", narrative=bad_text)
    close_row = db.conn.execute(
        "SELECT narrative FROM issue_advances WHERE issue_id=? ORDER BY id DESC",
        (issue_id,),
    ).fetchone()
    assert close_row["narrative"] == escaped
