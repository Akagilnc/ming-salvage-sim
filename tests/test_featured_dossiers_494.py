"""#494 featured minister/faction dossiers reach the public context seam.

Coverage is the static asset fields the assembler must deliver, and which
faction blocks an identity bucket may see. Static asset identity bucketing is
not LLM free-text locking (#1897 T1).
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
    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    for faction in SEVEN_FACTIONS:
        rendered = faction_context_with_db(replace(base, faction=faction, identity=65), db)
        row = _faction_row(db, faction)
        core = _FACTION_DOSSIERS[faction]["core"]
        internal = _FACTION_DOSSIERS[faction]["internal"]
        assert core in rendered
        assert internal not in rendered
        assert str(row["agenda"]) in rendered
        assert str(int(row["satisfaction"])) not in rendered
        assert str(int(row["leverage"])) not in rendered

    faction = base.faction
    core = _FACTION_DOSSIERS[faction]["core"]
    internal = _FACTION_DOSSIERS[faction]["internal"]
    agenda = str(_faction_row(db, faction)["agenda"])
    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    low = faction_context_with_db(replace(base, identity=20), db)
    assert len({low, middle, high}) == 3
    assert core in middle and core in high and core not in low
    assert agenda in middle and agenda in high and agenda not in low
    assert internal in high and internal not in middle and internal not in low


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
