"""#558 personnel prompt：诏令驱动人物变更示例须回指已颁布 dossier。

#1185：不锁中文 reason 散文；咬 来源引用 协议 dossier:<id>。
inline 毛文龙 JSON 独立解析（不靠 来源引用=dossier:* 循环自证选样）。
"""

import json
import re
from pathlib import Path


PROMPT = Path("content/prompts/score_extractor_personnel_secret.md")
_DOSSIER_REF = re.compile(r"^dossier:\d+$")


def test_decree_driven_personnel_examples_reference_promulgated_dossier():
    text = PROMPT.read_text(encoding="utf-8")

    # ⑦ 独立解析 inline 毛文龙 JSON（反引号包裹），验证引用格式与已颁布 dossier。
    # 选样靠姓名+inline 位置，不靠 来源引用 预过滤（避免循环自证）。
    inline_m = re.search(r'`(\{\s*"name"\s*:\s*"毛文龙".*?\})`', text, re.S)
    assert inline_m is not None
    inline_obj = json.loads(inline_m.group(1))
    inline_preamble = text[: inline_m.start()]
    inline_promulgated = set(re.findall(r"dossier:\d+", inline_preamble))
    assert inline_promulgated
    inline_ref = str(inline_obj.get("来源引用", ""))
    assert _DOSSIER_REF.fullmatch(inline_ref)
    assert inline_ref in inline_promulgated

    # fenced 完整示例：诏令驱动项经「颁布案卷」姓名窗识别（不预滤 来源引用）。
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    assert match is not None
    preamble = text[: match.start()]
    items = json.loads(match.group(1))["人物变更"]

    promulgated = set(re.findall(r"dossier:\d+", preamble))
    assert promulgated
    driven_names = set()
    for m in re.finditer(r"颁布案卷\s*`?(dossier:\d+)`?(.{0,60})", preamble, re.S):
        window = m.group(2)
        for it in items:
            name = str(it.get("name") or "")
            if name and name in window:
                driven_names.add(name)
    # 毛文龙亦为 inline 已验的诏令驱动样本，fenced 中同名须一并覆盖。
    driven_names.add("毛文龙")
    decree_items = [it for it in items if str(it.get("name") or "") in driven_names]
    assert decree_items
    assert any(str(it.get("name") or "") == "毛文龙" for it in decree_items)

    for it in decree_items:
        ref = str(it.get("来源引用", ""))
        assert _DOSSIER_REF.fullmatch(ref)
        assert ref in promulgated
