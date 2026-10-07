"""#494 featured minister/faction dossiers reach the public context seam.

Coverage is the asset fields the assembler must deliver, and which faction
blocks an identity bucket may see. Presentation labels are not the contract.
"""

from dataclasses import replace

from ming_sim.assets import load_json_asset
from ming_sim.context import (
    character_context_with_db,
    faction_context_with_db,
    minister_dossier,
)


SEVEN_FACTIONS = ("阉党", "皇党", "东林", "军队", "宗室", "中立", "西学")
_DOSSIERS = load_json_asset("minister_dossiers.json")
_VOICE_FIELDS = ("motivation", "burden", "episode")


def _court_ministers(content):
    return [
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
        and c.faction in SEVEN_FACTIONS
        and c.status == "active"
    ]


def test_every_active_seven_faction_minister_has_featured_dossier(game):
    """在朝七党大臣均有非空 dossier 装配出口（不锁素材正文子串）。"""
    _db, _state, content = game
    ministers = _court_ministers(content)
    assert len(ministers) >= 40
    for character in ministers:
        rendered = minister_dossier(character)
        assert isinstance(rendered, str) and rendered.strip()


def test_seven_faction_dossiers_are_objective_and_identity_scoped(game):
    """七党 faction_context 随 identity 档位变化（结构化可辨；不锁素材正文）。"""
    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    for faction in SEVEN_FACTIONS:
        rendered = faction_context_with_db(replace(base, faction=faction, identity=65), db)
        assert isinstance(rendered, str) and rendered.strip()

    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    low = faction_context_with_db(replace(base, identity=20), db)
    assert len({low, middle, high}) == 3


def test_north_star_ministers_have_distinct_featured_voices(game):
    """北极星大臣 featured voice 字段元组互异；dossier/context 非空（不锁正文嵌入）。"""
    db, _state, content = game
    names = ("毕自严", "杨嗣昌", "王绍徽")
    voices = []
    for name in names:
        character = content.characters[name]
        full = character_context_with_db(character, db)
        assert isinstance(full, str) and full.strip()
        dossier = minister_dossier(character)
        assert isinstance(dossier, str) and dossier.strip()
        voice = tuple(str(_DOSSIERS[name][field]).strip() for field in _VOICE_FIELDS)
        assert all(voice)
        voices.append(voice)
    assert len(set(voices)) == 3
