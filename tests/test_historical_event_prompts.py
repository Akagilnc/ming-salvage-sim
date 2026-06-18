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
