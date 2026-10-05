"""#494 featured minister/faction dossiers reach the public context seam.

Coverage is structured delivery and identity scoping. Presentation prose is not
the contract (#1897 F3：不锁自由正文机械比较).
"""

from dataclasses import replace

from ming_sim.assets import load_json_asset
from ming_sim.context import (
    _FACTION_DOSSIERS,
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


def _faction_row(db, faction: str):
    return db.conn.execute(
        "SELECT agenda, satisfaction, leverage FROM factions WHERE name = ?",
        (faction,),
    ).fetchone()


def test_every_active_seven_faction_minister_has_featured_dossier(game):
    _db, _state, content = game
    ministers = _court_ministers(content)
    assert len(ministers) >= 40
    for character in ministers:
        rendered = minister_dossier(character)
        assert isinstance(rendered, str) and rendered.strip()
        asset = _DOSSIERS.get(character.name)
        if asset is not None:
            for field in ("identity", *_VOICE_FIELDS):
                assert str(asset.get(field) or "").strip()
        else:
            assert str(character.summary or "").strip()


def test_seven_faction_dossiers_are_objective_and_identity_scoped(game):
    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    for faction in SEVEN_FACTIONS:
        rendered = faction_context_with_db(replace(base, faction=faction, identity=65), db)
        row = _faction_row(db, faction)
        assert isinstance(rendered, str) and rendered.strip()
        # 客观层：满意度／杠杆裸数不得进呈现（P4）；agenda 为可呈结构字段，存在性即可。
        assert str(int(row["satisfaction"])) not in rendered
        assert str(int(row["leverage"])) not in rendered
        assert str(row["agenda"] or "").strip()

    faction = base.faction
    assert faction in _FACTION_DOSSIERS
    assert "core" in _FACTION_DOSSIERS[faction] and "internal" in _FACTION_DOSSIERS[faction]
    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    low = faction_context_with_db(replace(base, identity=20), db)
    # 身份分桶改变供料长度／内容面；不锁具体散文块。
    assert len({low, middle, high}) == 3
    assert len(low) < len(middle) <= len(high)


def test_north_star_ministers_have_distinct_featured_voices(game):
    db, _state, content = game
    names = ("毕自严", "杨嗣昌", "王绍徽")
    voices = []
    for name in names:
        character = content.characters[name]
        full = character_context_with_db(character, db)
        assert isinstance(full, str) and name in full
        dossier = minister_dossier(character)
        assert isinstance(dossier, str) and dossier.strip()
        voice = tuple(str(_DOSSIERS[name][field]) for field in _VOICE_FIELDS)
        assert all(part.strip() for part in voice)
        voices.append(voice)
    assert len(set(voices)) == 3
