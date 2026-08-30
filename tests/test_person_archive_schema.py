"""ADR 0009 person archive schema contract."""

import json
import sqlite3

from ming_sim.content import load_character_content
from ming_sim.db import GameDB
from ming_sim.models import Character
from ming_sim.session import _sync_offices_from_db_impl


def _columns(db, table):
    return {row["name"] for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _column_info(db, table):
    return {row["name"]: dict(row) for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_characters_table_has_person_archive_fields(read_game):
    """ADR 0009 stores machine-readable reason and travel state on characters."""
    db, _, _ = read_game

    cols = _columns(db, "characters")

    assert "reason_code" in cols
    assert "transit_to" in cols
    assert {"intrigue", "defected_from"} <= cols
    assert {"transit_distance_remaining", "transit_speed_factor"} <= cols
    info = _column_info(db, "characters")
    assert info["intrigue"]["type"] == "INTEGER"
    assert info["intrigue"]["notnull"] == 1
    assert info["intrigue"]["dflt_value"] is None
    assert info["defected_from"]["type"] == "TEXT"
    assert info["defected_from"]["notnull"] == 0
    assert info["defected_from"]["dflt_value"] is None
    for name in ("transit_distance_remaining", "transit_speed_factor"):
        assert info[name]["type"] == "REAL"
        assert info[name]["notnull"] == 0
        assert info[name]["dflt_value"] is None
    for name in ("reason_code", "transit_to"):
        assert info[name]["type"] == "TEXT"
        assert info[name]["notnull"] == 1
        assert info[name]["dflt_value"] == "''"


def test_person_logs_table_records_person_archive_audit_chain(read_game):
    """ADR 0009 persists person archive process history separately from final state."""
    db, _, _ = read_game

    cols = _columns(db, "person_logs")

    assert {
        "id",
        "turn",
        "year",
        "period",
        "person_name",
        "action",
        "payload_summary",
        "derived_from",
        "normalized",
        "source",
        "created_at",
    } <= cols

    info = _column_info(db, "person_logs")
    for name in ("person_name", "action", "payload_summary", "derived_from", "normalized", "source"):
        assert info[name]["type"] == "TEXT"
        assert info[name]["notnull"] == 1
    for name in ("payload_summary", "derived_from", "normalized", "source"):
        assert info[name]["dflt_value"] == "''"

    indexes = {
        row["name"]
        for row in db.conn.execute("PRAGMA index_list(person_logs)").fetchall()
    }
    assert "idx_person_logs_turn" in indexes

    foreign_keys = {
        (row["from"], row["table"], row["to"])
        for row in db.conn.execute("PRAGMA foreign_key_list(person_logs)").fetchall()
    }
    assert ("person_name", "characters", "name") in foreign_keys


def test_person_logs_accepts_audit_rows_for_existing_characters(game):
    """The audit table is not only present; it can persist an ADR 0009 log row."""
    db, state, _ = game
    person = db.conn.execute("SELECT name FROM characters ORDER BY name LIMIT 1").fetchone()["name"]

    db.conn.execute(
        """
        INSERT INTO person_logs
        (turn, year, period, person_name, action, payload_summary, derived_from, normalized, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (state.turn, state.year, state.period, person, "行止", "启程赴辽", "S11", "{}", "system_simulation"),
    )

    row = db.conn.execute(
        "SELECT person_name, action, payload_summary, derived_from, normalized, source FROM person_logs"
    ).fetchone()
    assert dict(row) == {
        "person_name": person,
        "action": "行止",
        "payload_summary": "启程赴辽",
        "derived_from": "S11",
        "normalized": "{}",
        "source": "system_simulation",
    }


def test_add_character_persists_transit_to(game):
    """Runtime-created characters preserve ADR 0009 travel state."""
    db, state, _ = game
    character = Character(
        name="测试在途人物",
        office="听用",
        office_type="待铨",
        faction="中立",
        aliases=[],
        personal_skills=[],
        loyalty=50,
        ability=50,
        integrity=50,
        courage=50,
        intrigue=63,
        defected_from="阉党",
        style="测试人物",
        power_id="ming",
        location="beizhili",
        transit_to="liaodong",
    )

    db.add_character(state, character)

    row = db.conn.execute(
        "SELECT location, transit_to, intrigue, defected_from FROM characters WHERE name=?", (character.name,)
    ).fetchone()
    assert dict(row) == {
        "location": "beizhili",
        "transit_to": "liaodong",
        "intrigue": 63,
        "defected_from": "阉党",
    }


def test_reload_restores_complete_transit_ledger_from_db(game):
    db, _, content = game
    name = db.conn.execute("SELECT name FROM characters LIMIT 1").fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET transit_to='liaodong', transit_distance_remaining=1.25, "
        "transit_speed_factor=1.5, transit_start_turn=7 WHERE name=?",
        (name,),
    )

    _sync_offices_from_db_impl(content, db)

    character = content.characters[name]
    assert (
        character.transit_to,
        character.transit_distance_remaining,
        character.transit_speed_factor,
        character.transit_start_turn,
    ) == ("liaodong", 1.25, 1.5, 7)


def test_old_save_schema_is_upgraded_for_person_archive_fields(tmp_path, content):
    """Opening an old save adds ADR 0009 fields and audit table without reseeding."""
    path = tmp_path / "old-save.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE characters (
            name TEXT PRIMARY KEY,
            office TEXT NOT NULL,
            office_type TEXT NOT NULL,
            faction TEXT NOT NULL,
            personal_skills TEXT NOT NULL,
            loyalty INTEGER NOT NULL,
            ability INTEGER NOT NULL,
            integrity INTEGER NOT NULL,
            courage INTEGER NOT NULL,
            style TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            status_reason TEXT NOT NULL DEFAULT '',
            status_changed_turn INTEGER NOT NULL DEFAULT 0,
            power_id TEXT NOT NULL DEFAULT 'ming',
            location TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()

    db = GameDB(str(path), content)
    try:
        character_info = _column_info(db, "characters")
        assert "reason_code" in character_info
        assert "transit_to" in character_info
        assert "person_logs" in {
            row["name"]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        db.conn.close()


def test_north_star_named_figures_are_seeded_with_identity_metadata():
    """ADR 0009 can reject no named target used by north-star scenes/prompts."""
    _factions, characters = load_character_content()

    expected = {"郭允厚", "李之藻", "张缙彦", "李从心", "汤若望", "胡廷宴", "徐应秋"}
    assert expected <= characters.keys()
    for name in expected:
        assert isinstance(characters[name].identity, int)
        assert characters[name].seed_guilt
