from ming_sim import cli_backend
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


def test_initiative_enrichment_guidance_only_names_canonical_person_writer(monkeypatch):
    prompts = []

    def capture_prompt(prompt, _config, *, tag):
        prompts.append((prompt, tag))
        return "{}", {}

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", capture_prompt)
    cli_backend.enrich_initiative_effects("整饬朝纲")

    assert prompts[0][1] == "issue_enrich"
    guidance = prompts[0][0]
    assert "人物变更" in guidance
    assert "处置" in guidance
    for legacy_key in LEGACY_PERSON_KEYS:
        assert legacy_key not in guidance


def test_production_tool_guidance_only_names_canonical_person_writer(game):
    db, state, _content = game
    context = CourtContext(state=state, db=db, previous_summary="")

    for builder in (build_board_query_tools, build_simulator_tools, build_extractor_tools):
        guidance = "\n".join((tool.__doc__ or "") for tool in builder(context))
        assert "人物变更" in guidance
        if builder is build_extractor_tools:
            assert "行止只补非空 transit_to 启程" in guidance
            assert "不得提交 location" in guidance
            assert "抵达只由引擎 force_transit_arrivals 处理" in guidance
        for legacy_key in LEGACY_PERSON_KEYS:
            assert legacy_key not in guidance, (builder.__name__, legacy_key)
