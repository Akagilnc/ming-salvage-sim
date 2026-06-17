import pytest

import web_app


def test_humanize_character_loyalty_condition_hides_machine_threshold():
    text = web_app._humanize_condition("character.毛文龙.loyalty >= 65")

    assert text == "毛文龙忠诚回稳"
    assert "character" not in text
    assert "65" not in text


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
    text = web_app._humanize_condition(raw)

    assert text == "毛文龙忠诚回稳"
    assert "character" not in text
    assert "65" not in text


def test_humanize_non_character_condition_keeps_existing_region_translation():
    raw = "region.liaodong.controlled_by == ming"

    assert web_app._humanize_condition(raw) == "地区：辽东·归属 == 大明"


def test_humanize_character_status_condition_hides_machine_key():
    text = web_app._humanize_condition("character.袁崇焕.status == active")

    assert text == "袁崇焕状态为在朝"
    assert "character" not in text
    assert "active" not in text
