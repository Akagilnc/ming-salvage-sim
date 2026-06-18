from pathlib import Path


def test_season_simulator_prompts_historical_battle_results_as_main_ledger_facts():
    """#189：历史战斗软判须在叙事中写出可抽取的主账事实。"""
    prompt = (
        Path(__file__).resolve().parents[1]
        / "content"
        / "prompts"
        / "season_simulator.md"
    ).read_text(encoding="utf-8")

    assert "世界状态主账" in prompt
    assert "哪城丢" in prompt
    assert "谁死" in prompt
    assert "军损" in prompt
    assert "军队变化" in prompt
    assert "地区变化" in prompt
    assert "人物变更" in prompt
    assert "reason / 原因里带上事件名或战役名" in prompt


def test_extractor_prompts_preserve_strategic_battle_result_contract():
    """#189：extractor prompt 要保住同信封主账与 reason 锚点，不让真实输出漂走。"""
    prompt_dir = Path(__file__).resolve().parents[1] / "content" / "prompts"
    military = (prompt_dir / "score_extractor_military_external.md").read_text(encoding="utf-8")
    personnel = (prompt_dir / "score_extractor_personnel_secret.md").read_text(encoding="utf-8")
    issues = (prompt_dir / "score_extractor_issues.md").read_text(encoding="utf-8")

    assert "战略/外敌战事" in issues
    assert "不能只写" in issues
    assert "世界状态主账" in issues
    assert "同一信封" in issues

    for prompt in (military, personnel):
        assert "战略/外敌战事" in prompt
        assert "reason" in prompt
        assert "原因" in prompt
        assert "事件名或战役名" in prompt
