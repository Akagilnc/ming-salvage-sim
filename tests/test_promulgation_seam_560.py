import pytest

from ming_sim.decree import (
    stub_promulgation_verdicts,
    validate_promulgation_verdicts,
)
from ming_sim.exceptions import LLMContractError


def test_default_promulgation_stub_passes_every_dossier_without_collaborators():
    state = object()
    dossiers = [{"id": 7}, {"id": 11}]

    assert stub_promulgation_verdicts(dossiers, state) == [
        {"dossier_id": 7, "decision": "promulgated"},
        {"dossier_id": 11, "decision": "promulgated"},
    ]


def test_injected_promulgation_batch_cannot_silently_omit_a_dossier(read_game):
    db, state, _content = read_game
    dossiers = [{"id": 7}, {"id": 11}]

    with pytest.raises(LLMContractError, match="逐案覆盖"):
        validate_promulgation_verdicts(
            [{"dossier_id": 7, "decision": "promulgated"}], dossiers, db,
        )


def _stage_policy_dossier(db, state):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id=f"river-{state.turn}",
    )


def test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row(game):
    db, state, _content = game
    dossier_id = _stage_policy_dossier(db, state)
    original = [{"dossier_id": dossier_id, "decision": "promulgated"}]
    db.save_pending_promulgation_verdicts(state.turn, original)

    with pytest.raises((TypeError, ValueError)):
        db.save_pending_promulgation_verdicts(state.turn, [
            original[0], {"dossier_id": "not-an-int", "decision": "rejected"},
        ])

    assert db.get_pending_promulgation_verdicts(state.turn) == original
