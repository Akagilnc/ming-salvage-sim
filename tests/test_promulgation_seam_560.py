import pytest

from ming_sim.decree import validate_promulgation_verdicts
from ming_sim.exceptions import LLMContractError


def test_injected_promulgation_batch_cannot_silently_omit_a_dossier(read_game):
    db, state, _content = read_game
    # 规范案卷行（get_decree_dossier 形）：payload 已解码，无 raw payload_json 回退。
    dossiers = [
        {"id": 7, "action_type": "policy", "payload": {}},
        {"id": 11, "action_type": "policy", "payload": {}},
    ]

    with pytest.raises(LLMContractError):
        validate_promulgation_verdicts(
            [{"dossier_id": 7, "decision": "promulgated"}], dossiers, db,
        )
