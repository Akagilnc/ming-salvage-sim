"""#1023 structured qualitative character projection contracts."""

from ming_sim.simulation import build_simulator_payload
from tests.conftest import active_ming_character


def test_simulator_payload_projects_character_axes_without_raw_columns(game):
    db, state, content = game
    character_name = active_ming_character(db, content)
    character = content.characters[character_name]

    payload = build_simulator_payload(state, db, "", "")
    columns = payload["court_roster"]["cols"]
    row = next(
        dict(zip(columns, values))
        for values in payload["court_roster"]["rows"]
        if values[columns.index("name")] == character.name
    )

    assert row["忠诚"]
    assert row["能力"]
    assert row["清廉"]
    assert row["胆略"]
    assert row["党派认同"]
    assert row["阴谋"]
    assert not {"loyalty", "ability", "integrity", "courage", "identity", "intrigue"} & set(
        columns
    )
    character_columns = {
        info["name"] for info in db.conn.execute("PRAGMA table_info(characters)").fetchall()
    }
    assert "wealth" not in character_columns
    assert "wealth" not in columns
    assert "家产原值" not in columns
