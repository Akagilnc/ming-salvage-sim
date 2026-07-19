from pathlib import Path

from ming_sim.agents import build_simulator_context
from ming_sim.simulation import build_simulator_payload, _extractor_context_payload


ROOT = Path(__file__).resolve().parents[1]


def test_appease_mao_active_issue_context_marks_character_loyalty_stop_condition(game):
    db, state, _ = game
    db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·进行中",
        origin_kind="decree",
        bar_value=20,
        stage_text="遣臣持诏赴皮岛",
        cancellable="decree",
        resolve_condition="character.毛文龙.loyalty >= 65",
    )

    payload = _extractor_context_payload(db, state, "", "")
    issue = next(
        item for item in payload["active_issues"] if item["title"] == "安抚毛文龙·进行中"
    )

    assert issue["resolve_condition"] == "character.毛文龙.loyalty >= 65"
    assert issue["condition_role"] == "commitment_stop_condition"
    assert "不要按 resolve_condition 达标自动结案" in issue["condition_note"]


def test_appease_mao_simulator_payload_marks_character_loyalty_stop_condition(game):
    db, state, _ = game
    db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·进行中",
        origin_kind="decree",
        bar_value=20,
        stage_text="遣臣持诏赴皮岛",
        cancellable="decree",
        resolve_condition="character.毛文龙.loyalty >= 65",
    )

    payload = build_simulator_payload(state, db, "", "")
    issue = next(
        item for item in payload["active_issues"] if item["title"] == "安抚毛文龙·进行中"
    )

    assert issue["结案条件"] == "人物属性条件由引擎按定性档位复核"
    assert issue["condition_role"] == "commitment_stop_condition"
    assert "不要按 resolve_condition 达标自动结案" in issue["condition_note"]


def test_simulator_projects_structured_character_stop_condition_but_keeps_machine_gate(game):
    db, state, _ = game
    db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·结构化承诺",
        origin_kind="decree",
        bar_value=20,
        stage_text="遣臣持诏赴皮岛",
        cancellable="decree",
        stop_condition={"character.毛文龙.loyalty": ">=65"},
        commitment_kind="until_stop",
    )

    simulator = build_simulator_payload(state, db, "", "")
    simulator_issue = next(
        item for item in simulator["active_issues"] if item["title"] == "安抚毛文龙·结构化承诺"
    )
    extractor = _extractor_context_payload(db, state, "", "")
    extractor_issue = next(
        item for item in extractor["active_issues"] if item["title"] == "安抚毛文龙·结构化承诺"
    )

    assert "65" not in simulator_issue["stop_condition"]
    assert "人物属性条件" in simulator_issue["stop_condition"]
    assert simulator_issue["commitment_progress"]["remaining_to_goal"] == "距达标仍有差距"
    assert "65" in extractor_issue["stop_condition"]
    assert "remaining_to_goal" in extractor_issue["commitment_progress"]


def test_simulator_projects_issue_character_deltas_but_preserves_effect_details(game):
    db, state, _ = game
    db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·人物效果",
        origin_kind="decree",
        bar_value=20,
        stage_text="遣臣持诏赴皮岛",
        ongoing_effects={
            "人物变更": [{"name": "毛文龙", "动作": "评定", "loyalty": 13, "reason": "每月安抚"}],
        },
        effect_on_resolve={
            "人物变更": [{"name": "毛文龙", "动作": "评定", "ability": 14, "reason": "办成"}],
        },
        effect_on_fail={
            "人物变更": [{"name": "毛文龙", "动作": "评定", "integrity": -15, "reason": "办砸"}],
            "metrics": {"皇威": 2468},
        },
    )

    simulator = build_simulator_payload(state, db, "", "")
    simulator_issue = next(
        item for item in simulator["active_issues"] if item["title"] == "安抚毛文龙·人物效果"
    )
    rendered = build_simulator_context(simulator)

    assert '"loyalty": 13' not in rendered
    assert '"ability": 14' not in rendered
    assert '"integrity": -15' not in rendered
    assert "2468" in rendered
    assert simulator_issue["当前每月效果"]["人物变更"][0] == {
        "name": "毛文龙", "动作": "评定", "reason": "每月安抚",
    }
    assert simulator_issue["成功效果"]["人物变更"][0] == {
        "name": "毛文龙", "动作": "评定", "reason": "办成",
    }
    assert simulator_issue["失败效果"]["人物变更"][0] == {
        "name": "毛文龙", "动作": "评定", "reason": "办砸",
    }
    assert simulator_issue["失败效果"]["metrics"]["皇威"] == 2468


def test_appease_mao_commitment_bar_100_stays_active_until_explicit_close(game):
    db, state, _ = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·进行中",
        origin_kind="decree",
        bar_value=90,
        stage_text="遣臣持诏赴皮岛",
        cancellable="decree",
        resolve_condition="character.毛文龙.loyalty >= 65",
        effect_on_resolve={"metrics": {"皇威": 1}},
    )

    row = db.advance_issue(
        state,
        issue_id,
        trigger_kind="decree",
        delta_bar=20,
        narrative="承办有进展，但承诺完成仍待专门闭环。",
    )

    assert row["bar_value"] == 100
    assert row["status"] == "active"
    assert row["closed_turn"] is None


def test_appease_mao_commitment_rejects_direct_resolved_close_until_completion_flow(game):
    """post-merge CMR：人物承诺型 stop_condition 不由 close_issues resolved 直接结案。"""
    import ming_sim.issues as I

    db, state, _ = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·进行中",
        origin_kind="decree",
        bar_value=100,
        stage_text="毛文龙态度已有转圜",
        cancellable="decree",
        resolve_condition="character.毛文龙.loyalty >= 65",
        effect_on_resolve={"metrics": {"皇威": 1}},
    )

    out = I.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "误按承诺完成结案"}]},
    )

    close = out["closes"][0]
    assert close["rejected"] is True
    assert close["category"] == "invalid_enum"
    assert "承诺" in close["reason"]
    row = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row["status"] == "active"
