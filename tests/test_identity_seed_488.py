import json

from ming_sim.content import load_character_content
from ming_sim.session import _sync_offices_from_db_impl


def test_identity_and_seed_guilt_are_loaded_from_roster_and_seeded(game):
    db, state, content = game
    row = db.conn.execute(
        "SELECT faction, identity, seed_guilt FROM characters WHERE name=?",
        ("王承恩",),
    ).fetchone()
    assert row["faction"] == "皇党"
    assert row["identity"] == 95
    assert row["seed_guilt"] == ""

    温 = db.conn.execute(
        "SELECT faction, identity, seed_guilt FROM characters WHERE name=?", ("温体仁",)
    ).fetchone()
    assert 温["faction"] == "皇党"
    assert 温["identity"] == 18
    assert 温["seed_guilt"] == ""


def test_identity_and_seed_guilt_survive_restore(game):
    db, state, content = game
    before = db.conn.execute(
        "SELECT identity, seed_guilt FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    _sync_offices_from_db_impl(content, db)
    after = db.conn.execute(
        "SELECT identity, seed_guilt FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    assert dict(after) == dict(before)
    guilt = json.loads(after["seed_guilt"])
    assert guilt["severity"] == "重"


def test_identity_and_seed_guilt_never_enter_minister_context(game):
    db, state, content = game
    from ming_sim.context import character_context

    rendered = character_context(content.characters["王承恩"])
    assert "identity" not in rendered
    assert "seed_guilt" not in rendered
    assert "95" not in rendered


def test_roster_has_no_cross_faction_aliases():
    _, characters = load_character_content()
    by_alias = {}
    for character in characters.values():
        for alias in character.aliases:
            by_alias.setdefault(alias, set()).add(character.faction)
    assert all(len(factions) == 1 for factions in by_alias.values())
