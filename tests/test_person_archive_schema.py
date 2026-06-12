"""ADR 0009 person archive schema contract."""

import sqlite3
from pathlib import Path

from ming_sim.db import GameDB
from ming_sim.models import Character


def _columns(db, table):
    return {row["name"] for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _column_info(db, table):
    return {row["name"]: dict(row) for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_characters_table_has_person_archive_fields(game):
    """ADR 0009 stores machine-readable reason and travel state on characters."""
    db, _, _ = game

    cols = _columns(db, "characters")

    assert "reason_code" in cols
    assert "transit_to" in cols
    info = _column_info(db, "characters")
    for name in ("reason_code", "transit_to"):
        assert info[name]["type"] == "TEXT"
        assert info[name]["notnull"] == 1
        assert info[name]["dflt_value"] == "''"


def test_person_logs_table_records_person_archive_audit_chain(game):
    """ADR 0009 persists person archive process history separately from final state."""
    db, _, _ = game

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
        office_type="候补",
        faction="中立",
        aliases=[],
        personal_skills=[],
        loyalty=50,
        ability=50,
        integrity=50,
        courage=50,
        style="测试人物",
        power_id="ming",
        location="beizhili",
        transit_to="liaodong",
    )

    db.add_character(state, character)

    row = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (character.name,)
    ).fetchone()
    assert dict(row) == {"location": "beizhili", "transit_to": "liaodong"}


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


def test_personnel_extractor_prompt_teaches_person_change_contract():
    """Real personnel extraction prompts must ask for the ADR 0009 write surface."""
    prompt_dir = Path(__file__).resolve().parents[1] / "content" / "prompts"
    shared = (prompt_dir / "score_extractor_shared.md").read_text(encoding="utf-8")
    personnel = (prompt_dir / "score_extractor_personnel_secret.md").read_text(
        encoding="utf-8"
    )

    for text in (shared, personnel):
        assert "人物变更" in text
        assert "行止" in text
        assert "transit_to" in text
    assert "location" in personnel
    assert "任命" in personnel
    assert "罢黜" in personnel
    assert "调任" in personnel
    assert "处置" in personnel
    assert "易主" in personnel
    assert "册封" in personnel
    assert "新登场的非明朝人物" in personnel
    assert "若不在人物名册中，不写 `人物变更`" in personnel
    assert "走 `任命`，不走这里" not in personnel
