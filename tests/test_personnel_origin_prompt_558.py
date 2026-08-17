"""#558 personnel prompt：诏令驱动人物变更示例须回指已颁布 dossier。

#1185：不锁中文 reason 散文；咬 来源引用 协议 dossier:<id>。
"""

import json
import re
from pathlib import Path


PROMPT = Path("content/prompts/score_extractor_personnel_secret.md")
_DOSSIER_REF = re.compile(r"^dossier:\d+$")


def test_decree_driven_personnel_examples_reference_promulgated_dossier():
    text = PROMPT.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    assert match is not None
    items = json.loads(match.group(1))["人物变更"]

    dossier_items = [
        it for it in items if _DOSSIER_REF.fullmatch(str(it.get("来源引用", "")))
    ]
    assert dossier_items
    refs = {it["来源引用"] for it in dossier_items}
    assert len(refs) == 1
    ref = next(iter(refs))
    assert ref in text[: match.start()]
    assert ref in re.findall(r'"来源引用"\s*:\s*"(dossier:\d+)"', text)
