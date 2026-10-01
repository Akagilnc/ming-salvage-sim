"""#494 / ADR0033：特征化覆盖与认同度分桶，不锁档料标题。"""

from dataclasses import replace

from ming_sim.context import (
    _MINISTER_DOSSIERS,
    character_context_with_db,
    faction_context_with_db,
    minister_dossier,
)


SEVEN_FACTIONS = ("阉党", "皇党", "东林", "军队", "宗室", "中立", "西学")


def _court_ministers(content):
    return [
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
        and c.faction in SEVEN_FACTIONS
        and c.status == "active"
    ]


def test_every_active_seven_faction_minister_has_featured_dossier(game):
    db, _state, content = game
    ministers = _court_ministers(content)
    assert ministers
    for character in ministers:
        dossier = minister_dossier(character)
        assert dossier
        assert dossier in character_context_with_db(character, db)


def test_seven_faction_dossiers_are_objective_and_identity_scoped(game):
    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")
    for faction in SEVEN_FACTIONS:
        character = replace(base, faction=faction)
        low, middle, high = [
            faction_context_with_db(replace(character, identity=identity), db)
            for identity in (20, 60, 90)
        ]
        assert len({low, middle, high}) == 3
        agenda = db.conn.execute(
            "SELECT agenda FROM factions WHERE name=?", (faction,)
        ).fetchone()["agenda"]
        assert agenda not in low
        assert agenda in middle and agenda in high


def test_north_star_ministers_have_distinct_featured_voices(game):
    db, _state, content = game
    voices = []
    for name in ("毕自严", "杨嗣昌", "王绍徽"):
        character = content.characters[name]
        # 原始特征料作为输入；不按输出的标题、分号或中文字段词拆声部。
        source = _MINISTER_DOSSIERS[name]
        voice = tuple(source[field] for field in ("motivation", "burden", "episode"))
        full = character_context_with_db(character, db)
        assert all(fragment in full for fragment in voice)
        voices.append(voice)
    assert len(set(voices)) == 3
