"""现役 issue_payloads：机器条件不泄漏给玩家，保留人物身份与高低区别。"""

from types import SimpleNamespace

import pytest

import web_app


def _h(raw: str, game) -> str:
    db, state, _ = game
    issue_id = db.insert_issue(
        state, kind="situation", title="条件投影", resolve_condition=raw
    )
    runtime = SimpleNamespace(db=db, state=state)
    payload = next(
        row for row in web_app.WebGame.issue_payloads(runtime) if row["id"] == issue_id
    )
    return payload["resolve_condition"]


def _no_token(text: str, token: str) -> None:
    assert token not in text


def test_humanize_character_loyalty_condition_hides_machine_threshold(game):
    text = _h("character.毛文龙.loyalty >= 65", game)
    assert "毛文龙" in text
    for token in ("character", "loyalty", "65"):
        _no_token(text, token)


@pytest.mark.parametrize("raw", [
    "character.毛文龙.loyalty >= 65",
    "  character.毛文龙.loyalty   >=   65   ",
    "character.毛文龙.loyalty>65",
    "character.毛文龙.loyalty   >   65",
])
def test_humanize_character_loyalty_condition_variants(game, raw):
    assert _h(raw, game) == _h("character.毛文龙.loyalty >= 65", game)


def test_humanize_non_character_condition_keeps_existing_region_translation(game):
    text = _h("region.liaodong.controlled_by == ming", game)
    for token in ("region", "liaodong", "controlled_by", "ming"):
        _no_token(text, token)


def test_humanize_character_status_condition_hides_machine_key(game):
    text = _h("character.袁崇焕.status == active", game)
    assert "袁崇焕" in text
    for token in ("character", "status", "active"):
        _no_token(text, token)


def test_humanize_character_location_condition_uses_field_label_and_value_label(game):
    text = _h("character.毛文龙.location == liaodong", game)
    assert "毛文龙" in text
    for token in ("character", "location", "liaodong"):
        _no_token(text, token)


def test_humanize_character_low_loyalty_condition_hides_machine_threshold(game):
    high = _h("character.毛文龙.loyalty >= 65", game)
    low = _h("character.毛文龙.loyalty <65", game)
    assert "毛文龙" in low
    assert low != high
    for token in ("character", "loyalty", "65"):
        _no_token(low, token)
