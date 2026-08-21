from types import SimpleNamespace

import pytest

from ming_sim.simulation import EXTRACTION_MODULES, extract_scores_by_modules_with_agno


class FakeAgent:
    def __init__(self, *responses: str):
        self._responses = list(responses)
        self.calls = 0
        self.prompts = []

    def run(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeAgent response exhausted")
        return SimpleNamespace(content=self._responses.pop(0))


def _empty_module_json(module: str) -> str:
    if module == "internal":
        return '{"国势变化": {}, "钱粮收支": [], "财政制度变化": [], "新立月度收支": [], "裁撤月度收支": [], "派系变化": [], "阶级变化": {}, "地区变化": {}}'
    if module == "military_external":
        return '{"军队变化": {}, "建军": [], "势力变化": {}, "外交态度": {}}'
    if module == "issues":
        return '{"局势推进": [], "新立局势": [], "事件结局": {}, "撤销局势": [], "结案局势": []}'
    if module == "personnel_secret":
        return '{"人物变更": [], "密令副作用": [], "密令结案": [], "崇祯结局": {}}'
    if module == "relations":
        return '{"大臣互动": []}'
    raise AssertionError(module)


def _strategic_result_internal_json() -> str:
    return '{"国势变化": {}, "钱粮收支": [], "财政制度变化": [], "新立月度收支": [], "裁撤月度收支": [], "派系变化": [], "阶级变化": {}, "地区变化": {"beizhili": {"military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}}}'


def test_event_outcome_label_retry_reruns_only_issues_extractor(game):
    """ADR0014/#193：结局标签无法归一时，只重跑标签所在 issues extractor，不重跑叙事或其它 extractor。"""
    db, state, _content = game
    state.year = 1629
    state.period = 11
    agents = {module: FakeAgent(_empty_module_json(module)) for module in EXTRACTION_MODULES}
    agents["internal"] = FakeAgent(_strategic_result_internal_json())
    agents["issues"] = FakeAgent(
        '{"局势推进": [], "新立局势": [{"来源类型": "event_pool", "编号": "jisi_lubian"}], "事件结局": {"jisi_lubian": "大胜"}, "撤销局势": [], "结案局势": []}',
        '{"局势推进": [], "新立局势": [{"来源类型": "event_pool", "编号": "jisi_lubian"}], "事件结局": {"jisi_lubian": "入塞被遏"}, "撤销局势": [], "结案局势": []}',
    )

    extracted, _output, _trace = extract_scores_by_modules_with_agno(
        agents,
        db,
        state,
        "己巳之变后金入塞，邸报正文保持不重跑。",
        decree_text="",
        parallel=False,
    )

    assert extracted["事件结局"] == {"jisi_lubian": "入塞被遏"}
    assert agents["issues"].calls == 2
    for module in EXTRACTION_MODULES:
        if module != "issues":
            assert agents[module].calls == 1
    assert "事件结局标签无法归一" in agents["issues"].prompts[1]


def test_event_outcome_label_alias_normalizes_without_retry(game):
    """ADR0014/#193：合法别名在 extractor 层归一为闭合集合内标签，不额外重跑 issues。"""
    db, state, _content = game
    state.year = 1629
    state.period = 11
    agents = {module: FakeAgent(_empty_module_json(module)) for module in EXTRACTION_MODULES}
    agents["internal"] = FakeAgent(_strategic_result_internal_json())
    agents["issues"] = FakeAgent(
        '{"局势推进": [], "新立局势": [{"来源类型": "event_pool", "编号": "jisi_lubian"}], "事件结局": {"jisi_lubian": "入塞遭遏"}, "撤销局势": [], "结案局势": []}',
    )

    extracted, _output, _trace = extract_scores_by_modules_with_agno(
        agents,
        db,
        state,
        "己巳之变后金入塞但遭阻遏。",
        decree_text="",
        parallel=False,
    )

    assert extracted["事件结局"] == {"jisi_lubian": "入塞被遏"}
    assert agents["issues"].calls == 1


def test_event_outcome_label_retry_cap_fails_loud(game):
    """ADR0014/#193：结局标签重试有上限，超限 fail-loud，不写空/假标签。"""
    db, state, _content = game
    state.year = 1629
    state.period = 11
    agents = {module: FakeAgent(_empty_module_json(module)) for module in EXTRACTION_MODULES}
    agents["internal"] = FakeAgent(_strategic_result_internal_json())
    agents["issues"] = FakeAgent(
        '{"局势推进": [], "新立局势": [{"来源类型": "event_pool", "编号": "jisi_lubian"}], "事件结局": {"jisi_lubian": "大胜"}, "撤销局势": [], "结案局势": []}',
        '{"局势推进": [], "新立局势": [{"来源类型": "event_pool", "编号": "jisi_lubian"}], "事件结局": {"jisi_lubian": "惨胜"}, "撤销局势": [], "结案局势": []}',
    )

    with pytest.raises(ValueError, match="事件结局标签无法归一"):
        extract_scores_by_modules_with_agno(
            agents,
            db,
            state,
            "己巳之变后金入塞，邸报正文保持不重跑。",
            decree_text="",
            parallel=False,
            event_outcome_retry_limit=1,
        )

    assert agents["issues"].calls == 2
    for module in EXTRACTION_MODULES:
        if module != "issues":
            assert agents[module].calls == 1
