"""#494 featured minister/faction dossiers reach the public context seam.

Coverage is the asset fields the assembler must deliver, and which faction
blocks an identity bucket may see. Presentation labels are not the contract.
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
        asset = _DOSSIERS.get(character.name)
        if asset is not None:
            for field in ("identity", *_VOICE_FIELDS):
                value = str(asset[field]).strip()
                assert value and value in rendered
        else:
            summary = (character.summary or "").strip()
            assert summary and summary in rendered


def test_seven_faction_dossiers_are_objective_and_identity_scoped(game):
    """#494：identity 桶决定供料来源；最低桶不喂 dossier/议程原值。

    契约=已知源字段原值搬运（正/负），不复制渲染模板、不扫任意禁词。
    """
    from ming_sim.context import _identity_bucket

    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    assert _identity_bucket(20) == "low"
    assert _identity_bucket(60) == "middle"
    assert _identity_bucket(90) == "high"

    for faction in SEVEN_FACTIONS:
        # middle 桶：core + agenda 原值入面；internal 不喂。
        rendered = faction_context_with_db(replace(base, faction=faction, identity=65), db)
        row = _faction_row(db, faction)
        core = _FACTION_DOSSIERS[faction]["core"]
        internal = _FACTION_DOSSIERS[faction]["internal"]
        agenda = str(row["agenda"])
        assert core in rendered
        assert agenda in rendered
        assert internal not in rendered

    faction = base.faction
    core = _FACTION_DOSSIERS[faction]["core"]
    internal = _FACTION_DOSSIERS[faction]["internal"]
    agenda = str(_faction_row(db, faction)["agenda"])
    low = faction_context_with_db(replace(base, identity=20), db)
    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    assert len({low, middle, high}) == 3
    # 最低桶：dossier/agenda 源原值均不喂。
    assert core not in low and internal not in low and agenda not in low
    # 中桶：core+agenda；不喂 internal。
    assert core in middle and agenda in middle and internal not in middle
    # 高桶：core+internal+agenda。
    assert core in high and internal in high and agenda in high


def test_north_star_ministers_have_distinct_featured_voices(game):
    db, _state, content = game
    names = ("毕自严", "杨嗣昌", "王绍徽")
    voices = []
    for name in names:
        character = content.characters[name]
        full = character_context_with_db(character, db)
        assert name in full
        dossier = minister_dossier(character)
        voice = tuple(str(_DOSSIERS[name][field]) for field in _VOICE_FIELDS)
        assert all(part and part in dossier for part in voice)
        assert dossier in full
        voices.append(voice)
    assert len(set(voices)) == 3
