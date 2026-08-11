from ming_sim.models import CourtContext
from ming_sim.tools import (
    build_board_query_tools,
    build_extractor_tools,
    build_simulator_tools,
)


LEGACY_PERSON_KEYS = (
    "appointments",
    "character_status_changes",
    "character_power_changes",
    "office_changes",
)


def test_production_tool_guidance_only_names_canonical_person_writer(game):
    db, state, _content = game
    context = CourtContext(state=state, db=db, previous_summary="")

    for builder in (build_board_query_tools, build_simulator_tools, build_extractor_tools):
        guidance = "\n".join((tool.__doc__ or "") for tool in builder(context))
        assert "人物变更" in guidance
        for legacy_key in LEGACY_PERSON_KEYS:
            assert legacy_key not in guidance, (builder.__name__, legacy_key)
