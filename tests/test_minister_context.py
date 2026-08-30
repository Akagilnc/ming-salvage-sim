"""Structured minister tool and knowledge-boundary contracts."""

import json
from unittest.mock import MagicMock, patch

import pytest
from agno.tools.function import Function

from ming_sim.knowledge import knowledge_row_visible_to
from ming_sim.models import Character, CourtContext, LLMConfig
from ming_sim.registry import create_minister_agent
from ming_sim.tools import build_minister_tools
from tests.dossier_test_helpers import create_test_secret_order


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def _active_ministers(content, db, *, n=1):
    return [
        character
        for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ][:n]


def _capture_agent(game, character):
    db, _state, _content = game
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    config = LLMConfig(
        api_key="", base_url="", model="test", channel="cli", cli_runner="codex"
    )
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), patch(
        "ming_sim.registry.create_chat_model", return_value=MagicMock()
    ):
        create_minister_agent(character, config, _ctx(game), db)
    return captured


def test_summon_tool_exposes_and_enforces_canonical_travel_tones(game):
    db, _state, content = game
    minister = _active_ministers(content, db)[0]
    summon = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}[
        "summon_minister"
    ]

    schema = Function.from_callable(summon).to_dict()
    assert schema["parameters"]["properties"]["行程语气"]["enum"] == [
        "常行",
        "加急",
        "星夜兼程",
    ]
    assert summon(minister.name, 行程语气="加急") == f"__summon__{minister.name}"
    with pytest.raises(ValueError):
        summon(minister.name, 行程语气="飞驰")


def test_secret_order_source_visibility_respects_exclusions(game):
    db, state, content = game
    included, excluded = _active_ministers(content, db, n=2)
    order = create_test_secret_order(
        db,
        state,
        included.name,
        "暗查军饷",
        "查验边镇欠饷",
        [],
        excluded_names=[excluded.name],
    )
    source_id = f"secret_order:{order}"
    db.record_public_knowledge_event(
        state, "密令确认", "军饷已获确认", source_id=source_id
    )

    included_sources = {
        row["source_id"]
        for row in db.get_character_knowledge(state, included.name)["public_events"]
    }
    excluded_sources = {
        row["source_id"]
        for row in db.get_character_knowledge(state, excluded.name)["public_events"]
    }
    assert source_id in included_sources
    assert source_id not in excluded_sources


def test_secret_order_blacklist_overrides_assignee_brief_and_reference_candidate(game):
    db, state, _content = game
    excluded = "毕自严"
    hidden_order = create_test_secret_order(
        db,
        state,
        excluded,
        "黑名单密查军饷",
        "不可向承办人披露",
        [],
        excluded_names=[excluded],
    )
    visible_order = create_test_secret_order(
        db, state, excluded, "承办人可知军械", "正常承办密令", []
    )
    hidden_dossier = db.get_dossier_for_secret_order(hidden_order)
    visible_dossier = db.get_dossier_for_secret_order(visible_order)

    events = db._character_knowledge_events(excluded, include_exclusions=True)
    visible_sources = {
        event["source_id"]
        for event in events
        if knowledge_row_visible_to(db, event, excluded)
    }
    candidate_ids = {
        row["id"] for row in db.list_referenceable_dossiers(excluded, state.turn)
    }

    assert f"secret_order_brief:{hidden_order}" not in visible_sources
    assert hidden_dossier["id"] not in candidate_ids
    assert f"secret_order_brief:{visible_order}" in visible_sources
    assert visible_dossier["id"] in candidate_ids


def test_secret_source_boundary_preserves_chapter_and_issue_projections(game):
    db, state, content = game
    included, excluded = _active_ministers(content, db, n=2)
    order = create_test_secret_order(
        db,
        state,
        included.name,
        "密查军饷",
        "核验欠饷",
        [],
        excluded_names=[excluded.name],
    )
    secret_source = f"secret_order:{order}"
    db.record_public_knowledge_event(
        state, "密令确认", "核验", source_id=secret_source
    )
    db.save_chapter_memory(state, "本月朝局", "本月朝局", public_body="本月朝局")

    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="仅知者可见事项",
        origin_kind="test",
        origin_ref="test:scoped-issue",
        bar_value=20,
        inertia=0,
        stage_text="核验",
        participants=[{"character_id": included.name}],
    )

    included_view = db.get_character_knowledge(state, included.name)
    excluded_view = db.get_character_knowledge(state, excluded.name)
    included_sources = {row["source_id"] for row in included_view["public_events"]}
    excluded_sources = {row["source_id"] for row in excluded_view["public_events"]}
    chapter_source = f"projection:chapter:{state.turn}"

    assert secret_source in included_sources
    assert secret_source not in excluded_sources
    assert chapter_source in included_sources
    assert chapter_source in excluded_sources
    assert {row["id"] for row in included_view["issues"]} == {issue_id}
    assert {row["source_id"] for row in included_view["issues"]} == {f"issue:{issue_id}"}
    assert issue_id not in {row["id"] for row in excluded_view["issues"]}


def test_secret_order_tool_preserves_long_title_without_formal_cap(game):
    db, _state, content = game
    minister = _active_ministers(content, db)[0]
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    title = "核发辽饷转运与沿途侵蚀及军粮实数并追索责任官员"

    result = tools["secret_order"](
        action="issue",
        title=title,
        content="核发军饷并回奏。",
        kind="核发辽饷",
        axes_json='["实务事功"]',
        delivery_unit="万两",
        delivery_target_units=1,
        effect_sign=-1,
        purpose="辽饷",
        category="军饷",
        account="国库",
    )

    assert result.startswith("__secret_order__")
    assert json.loads(result.removeprefix("__secret_order__"))["title"] == title


def test_scale_gate_uses_authorized_roster_slice(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "工部")
    roster_size = len(db.current_court_roster_rows(state))
    for index in range(101 - roster_size):
        db.add_character(
            state,
            Character(
                name=f"scale-roster-{index:03d}",
                office="听用",
                office_type="待铨",
                faction="中立",
                aliases=[],
                personal_skills=[],
                loyalty=50,
                ability=50,
                integrity=50,
                courage=50,
                style="scale-seed",
                power_id="ming",
                status="active",
            ),
            source="test-scale-roster",
            commit=False,
        )
    db.conn.commit()

    captured = _capture_agent(game, minister)
    assert "query_court_roster" not in {tool.__name__ for tool in captured["tools"]}
