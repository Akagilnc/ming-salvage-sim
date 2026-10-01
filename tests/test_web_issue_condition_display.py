"""web 结案条件 humanize：藏机读 key/阈值，人物名保留。

#1185：不锁精确中文展示串；机读 token 不泄漏、变体归一、高/低忠诚可分。
地区/状态/所在 断言 主体·字段·值 三层语义（不恢复整句盯文）。
"""

from __future__ import annotations

import pytest

import web_app


def _h(raw: str) -> str:
    return web_app._humanize_condition(raw)


def _no_token(text: str, token: str) -> None:
    """机读 token 不得以任何形式出现。

    不用 \\w 边界：Python \\w 含汉字，`毛文龙loyalty` / `状态active` / `忠诚65`
    在 (?<!\\w)...(?!\\w) 下会空转漏检。直接禁子串。
    """
    assert token not in text


def test_humanize_character_loyalty_condition_hides_machine_threshold():
    text = _h("character.毛文龙.loyalty >= 65")
    assert "毛文龙" in text
    for tok in ("character", "loyalty", "65"):
        _no_token(text, tok)


@pytest.mark.parametrize(
    "raw",
    [
        "character.毛文龙.loyalty >= 65",
        "  character.毛文龙.loyalty   >=   65   ",
        "character.毛文龙.loyalty>65",
        "character.毛文龙.loyalty   >   65",
    ],
)
def test_humanize_character_loyalty_condition_variants(raw):
    base = _h("character.毛文龙.loyalty >= 65")
    text = _h(raw)
    assert text == base and "毛文龙" in text
    for tok in ("character", "65"):
        _no_token(text, tok)


def test_humanize_non_character_condition_keeps_existing_region_translation():
    raw = "region.liaodong.controlled_by == ming"
    text = _h(raw)
    assert text != raw
    assert text
    for tok in ("region", "liaodong", "controlled_by", "ming"):
        _no_token(text, tok)


def test_humanize_character_status_condition_hides_machine_key():
    text = _h("character.袁崇焕.status == active")
    assert "袁崇焕" in text
    for tok in ("character", "status", "active"):
        _no_token(text, tok)


def test_humanize_character_location_condition_uses_field_label_and_value_label():
    text = _h("character.毛文龙.location == liaodong")
    # 人物 / 字段 / 值
    assert "毛文龙" in text
    for tok in ("character", "location", "liaodong"):
        _no_token(text, tok)


def test_humanize_character_low_loyalty_condition_hides_machine_threshold():
    high = _h("character.毛文龙.loyalty >= 65")
    low = _h("character.毛文龙.loyalty <65")
    assert "毛文龙" in low and low != high
    for tok in ("character", "65"):
        _no_token(low, tok)
