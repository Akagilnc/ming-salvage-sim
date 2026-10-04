import json

import pytest

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
from ming_sim.exceptions import LLMContractError
from ming_sim.models import LLMConfig
from ming_sim.strict_types import IMPERIAL_AUTHORITY_BANDS
from tests.dossier_test_helpers import rejected_verdict


def _dossier(db, state, text="清丈天下田亩", **payload):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text=text,
        target_kind="issue", target_id=f"policy-{state.turn}", payload=payload,
    )


def test_promulgation_context_is_deterministic_and_excludes_satisfaction(game):
    db, state, _content = game
    # break_rank is persisted dossier evidence read from payload (#562).
    # endorsement_entry_ids are positive ints from DB-backed spoken endorsements (#612).
    dossier_id = _dossier(
        db, state, mode="midzhi",
        break_rank={"office_rank": "越三级"},
    )
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    chat_a = db.create_chat_turn(state, minister, "promulgation-561-a", 0)
    chat_b = db.create_chat_turn(state, minister, "promulgation-561-b", 0)
    first_id = db.add_dossier_endorsement(
        dossier_id, form="会签", endorser_id=minister, source_chat_turn_id=chat_a,
    )
    second_id = db.add_dossier_endorsement(
        dossier_id, form="当面站台", endorser_id=minister, source_chat_turn_id=chat_b,
    )
    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )

    assert context == decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True)
    assert "satisfaction" not in encoded
    assert "满意" not in encoded
    assert context["dossiers"][0]["mode"] == "midzhi"
    assert context["dossiers"][0]["break_rank"] == {"office_rank": "越三级"}
    assert set(context["factions"][0]) == {"name", "leverage", "agenda"}
    assert context["imperial_authority_band"] in IMPERIAL_AUTHORITY_BANDS
    assert context["classes"]
    assert all(isinstance(name, str) for name in context["classes"])
    assert context["gatekeepers"]
    assert all(set(row) == {
        "name", "office", "office_type", "faction", "courage", "integrity",
    } for row in context["gatekeepers"])
    assert all(
        isinstance(row["courage"], str) and isinstance(row["integrity"], str)
        for row in context["gatekeepers"]
    )
    assert context["dossiers"][0]["criteria_snapshot_source"] == {
        "imperial_authority_band": context["imperial_authority_band"],
        "appointment_tenure": "", "authorization_ids": [],
        "endorsement_entry_ids": sorted({first_id, second_id}),
    }
    assert all(
        isinstance(item, int) and not isinstance(item, bool) and item > 0
        for item in context["dossiers"][0]["criteria_snapshot_source"][
            "endorsement_entry_ids"
        ]
    )


def test_promulgation_context_projects_faction_leverage_as_qualitative_band(game):
    """#614: player-visible judge reasons inherit input-side leverage bands only."""
    db, state, _content = game
    _dossier(db, state, "清丈天下田亩")
    db.conn.execute(
        "UPDATE factions SET leverage=5, agenda='反对清丈' WHERE name='东林'"
    )
    db.conn.execute(
        "UPDATE factions SET leverage=95, agenda='附议清丈' WHERE name='阉党'"
    )
    db.conn.commit()

    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    by_name = {row["name"]: row for row in context["factions"]}

    assert by_name["东林"] == {
        "name": "东林", "leverage": "极弱", "agenda": "反对清丈",
    }
    assert by_name["阉党"] == {
        "name": "阉党", "leverage": "强盛", "agenda": "附议清丈",
    }
    assert all(
        isinstance(row["leverage"], str)
        and not isinstance(row["leverage"], bool)
        and row["leverage"] in IMPERIAL_AUTHORITY_BANDS
        for row in context["factions"]
    )
    # Resistance remains present; only the projection is qualitative.
    assert all(set(row) == {"name", "leverage", "agenda"} for row in context["factions"])
    assert any(row["agenda"] for row in context["factions"])


def test_promulgation_context_maps_faction_leverage_to_qualitative_band(game):
    """#614 C1: factions[].leverage 以领域外部可见定性带呈现（非内部公式 oracle）。"""
    db, state, _content = game
    _dossier(db, state, "清丈天下田亩")
    db.conn.execute("UPDATE factions SET leverage=42 WHERE name='东林'")
    db.conn.commit()

    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    by_name = {row["name"]: row for row in context["factions"]}
    assert by_name["东林"]["leverage"] == "中等"
    assert by_name["东林"]["leverage"] in IMPERIAL_AUTHORITY_BANDS


def test_promulgation_history_only_projects_forced_and_midzhi_markers(game):
    db, state, _content = game
    ordinary = _dossier(db, state)
    midzhi_pass = _dossier(db, state, text="中旨补饷", mode="midzhi")
    midzhi_reject = _dossier(db, state, text="中旨清丈", mode="midzhi")
    for dossier_id, decision, action in (
        (ordinary, "rejected", ""),
        (ordinary, "rejected", "force_promulgated"),
        (midzhi_pass, "promulgated", ""),
        (midzhi_reject, "rejected", ""),
        (midzhi_reject, "rejected", "hold"),
        (midzhi_reject, "rejected", "withdrawn"),
        (midzhi_reject, "rejected", "force_promulgated"),
    ):
        db.conn.execute(
            "INSERT INTO decree_dossier_decisions "
            "(dossier_id,turn,decision,blocked_layer,rescript_action,reason) "
            "VALUES (?,?,?,?,?,?)",
            (dossier_id, state.turn, decision, "", action, "fixture"),
        )
    history = decree_mod.build_promulgation_judge_context(db, state, [])["promulgation_history"]
    assert history == [
        {"dossier_id": ordinary, "turn": state.turn, "mode": "ordinary",
         "marker": "批红强颁", "outcome": "promulgated"},
        {"dossier_id": midzhi_pass, "turn": state.turn, "mode": "midzhi",
         "marker": "中旨", "outcome": "promulgated"},
        {"dossier_id": midzhi_reject, "turn": state.turn, "mode": "midzhi",
         "marker": "中旨", "outcome": "rejected"},
        {"dossier_id": midzhi_reject, "turn": state.turn, "mode": "midzhi",
         "marker": "批红强颁", "outcome": "promulgated"},
    ]




def test_promulgation_verdict_list_shape_has_one_canonical_authority(game):
    db, _state, _content = game
    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts({"verdicts": []}, [], db)


@pytest.mark.parametrize("decision", ["promulgated", "rejected"])
def test_promulgation_verdict_rejects_unknown_fields(game, decision):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    verdict = (
        {"dossier_id": dossier_id, "decision": "promulgated"}
        if decision == "promulgated"
        else _rejected_verdict(dossier_id, context["imperial_authority_band"])
    )
    verdict["foo"] = "bar"

    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts(
            [verdict], dossiers, db, prepared_context=context,
        )


def test_promulgated_verdict_strips_rejection_only_noise(game):
    """#1397：顺颁夹带打回专属字段 → 剥离后过闸，不卡 settling。

    r6 三局 rejection_reports 实证：LLM 在 decision=promulgated 上塞
    reason/gatekeeper_id/primary_opponents/criteria_snapshot/affected_parties。
    """
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    noisy = {
        "dossier_id": dossier_id,
        "decision": "promulgated",
        "gatekeeper_id": "许誉卿",
        "primary_opponents": [{"kind": "faction", "key": "阉党"}],
        "reason": "有御笔手敕背书；该案未见越制破格条款。",
        "criteria_snapshot": {
            "imperial_authority_band": context["imperial_authority_band"],
            "appointment_tenure": "",
            "authorization_ids": [],
            "endorsement_entry_ids": [],
        },
        "affected_parties": [
            {"kind": "faction", "key": "阉党", "direction": "negative", "intensity": "strong"},
        ],
        "blocked_layer": "six_offices",
        "legal_reason_code": "",
        "midzhi_unpromulgatable": False,
    }
    original_keys = set(noisy)

    cleaned = decree_mod.validate_promulgation_verdicts(
        [noisy], dossiers, db, prepared_context=context,
    )

    assert cleaned == [{"dossier_id": dossier_id, "decision": "promulgated"}]
    # 调用方输入不被原地改写（error-pack / rejection 审计仍见原文）。
    assert set(noisy) == original_keys


def test_promulgated_midzhi_strips_affected_parties_with_rejection_noise(game):
    """#657 §C.8：中旨顺颁剥离打回噪声与猜派 affected_parties。"""
    db, state, _content = game
    dossier_id = _dossier(db, state, mode="midzhi")
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    parties = [
        {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "weak"},
    ]
    noisy = {
        "dossier_id": dossier_id,
        "decision": "promulgated",
        "affected_parties": parties,
        "reason": "中旨行政旨照过",
        "gatekeeper_id": "黄立极",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "blocked_layer": "six_offices",
        "criteria_snapshot": {
            "imperial_authority_band": context["imperial_authority_band"],
            "appointment_tenure": "",
            "authorization_ids": [],
            "endorsement_entry_ids": [],
        },
    }

    cleaned = decree_mod.validate_promulgation_verdicts(
        [noisy], dossiers, db, prepared_context=context,
    )

    assert cleaned == [{
        "dossier_id": dossier_id,
        "decision": "promulgated",
    }]
    assert "affected_parties" not in cleaned[0]


def test_promulgated_true_path_clean_verdict_passes(game):
    """#1397 钉测：干净顺颁真路径（仅 dossier_id+decision）过闸。"""
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)

    assert decree_mod.validate_promulgation_verdicts(
        [{"dossier_id": dossier_id, "decision": "promulgated"}],
        dossiers, db, prepared_context=context,
    ) == [{"dossier_id": dossier_id, "decision": "promulgated"}]


def test_rejected_verdict_still_requires_full_rejection_contract(game):
    """#1397 负向边界：打回契约不因顺颁容错而放松。"""
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)

    with pytest.raises(
        decree_mod.LLMContractError,
    ):
        decree_mod.validate_promulgation_verdicts(
            [{"dossier_id": dossier_id, "decision": "rejected", "reason": "仅有缘由"}],
            dossiers, db, prepared_context=context,
        )
























def test_promulgation_judge_omits_max_tokens(monkeypatch):
    """#1472：颁布判官参数面不发 max_tokens。"""
    seen = {}
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda _cfg, **kwargs: seen.update(kwargs) or object())
    monkeypatch.setattr(agents_mod, "Agent", lambda **kwargs: kwargs)
    cfg = LLMConfig(api_key="test", base_url="http://unused", model="test")

    agents_mod.create_promulgation_judge_agent(
        cfg, object(),
        session_id="promulgation-judge-turn-test",
        num_history_runs=4,
    )

    assert "max_tokens" not in seen


def _rejected_verdict(dossier_id, authority_band, *, midzhi=False):
    # Preserve suite-specific reason/intensity differences via builder knobs.
    return rejected_verdict(
        dossier_id, authority_band, midzhi=midzhi,
        reason="触犯钱粮命门，科臣封驳。", intensity="strong",
    )


@pytest.mark.parametrize(
    ("mode", "decision"),
    [("ordinary", "promulgated"), ("midzhi", "promulgated"),
     ("ordinary", "rejected"), ("midzhi", "rejected")],
)
def test_promulgation_verdict_accepts_exact_keys_for_each_mode(game, mode, decision):
    db, state, _content = game
    dossier_id = _dossier(db, state, mode=mode)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    if decision == "promulgated":
        verdict = {"dossier_id": dossier_id, "decision": decision}
        expected = [verdict]
    else:
        verdict = _rejected_verdict(
            dossier_id, context["imperial_authority_band"], midzhi=mode == "midzhi",
        )
        if mode == "midzhi":
            # #657 §C.8：中旨打回剥离猜派字段
            expected = [{
                k: v for k, v in verdict.items() if k != "affected_parties"
            }]
        else:
            expected = [verdict]

    assert decree_mod.validate_promulgation_verdicts(
        [verdict], dossiers, db, prepared_context=context,
    ) == expected


def test_rejected_exact_keys_accept_only_empty_legal_reason_slot(game):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
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
    dossiers = db.list_decree_dossiers(status="proposed")
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


@pytest.mark.parametrize(
    ("snapshot_key", "forged"),
    [
        ("imperial_authority_band", "极弱"),
        ("appointment_tenure", "署理"),
        ("authorization_ids", ["forged-auth"]),
        ("endorsement_entry_ids", [1]),
    ],
)
def test_rejected_snapshot_must_equal_the_prepared_judge_input(
    game, snapshot_key, forged,
):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    verdict = _rejected_verdict(dossier_id, context["imperial_authority_band"])
    verdict["criteria_snapshot"][snapshot_key] = forged

    with pytest.raises(decree_mod.LLMContractError):
        decree_mod.validate_promulgation_verdicts(
            [verdict], dossiers, db, prepared_context=context,
        )


def test_appointment_tenure_is_the_rejection_snapshot_value(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="appointment", decree_text="署理某官",
        target_kind="character", target_id="candidate", payload={"任别": "署理"},
    )

    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )

    assert context["dossiers"][0]["criteria_snapshot_source"]["appointment_tenure"] == "署理"
    assert context["dossiers"][0]["id"] == dossier_id


def test_non_gatekeeper_character_cannot_be_named_as_gatekeeper(game):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
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


def test_ordinary_rejection_cannot_claim_midzhi_unpromulgatable(game):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")
    context = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    verdict = _rejected_verdict(
        dossier_id, context["imperial_authority_band"], midzhi=True,
    )

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
    dossier = db.get_decree_dossier(dossier_id)
    product = produce_forecast_product(
        session, snapshot_for_existing_dossier(session, dossier),
    )

    assert product["verdict"] == {"dossier_id": dossier_id, "decision": "promulgated"}
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"
    assert db.list_decree_dossier_decisions(dossier_id) == []
