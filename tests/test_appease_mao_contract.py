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
