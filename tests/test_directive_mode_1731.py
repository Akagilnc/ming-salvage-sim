"""#1731: directive mode is a typed LLM decision, never parsed from player prose."""

from ming_sim.cli_backend import resolve_directive_mode


def test_unclassified_player_prose_defaults_to_ordinary():
    assert resolve_directive_mode("中旨直发，绕过内阁", extracted="") == "ordinary"


def test_typed_llm_midzhi_decision_is_honored():
    assert resolve_directive_mode("卿即拟旨呈览", extracted="midzhi") == "midzhi"
