import json

import pytest

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
from ming_sim.qualitative import qualitative_character_axis, power_band
from ming_sim.models import LLMConfig
from ming_sim.strict_types import IMPERIAL_AUTHORITY_BANDS
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


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
    # 结构键白名单：派系面不含 satisfaction；不扫序列化载体禁词。
    assert context["dossiers"][0]["mode"] == "midzhi"
    assert context["dossiers"][0]["break_rank"] == {"office_rank": "越三级"}
    # 派系投影仅结构字段 name/leverage/agenda，不含 satisfaction 等额外阻力键。
    assert set(context["factions"][0]) == {"name", "leverage", "agenda"}
    assert all("satisfaction" not in row for row in context["factions"])
    assert context["imperial_authority_band"] in IMPERIAL_AUTHORITY_BANDS
    assert context["classes"]
    assert all(isinstance(name, str) for name in context["classes"])
    assert context["gatekeepers"]
    assert all(set(row) == {
        "name", "office", "office_type", "faction", "courage", "integrity",
    } for row in context["gatekeepers"])
    raw_axes = {
        row["name"]: (row["courage"], row["integrity"])
        for row in db.conn.execute("SELECT name,courage,integrity FROM characters")
    }
    assert all(
        row["courage"] == qualitative_character_axis(
            "courage", raw_axes[row["name"]][0]
        )
        and row["integrity"] == qualitative_character_axis(
            "integrity", raw_axes[row["name"]][1]
        )
        and isinstance(row["courage"], str)
        and isinstance(row["integrity"], str)
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
    assert by_name["东林"]["leverage"] == power_band(5)
    assert by_name["阉党"]["leverage"] == power_band(95)
    assert all(
        isinstance(row["leverage"], str)
        and not isinstance(row["leverage"], bool)
        and row["leverage"] in IMPERIAL_AUTHORITY_BANDS
        for row in context["factions"]
    )
    # Resistance remains present; only the projection is qualitative.
    assert all(set(row) == {"name", "leverage", "agenda"} for row in context["factions"])
    assert any(row["agenda"] for row in context["factions"])


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

    with pytest.raises(decree_mod.LLMContractError):
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
