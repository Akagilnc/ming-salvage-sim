from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parents[1] / "content" / "prompts"


def test_extractor_prompts_route_army_effects_away_from_faction_delta():
    """#356: military effects must not be keyed as faction changes."""
    shared = (PROMPT_DIR / "score_extractor_shared.md").read_text(encoding="utf-8")
    internal = (PROMPT_DIR / "score_extractor_internal.md").read_text(encoding="utf-8")

    assert "`armies` 表、army_id 或具体军号不是派系" in shared
    assert "派系变化" in shared
    assert "合法派系" in shared
    assert "合法派系名 `军队`" in shared
    assert "军队变化" in shared
    assert "不得把 `armies`、army_id 或具体军号写成 `派系变化` key" in internal
    assert "合法派系名 `军队` 仍可写 `派系变化`" in internal
