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
    preamble = text[: match.start()]
    items = json.loads(match.group(1))["人物变更"]

    # 示例前已颁布的案卷；诏令驱动项须独立于 来源引用 识别（不靠 reason 散文）。
    promulgated = set(re.findall(r"dossier:\d+", preamble))
    assert promulgated
    driven_names = set()
    for m in re.finditer(r"颁布案卷\s*`?(dossier:\d+)`?(.{0,60})", preamble, re.S):
        window = m.group(2)
        for it in items:
            name = str(it.get("name") or "")
            if name and name in window:
                driven_names.add(name)
    decree_items = [it for it in items if str(it.get("name") or "") in driven_names]
    assert decree_items

    for it in decree_items:
        ref = str(it.get("来源引用", ""))
        assert _DOSSIER_REF.fullmatch(ref)
        assert ref in promulgated
