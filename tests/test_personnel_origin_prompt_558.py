import json
import re
from pathlib import Path


PROMPT = Path("content/prompts/score_extractor_personnel_secret.md")


def test_decree_driven_personnel_examples_reference_promulgated_dossier():
    text = PROMPT.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    assert match is not None
    example = json.loads(match.group(1))
    items = example["人物变更"]

    decree_items = [item for item in items if "诏书明文" in item.get("reason", "") or "奉旨" in item.get("reason", "")]
    assert decree_items
    assert all(item["来源引用"] == "dossier:17" for item in decree_items)
    assert "dossier:17" in text[: match.start()]

    inline = re.search(r"奉旨安抚毛文龙.*?可写 `(\{.*?\})`", text)
    assert inline is not None
    inline_item = json.loads(inline.group(1))
    assert inline_item["来源引用"] == "dossier:17"
