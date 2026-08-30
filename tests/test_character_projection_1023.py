"""#1023 player-facing LLM inputs share the qualitative character projection."""

from ming_sim.agents import build_simulator_context
from ming_sim.context import character_context
from ming_sim.qualitative import qualitative_character_axis
from ming_sim.simulation import build_simulator_payload
from tests.conftest import (
    CHARACTER_AXIS_SENTINEL,
    active_ming_character,
    plant_character_axis_sentinels,
)


def test_simulator_context_projects_character_axes_but_keeps_world_numbers(game):
    db, state, content = game
    character_name = active_ming_character(db, content)
    character = content.characters[character_name]
    army = db.conn.execute("SELECT name, manpower FROM armies ORDER BY id LIMIT 1").fetchone()
    plant_character_axis_sentinels(db, content, character.name)

    payload = build_simulator_payload(state, db, "", "")
    rendered = build_simulator_context(payload)
    columns = payload["court_roster"]["cols"]
    row = next(
        dict(zip(columns, values))
        for values in payload["court_roster"]["rows"]
        if values[columns.index("name")] == character.name
    )

    assert character.name in rendered
    assert row["忠诚"] == "离心已显"
    assert row["能力"] == "才具有限"
    assert row["清廉"] == "操守平常"
    assert row["胆略"] == "敢任其事"
    assert row["党派认同"] == "党色极深"
    expected_intrigue = qualitative_character_axis(
        "intrigue", CHARACTER_AXIS_SENTINEL["intrigue"]
    )
    assert row["阴谋"] == expected_intrigue
    character_rendered = character_context(character)
    assert "忠诚离心已显" in character_rendered
    assert "能力才具有限" in character_rendered
    assert "清廉操守平常" in character_rendered
    assert "胆略敢任其事" in character_rendered
    assert not {"loyalty", "ability", "integrity", "courage", "identity", "intrigue"} & set(
        columns
    )
    assert not any(
        str(value) in "\t".join(str(item) for item in row.values())
        for value in CHARACTER_AXIS_SENTINEL.values()
    )
    assert f'"year": {state.year}' in rendered
    assert f'"period": {state.period}' in rendered
    assert str(army["manpower"]) in rendered
    assert payload["treasury_brief"] in rendered


def test_character_projection_allows_memorial_wealth_approximation_without_an_exact_wealth_field(game):
    db, state, content = game
    character = next(iter(content.characters.values()))
    memorial = "臣闻此人家赀约数十万两，练兵有方、操守可虑。"

    rendered = character_context(character)
    payload = build_simulator_payload(state, db, "", memorial)
    simulator_input = build_simulator_context(payload)
    character_columns = {
        row["name"] for row in db.conn.execute("PRAGMA table_info(characters)").fetchall()
    }

    assert "家赀约数十万两" in simulator_input
    assert "wealth" not in character_columns
    assert "wealth" not in payload["court_roster"]["cols"]
    assert "家产原值" not in payload["court_roster"]["cols"]
    assert "wealth" not in rendered
