"""#494 featured minister/faction dossiers 经公共接缝装配。

#1185：不锁长散文。结构键 + identity 分桶差分 + 北辰可分 + 派系块只注入一次。
北辰可分性只比 minister_dossier 的动机/包袱/事例——姓名/身份/官职/技能/轴/派系不得自证。
"""

from dataclasses import replace
import re

from ming_sim.context import (
    character_context_with_db,
    faction_context_with_db,
    minister_dossier,
)


SEVEN_FACTIONS = ("阉党", "皇党", "东林", "军队", "宗室", "中立", "西学")
_DOSSIER_KEYS = ("身份：", "动机：", "包袱：", "事例：")


def _court_ministers(content):
    return [
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
        and c.faction in SEVEN_FACTIONS
        and c.status == "active"
    ]


def _dossier_voice(dossier_text: str) -> tuple[str, str, str]:
    """仅提取动机/包袱/事例。身份/脾性不得充当 distinctness 自证。"""
    parts: list[str] = []
    for key in ("动机：", "包袱：", "事例："):
        m = re.search(rf"{re.escape(key)}([^；]*)", dossier_text)
        assert m is not None, f"missing {key} in {dossier_text!r}"
        parts.append(m.group(1).strip())
    return parts[0], parts[1], parts[2]


def test_every_active_seven_faction_minister_has_featured_dossier(game):
    _db, _state, content = game
    ministers = _court_ministers(content)
    assert len(ministers) >= 40
    for character in ministers:
        rendered = minister_dossier(character)
        assert all(k in rendered for k in _DOSSIER_KEYS)
        assert "未有专门 dossier" not in rendered


def test_seven_faction_dossiers_are_objective_and_identity_scoped(game):
    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    for faction in SEVEN_FACTIONS:
        rendered = faction_context_with_db(replace(base, faction=faction, identity=65), db)
        assert "【派系档料】" in rendered
        assert not re.search(r"\d+", rendered)

    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    low = faction_context_with_db(replace(base, identity=20), db)
    assert len({low, middle, high}) == 3
    assert len(high) > len(middle) > len(low)


def test_north_star_ministers_have_distinct_featured_voices(game):
    db, _state, content = game
    names = ("毕自严", "杨嗣昌", "王绍徽")
    voices = []
    for name in names:
        character = content.characters[name]
        full = character_context_with_db(character, db)
        assert name in full and "【人物档料】" in full
        dossier = minister_dossier(character)
        assert all(k in dossier for k in _DOSSIER_KEYS)
        assert dossier in full
        # 可分性只比 dossier 动机/包袱/事例，不让姓名/身份/官职/技能/轴/派系块自证。
        voices.append(_dossier_voice(dossier))
    assert len(set(voices)) == 3


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
            minister, config,
            CourtContext(state=state, db=db, previous_summary=""),
            db,
        )

    rendered = "\n".join(captured["instructions"])
    assert rendered.count(faction_context_with_db(minister, db)) == 1
    assert "【人物档料】" in rendered and "【派系档料】" in rendered
