from dataclasses import replace
import re

from ming_sim.context import (
    character_context_with_db,
    faction_context_with_db,
    minister_dossier,
)


SEVEN_FACTIONS = ("阉党", "皇党", "东林", "军队", "宗室", "中立", "西学")


def _court_ministers(content):
    return [
        character
        for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and character.faction in SEVEN_FACTIONS
        and character.status == "active"
    ]


def test_every_active_seven_faction_minister_has_featured_dossier(game):
    _db, _state, content = game

    ministers = _court_ministers(content)
    assert len(ministers) >= 40
    assert all("身份：" in minister_dossier(character) for character in ministers)
    assert all("动机：" in minister_dossier(character) for character in ministers)
    assert all("包袱：" in minister_dossier(character) for character in ministers)
    assert all("事例：" in minister_dossier(character) for character in ministers)
    assert all("未有专门 dossier" not in minister_dossier(character) for character in ministers)


def test_seven_faction_dossiers_are_objective_and_identity_scoped(game):
    db, _state, content = game
    base = next(character for character in content.characters.values() if character.faction == "东林")

    for faction in SEVEN_FACTIONS:
        character = replace(base, faction=faction, identity=65)
        rendered = faction_context_with_db(character, db)
        assert "【派系档料】" in rendered
        assert not re.search(r"\d+", rendered)

    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    low = faction_context_with_db(replace(base, identity=20), db)
    assert "这个党是什么样一伙人" in middle
    assert "这个党是什么样一伙人" in high
    assert "这个党是什么样一伙人" not in low
    assert "其内部" in high
    assert "其内部" not in middle


def test_north_star_ministers_have_distinct_featured_voices(game):
    db, _state, content = game
    rendered = {
        name: character_context_with_db(content.characters[name], db)
        for name in ("毕自严", "杨嗣昌", "王绍徽")
    }

    assert len(set(rendered.values())) == 3
    assert "财政" in rendered["毕自严"]
    assert "边务" in rendered["杨嗣昌"]
    assert "党" in rendered["王绍徽"]


def test_minister_agent_injects_faction_dossier_once(game):
    """人物档料与派系档料各有一个装配入口，不重复占用 prompt。"""
    from unittest.mock import MagicMock, patch

    from ming_sim.models import CourtContext, LLMConfig
    from ming_sim.registry import create_minister_agent

    db, state, content = game
    minister = content.characters["毕自严"]
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    config = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry._ctx", return_value=content), \
         patch("ming_sim.registry._skills_for", return_value=None), \
         patch("ming_sim.registry.build_minister_tools", return_value=[]):
        create_minister_agent(
            minister,
            config,
            CourtContext(state=state, db=db, previous_summary=""),
            db,
        )

    rendered = "\n".join(captured["instructions"])
    assert rendered.count("【派系档料】") == 1
