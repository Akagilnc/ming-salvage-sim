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

    契约=按桶供料：应喂源的原值入面；不应喂的源被改写后面不变。
    不复制渲染模板、不按文字值推断来源、不断言私有桶标签。
    """
    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    for faction in SEVEN_FACTIONS:
        char_low = replace(base, faction=faction, identity=20)
        char_mid = replace(base, faction=faction, identity=65)
        char_high = replace(base, faction=faction, identity=90)
        dossier = _FACTION_DOSSIERS[faction]
        core = dossier["core"]
        agenda = str(_faction_row(db, faction)["agenda"])

        # 正：中桶搬运 core + agenda 原值。
        mid = faction_context_with_db(char_mid, db)
        assert core in mid and agenda in mid

        # 负：agenda 源——低桶不喂（改写后面不变）；中桶喂新值。
        low_before = faction_context_with_db(char_low, db)
        probe_agenda = f"AGENDA_PROBE_494_{faction}"
        db.conn.execute(
            "UPDATE factions SET agenda = ? WHERE name = ?",
            (probe_agenda, faction),
        )
        db.conn.commit()
        try:
            assert faction_context_with_db(char_low, db) == low_before
            mid_after = faction_context_with_db(char_mid, db)
            assert probe_agenda in mid_after and core in mid_after
        finally:
            db.conn.execute(
                "UPDATE factions SET agenda = ? WHERE name = ?",
                (agenda, faction),
            )
            db.conn.commit()

        # 负：internal 源——中桶不喂；高桶喂新值。
        old_internal = dossier["internal"]
        probe_internal = f"INTERNAL_PROBE_494_{faction}"
        mid_before = faction_context_with_db(char_mid, db)
        dossier["internal"] = probe_internal
        try:
            assert faction_context_with_db(char_mid, db) == mid_before
            high_after = faction_context_with_db(char_high, db)
            assert probe_internal in high_after and core in high_after
        finally:
            dossier["internal"] = old_internal

        # 负：core 源——低桶不喂；中/高桶喂新值。
        old_core = dossier["core"]
        probe_core = f"CORE_PROBE_494_{faction}"
        low_before = faction_context_with_db(char_low, db)
        dossier["core"] = probe_core
        try:
            assert faction_context_with_db(char_low, db) == low_before
            assert probe_core in faction_context_with_db(char_mid, db)
            assert probe_core in faction_context_with_db(char_high, db)
        finally:
            dossier["core"] = old_core


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
