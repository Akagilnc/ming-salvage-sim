import json

import pytest

import ming_sim.content as content_module
from ming_sim.assets import load_json_asset
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
    content.characters["魏忠贤"].identity = 0
    content.characters["魏忠贤"].seed_guilt = ""
    _sync_offices_from_db_impl(content, db)
    after = db.conn.execute(
        "SELECT identity, seed_guilt FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    assert dict(after) == dict(before)
    guilt = json.loads(after["seed_guilt"])
    assert guilt["severity"] == "重"
    assert content.characters["魏忠贤"].identity == before["identity"]
    assert json.loads(content.characters["魏忠贤"].seed_guilt) == guilt


def test_all_74_seed_roster_entries_are_persisted(game):
    db, state, content = game
    roster = load_json_asset("characters.json")["characters"]
    seeded = [raw for raw in roster if "identity" in raw]
    assert len(seeded) == 74
    for raw in seeded:
        character = content.characters[raw["name"]]
        row = db.conn.execute(
            "SELECT identity, seed_guilt FROM characters WHERE name=?", (character.name,)
        ).fetchone()
        assert row["identity"] == raw["identity"] == character.identity
        if character.name in {"高起潜", "吴昌时"}:
            assert row["seed_guilt"] == ""
        else:
            guilt = json.loads(row["seed_guilt"])
            assert set(guilt) == {"crime", "severity"}
            assert guilt["severity"] in {"无", "轻", "中", "重"}


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


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("identity", 101, "identity"),
        ("seed_guilt", {"crime": "", "severity": "轻"}, "crime"),
        ("seed_guilt", {"crime": "无", "severity": "未知"}, "severity"),
    ],
)
def test_seed_schema_rejects_invalid_values(monkeypatch, field, value, match):
    data = load_json_asset("characters.json")
    data["characters"][0][field] = value
    monkeypatch.setattr(content_module, "load_json_asset", lambda _: data)
    with pytest.raises(SystemExit, match=match):
        load_character_content()
