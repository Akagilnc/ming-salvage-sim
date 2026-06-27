from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parents[1] / "content" / "prompts"


def test_extractor_prompts_route_army_effects_away_from_faction_delta():
    """#356: military effects must not be keyed as faction changes."""
    shared = (PROMPT_DIR / "score_extractor_shared.md").read_text(encoding="utf-8")
    internal = (PROMPT_DIR / "score_extractor_internal.md").read_text(encoding="utf-8")

    assert "军队不是派系" in shared
    assert "派系变化" in shared
    assert "合法派系" in shared
    assert "军队变化" in shared
    assert "军队不是派系" in internal
