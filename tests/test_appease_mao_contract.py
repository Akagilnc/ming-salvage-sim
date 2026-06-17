from pathlib import Path


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
    assert "即使当前 loyalty 已达阈值" in issue_prompt
    assert "不要写 `结案局势`" in issue_prompt
