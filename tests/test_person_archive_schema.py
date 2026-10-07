"""ADR 0009 person archive schema contract."""

from ming_sim.content import load_character_content
from ming_sim.models import Character
from ming_sim.decree import reload_state_from_db


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


def test_reload_restores_complete_transit_ledger_from_db(game):
    db, state, content = game
    name = db.conn.execute("SELECT name FROM characters LIMIT 1").fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET transit_to='liaodong', transit_distance_remaining=1.25, "
        "transit_speed_factor=1.5, transit_start_turn=7 WHERE name=?",
        (name,),
    )

    reload_state_from_db(db, state, content=content)

    character = content.characters[name]
    assert (
        character.transit_to,
        character.transit_distance_remaining,
        character.transit_speed_factor,
        character.transit_start_turn,
    ) == ("liaodong", 1.25, 1.5, 7)


def test_north_star_named_figures_are_seeded_with_identity_metadata():
    """ADR 0009 can reject no named target used by north-star scenes/prompts."""
    _factions, characters = load_character_content()

    expected = {"郭允厚", "李之藻", "张缙彦", "李从心", "汤若望", "胡廷宴", "徐应秋"}
    assert expected <= characters.keys()
    for name in expected:
        assert isinstance(characters[name].identity, int)
        assert characters[name].seed_guilt
