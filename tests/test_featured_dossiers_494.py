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
    """#494：identity 桶决定供料来源；最低桶不喂派系档/议程。

    契约落在确定性装配等值（源字段 + 固定低档文案），不扫自由文禁词。
    """
    from ming_sim.context import _faction_band, _identity_bucket
    from ming_sim.qualitative import identity_band

    db, _state, content = game
    base = next(c for c in content.characters.values() if c.faction == "东林")

    assert _identity_bucket(20) == "low"
    assert _identity_bucket(60) == "middle"
    assert _identity_bucket(90) == "high"

    def _expected(faction: str, identity: int) -> str:
        row = _faction_row(db, faction)
        dossier = _FACTION_DOSSIERS[faction]
        bucket = _identity_bucket(identity)
        if bucket == "low":
            body = (
                "与该派仅有名义关联，未提供该派内情；"
                "人物立场由自身经历与当下处境呈现。"
            )
        elif bucket == "middle":
            body = (
                f"这个党是什么样一伙人：{dossier['core']}"
                f"所求：{row['agenda']}；当前朝势："
                f"{_faction_band('leverage', row['leverage'])}。"
            )
        else:
            body = (
                f"这个党是什么样一伙人：{dossier['core']}"
                f"其内部：{dossier['internal']}"
                f"所求：{row['agenda']}；当前朝势："
                f"{_faction_band('leverage', row['leverage'])}，"
                f"对政局态度{_faction_band('satisfaction', row['satisfaction'])}。"
            )
        return (
            f"【派系档料】{faction}：{body}"
            f"【党派认同】此人对本派的认同为{identity_band(identity)}。"
        )

    for faction in SEVEN_FACTIONS:
        assert faction_context_with_db(
            replace(base, faction=faction, identity=65), db,
        ) == _expected(faction, 65)

    faction = base.faction
    low = faction_context_with_db(replace(base, identity=20), db)
    middle = faction_context_with_db(replace(base, identity=60), db)
    high = faction_context_with_db(replace(base, identity=90), db)
    # 源装配等值：低档固定文案（不喂 dossier/agenda）；中/高按桶拼 core/internal。
    assert low == _expected(faction, 20)
    assert middle == _expected(faction, 60)
    assert high == _expected(faction, 90)
    assert len({low, middle, high}) == 3


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
