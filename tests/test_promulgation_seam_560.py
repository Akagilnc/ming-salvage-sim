import pytest

from ming_sim.decree import (
    stub_promulgation_verdicts,
    validate_promulgation_verdicts,
)
from ming_sim.exceptions import LLMContractError


def test_default_promulgation_stub_passes_every_dossier_without_collaborators(game):
    _db, state, _content = game
    dossiers = [{"id": 7}, {"id": 11}]

    assert stub_promulgation_verdicts(dossiers, state) == [
        {"dossier_id": 7, "decision": "promulgated"},
        {"dossier_id": 11, "decision": "promulgated"},
    ]


def test_injected_promulgation_batch_cannot_silently_omit_a_dossier(game):
    db, state, _content = game
    dossiers = [{"id": 7}, {"id": 11}]

    with pytest.raises(LLMContractError, match="逐案覆盖"):
        validate_promulgation_verdicts(
            [{"dossier_id": 7, "decision": "promulgated"}], dossiers, db,
        )
