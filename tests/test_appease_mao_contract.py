from pathlib import Path

from ming_sim.simulation import _extractor_context_payload


ROOT = Path(__file__).resolve().parents[1]


def test_appease_mao_extractor_contract_documents_commitment_boundary():
    issue_prompt = (ROOT / "content/prompts/score_extractor_issues.md").read_text()
    personnel_prompt = (ROOT / "content/prompts/score_extractor_personnel_secret.md").read_text()
    schema_doc = (ROOT / "docs/DELTA_SCHEMA.md").read_text()

    assert "安抚毛文龙" in issue_prompt
    assert "stop_condition" in issue_prompt
    assert "一次性赏赐" in issue_prompt
    assert "不立局势" in issue_prompt
    assert "评定" in personnel_prompt
    assert "loyalty" in personnel_prompt
    assert "stop_condition" in schema_doc
    assert "评定" in schema_doc


def test_appease_mao_stop_condition_is_excluded_from_prompt_auto_close_rule():
    issue_prompt = (ROOT / "content/prompts/score_extractor_issues.md").read_text()

    assert "人物承诺型 `stop_condition` 不套用 `resolve_condition` 达标即结案规则" in issue_prompt
    assert "`condition_role:\"commitment_stop_condition\"`" in issue_prompt
    assert "即使当前 loyalty 已达阈值" in issue_prompt
    assert "不要写 `结案局势`" in issue_prompt


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
