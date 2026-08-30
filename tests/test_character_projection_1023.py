"""#1023 structured qualitative character projection contracts."""

from ming_sim.simulation import build_simulator_payload
from tests.conftest import active_ming_character, plant_character_axis_sentinels


def test_simulator_payload_projects_character_axes_without_raw_columns(game):
    db, state, content = game
    character_name = active_ming_character(db, content)
    character = content.characters[character_name]
    axis_values = plant_character_axis_sentinels(db, content, character_name)

    payload = build_simulator_payload(state, db, "", "")
    columns = payload["court_roster"]["cols"]
    row = next(
        dict(zip(columns, values))
        for values in payload["court_roster"]["rows"]
        if values[columns.index("name")] == character.name
    )

    assert {
        key: row[key]
        for key in ("忠诚", "能力", "清廉", "胆略", "党派认同", "阴谋")
    } == {
        "忠诚": "离心已显",
        "能力": "才具有限",
        "清廉": "操守平常",
        "胆略": "敢任其事",
        "党派认同": "党色极深",
        "阴谋": "深谙机变",
    }
    assert not set(map(str, axis_values.values())) & set(row.values())
    assert not {"loyalty", "ability", "integrity", "courage", "identity", "intrigue"} & set(
        columns
    )
    character_columns = {
        info["name"] for info in db.conn.execute("PRAGMA table_info(characters)").fetchall()
    }
    assert "wealth" not in character_columns
    assert "wealth" not in columns
    assert "家产原值" not in columns
