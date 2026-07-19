"""#1023 player-facing LLM inputs share the qualitative character projection."""

from ming_sim.agents import build_simulator_context
from ming_sim.context import character_context
from ming_sim.qualitative import qualitative_character_axes
from ming_sim.simulation import build_simulator_payload


def test_simulator_context_projects_character_axes_but_keeps_world_numbers(game):
    db, state, content = game
    character = next(
        item for item in content.characters.values()
        if item.status == "active" and item.power_id == "ming"
        and item.office_type not in ("后宫", "宗藩")
    )
    army = db.conn.execute("SELECT name, manpower FROM armies ORDER BY id LIMIT 1").fetchone()

    payload = build_simulator_payload(state, db, "", "")
    rendered = build_simulator_context(payload)

    assert character.name in rendered
    assert "忠诚" in rendered and "能力" in rendered and "清廉" in rendered and "胆略" in rendered
    projection = qualitative_character_axes(character)
    assert all(word in rendered for word in projection.values())
    assert not {"loyalty", "ability", "integrity", "courage", "identity"} & set(
        payload["court_roster"]["cols"]
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
    simulator_input = build_simulator_context(
        build_simulator_payload(state, db, "", memorial)
    )

    assert "家赀约数十万两" in simulator_input
    assert "wealth" not in rendered
    assert "家产原值" not in rendered
