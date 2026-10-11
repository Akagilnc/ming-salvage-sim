from ming_sim.settlement.dossier import apply_dossier_verdicts
import json
import pytest
import ming_sim.decree as decree_mod
from ming_sim.exceptions import LLMContractError
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import view
from ming_sim.strict_types import IMPERIAL_AUTHORITY_BANDS
from tests.dossier_test_helpers import rejected_verdict
from ming_sim.qualitative import qualitative_character_axis



def _dossier(db, state, text="清丈天下田亩", **payload):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text=text,
        target_kind="issue", target_id=f"policy-{state.turn}", payload=payload,
    )





def test_promulgation_verdict_list_shape_has_one_canonical_authority(game):
    db, _state, _content = game
    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts({"verdicts": []}, [], db)

@pytest.mark.parametrize("decision, field, value, snapshot, midzhi", [
    ('promulgated', 'foo', 'bar', False, False),
    ('rejected', 'foo', 'bar', False, False),
    ('rejected', 'imperial_authority_band', '极弱', True, False),
    ('rejected', 'appointment_tenure', '署理', True, False),
    ('rejected', 'authorization_ids', ['forged-auth'], True, False),
    ('rejected', 'endorsement_entry_ids', [1], True, False),
    ('rejected', None, None, False, True),
])
def test_promulgation_verdict_rejects_unknown_fields(game, decision, field, value, snapshot, midzhi):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.dossiers.list_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    verdict = (
        {"dossier_id": dossier_id, "decision": "promulgated"}
        if decision == "promulgated"
        else _rejected_verdict(dossier_id, context["imperial_authority_band"], midzhi=midzhi)
    )
    if field is not None:
        target = verdict["criteria_snapshot"] if snapshot else verdict
        target[field] = value
    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts([verdict], dossiers, db, prepared_context=context)



def test_rejected_verdict_still_requires_full_rejection_contract(game):
    """#1397 负向边界：打回契约不因顺颁容错而放松。

    只给缘由、不给完整打回契约（受影响方 + typed 判据快照）的判决必须被拒，
    且一条 verdict 都不落账——区分度是**拒收后颁布格与判决表仍为空**这条
    结构化事实，不靠报错措辞（#1889）。
    """
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.dossiers.list_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)

    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts(
            [{"dossier_id": dossier_id, "decision": "rejected", "reason": "仅有缘由"}],
            dossiers, db, prepared_context=context,
        )

    after = db.dossiers.get(dossier_id)
    assert after["promulgation_decision"] == "", after["promulgation_decision"]
    assert db.dossiers.decisions(dossier_id) == []







def _rejected_verdict(dossier_id, authority_band, *, midzhi=False):
    # Preserve suite-specific reason/intensity differences via builder knobs.
    return rejected_verdict(
        dossier_id, authority_band, midzhi=midzhi,
        reason="触犯钱粮命门，科臣封驳。", intensity="strong",
    )


def test_rejected_exact_keys_accept_only_empty_legal_reason_slot(game):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.dossiers.list_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    verdict = _rejected_verdict(dossier_id, context["imperial_authority_band"])
    verdict["legal_reason_code"] = ""

    assert decree_mod.validate_promulgation_verdicts(
        [verdict], dossiers, db, prepared_context=context,
    ) == [verdict]

    for invalid in ("statute-42", 0, False, [], {}):
        verdict["legal_reason_code"] = invalid
        with pytest.raises(LLMContractError):
            decree_mod.validate_promulgation_verdicts(
                [verdict], dossiers, db, prepared_context=context,
            )

def test_default_promulgation_judge_uses_one_batch_and_existing_validator(game, monkeypatch):
    """一批判官一次调用，再走既有校验。入口是 llm_promulgation_verdicts。"""
    db, state, content = game
    del content
    first = _dossier(db, state)
    second = db.create_decree_dossier(
        state, action_type="appointment", decree_text="擢任某官",
        target_kind="character", target_id="candidate",
    )
    calls = []

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())

    def canned(_agent, prompt, tag, **_k):
        calls.append((json.loads(prompt), tag))
        return json.dumps({"verdicts": [
            {"dossier_id": first, "decision": "promulgated"},
            {"dossier_id": second, "decision": "promulgated"},
        ]})

    monkeypatch.setattr(decree_mod, "run_agent_text", canned)
    dossiers = db.dossiers.list_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    raw = decree_mod.llm_promulgation_verdicts(
        dossiers, state, db=db, agno_db=None, llm_config=object(),
        prepared_context=context,
    )

    assert decree_mod.validate_promulgation_verdicts(
        raw, dossiers, db, prepared_context=context,
    ) == [
        {"dossier_id": first, "decision": "promulgated"},
        {"dossier_id": second, "decision": "promulgated"},
    ]
    assert len(calls) == 1
    assert calls[0][1] == "promulgation-judge"
    assert [row["id"] for row in calls[0][0]["dossiers"]] == [first, second]



def test_non_gatekeeper_character_cannot_be_named_as_gatekeeper(game):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.dossiers.list_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    gatekeepers = {row["name"] for row in context["gatekeepers"]}
    outsider = next(
        row["name"] for row in db.conn.execute("SELECT name FROM characters ORDER BY name")
        if row["name"] not in gatekeepers
    )
    verdict = _rejected_verdict(dossier_id, context["imperial_authority_band"])
    verdict["gatekeeper_id"] = outsider

    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts(
            [verdict], dossiers, db, prepared_context=context,
        )


@pytest.mark.parametrize(
    ("action_type", "mode"),
    [
        ("secret_authorization", "ordinary"),
        ("secret_authorization", "midzhi"),
        ("secret_investigation", "ordinary"),
        ("secret_investigation", "midzhi"),
        ("protection", "ordinary"),
        ("protection", "midzhi"),
    ],
)
def test_review_exempt_actions_auto_promulgate_without_judge_contract_abort(
    game, monkeypatch, action_type, mode,
):
    from types import SimpleNamespace

    from ming_sim import agents as forecast_agents
    from ming_sim.decree_forecast import (
        produce_forecast_product, snapshot_for_existing_dossier,
    )

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type=action_type, decree_text="密旨照准",
        target_kind="issue", target_id=f"exempt-{action_type}-{mode}",
        payload={"mode": mode},
    )
    monkeypatch.setattr(
        decree_mod, "create_promulgation_judge_agent",
        lambda *_a, **_k: pytest.fail("review-exempt 案卷不得送入 LLM"),
    )
    monkeypatch.setattr(forecast_agents, "create_decree_forecast_agent", lambda *a, **k: object())
    monkeypatch.setattr(forecast_agents, "run_agent_text", lambda *a, **k: "")
    session = SimpleNamespace(
        db=db, state=state, llm_config=object(), agno_db=None, content=content,
    )
    dossier = db.dossiers.get(dossier_id)
    product = produce_forecast_product(
        session, snapshot_for_existing_dossier(session, dossier),
    )

    assert product["verdict"] == {"dossier_id": dossier_id, "decision": "promulgated"}
    assert db.dossiers.get(dossier_id)["status"] == "proposed"
    assert db.dossiers.decisions(dossier_id) == []
