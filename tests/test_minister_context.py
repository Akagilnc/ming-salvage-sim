"""Structured minister tool and knowledge-boundary contracts."""

import json

import pytest
from agno.tools.function import Function

from ming_sim.knowledge import knowledge_row_visible_to
from ming_sim.models import CourtContext
from ming_sim.tools import build_minister_tools
from tests.dossier_test_helpers import create_test_secret_order


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def _active_minister(content, db):
    return next(
        character
        for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    )


def test_summon_tool_exposes_and_enforces_canonical_travel_tones(game):
    db, _state, content = game
    minister = _active_minister(content, db)
    summon = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}["summon_minister"]

    schema = Function.from_callable(summon).to_dict()
    assert schema["parameters"]["properties"]["行程语气"]["enum"] == ["常行", "加急", "星夜兼程"]
    assert summon(minister.name, 行程语气="加急") == f"__summon__{minister.name}"
    with pytest.raises(ValueError, match="行程语气"):
        summon(minister.name, 行程语气="飞驰")


def test_secret_order_blacklist_overrides_assignee_brief_and_reference_candidate(game):
    db, state, _content = game
    excluded = "毕自严"
    hidden_order = create_test_secret_order(
        db, state, excluded, "黑名单密查军饷", "不可向承办人披露", [],
        excluded_names=[excluded],
    )
    visible_order = create_test_secret_order(
        db, state, excluded, "承办人可知军械", "正常承办密令", [],
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


def test_secret_order_tool_preserves_long_title_without_formal_cap(game):
    db, _state, content = game
    minister = _active_minister(content, db)
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    title = "核发辽饷转运与沿途侵蚀及军粮实数并追索责任官员"

    result = tools["secret_order"](
        action="issue", title=title, content="核发军饷并回奏。",
        kind="核发辽饷", axes_json='["实务事功"]', delivery_unit="万两",
        delivery_target_units=1, effect_sign=-1, purpose="辽饷", category="军饷", account="国库",
    )

    assert result.startswith("__secret_order__")
    assert json.loads(result.removeprefix("__secret_order__"))["title"] == title
