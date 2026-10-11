from ming_sim.settlement.dossier import apply_dossier_verdicts
import json

import pytest

import ming_sim.decree as decree_mod
from ming_sim.exceptions import LLMContractError
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import view
from ming_sim.strict_types import IMPERIAL_AUTHORITY_BANDS
from tests.dossier_test_helpers import rejected_verdict

def _dossier(db, state, text="清丈天下田亩", **payload):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text=text,
        target_kind="issue", target_id=f"policy-{state.turn}", payload=payload,
    )

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

def test_gate_reconsideration_removes_only_named_opponent_and_keeps_real_bench(game):
    from scripts.promulgation_gate_561 import _prepare_reconsideration_facts

    db, state, _content = game
    dossier_id = _dossier(db, state, "不经部议，清丈天下田亩并追夺士绅隐田")
    first = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    original_factions = {row["name"]: row for row in first["factions"]}

    second = _prepare_reconsideration_facts(db, state, dossier_id, first)

    assert [row["name"] for row in second["gatekeepers"]] == ["黄立极", "王体乾"]
    assert db.conn.execute(
        "SELECT status FROM characters WHERE name='许誉卿'"
    ).fetchone()["status"] == "dismissed"
    second_factions = {row["name"]: row for row in second["factions"]}
    assert second_factions["东林"] == {
        "name": "东林", "leverage": "极弱",
        "agenda": "失去许誉卿封驳支点，转入复议",
    }
    assert {
        name: facts for name, facts in second_factions.items() if name != "东林"
    } == {
        name: facts for name, facts in original_factions.items() if name != "东林"
    }
    auth_ids = second["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"]
    assert auth_ids and all(item.isdigit() for item in auth_ids)
    authority = db.get_authority(int(auth_ids[0]))
    assert authority["dossier_id"] != dossier_id
    assert db.dossier_authorizes_effects(int(authority["dossier_id"]))
    assert second["dossiers"][0]["held_authorities"]
    assert second["dossiers"][0]["held_authorities"][0]["privilege"] == "便宜行事"
    assert second["imperial_authority_band"] == "强盛"

def test_gate_reconsideration_resolves_missing_target_to_land_survey(game):
    from scripts.promulgation_gate_561 import _prepare_reconsideration_facts

    db, state, _content = game
    dossier_id = _dossier(db, state, "不经部议，清丈天下田亩并追夺士绅隐田")
    db.conn.execute(
        "UPDATE decree_dossiers SET target_kind='', target_id='' WHERE id=?",
        (dossier_id,),
    )
    first = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )

    second = _prepare_reconsideration_facts(db, state, dossier_id, first)

    held = db.get_decree_dossier(dossier_id)
    assert held["target_kind"] == "issue"
    assert held["target_id"] == "清丈田亩"
    auth_ids = second["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"]
    assert auth_ids and all(item.isdigit() for item in auth_ids)
    authority = db.get_authority(int(auth_ids[0]))
    grant = db.get_decree_dossier(int(authority["dossier_id"]))
    assert authority["scope"] == "issue:清丈田亩"
    assert grant["target_kind"] == "issue"
    assert grant["target_id"] == "清丈田亩"
    assert second["dossiers"][0]["held_authorities"][0]["scope"] == "issue:清丈田亩"

def test_gate_evidence_reloads_dossier_after_reconsideration_mutation(game):
    from scripts.promulgation_gate_561 import _judge_context_for_dossier
    db, state, content = game
    dossier_id = _dossier(db, state)
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    stale = db.get_decree_dossier(dossier_id)
    # Payload authorization strings must not become authorization_ids (#611).
    payload = json.loads(stale["payload_json"])
    payload["authorization_ids"] = ["fresh-authorization"]
    db.conn.execute(
        "UPDATE decree_dossiers SET payload_json=?, executor_kind='character', "
        "executor_id=? WHERE id=?",
        (json.dumps(payload), holder, dossier_id),
    )
    db.conn.commit()
    grant_dossier_id = db.create_decree_dossier(
        state, action_type="authorization", decree_text="另案授以便宜行事",
        target_kind="issue", target_id=f"policy-{state.turn}",
        executor_kind="character", executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(grant_dossier_id, "promulgated")
    grant = view(settle_delta(state, db, {"authority_changes": [{
        "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
        "scope": f"issue:policy-{state.turn}", "dossier_id": grant_dossier_id,
    }]}, SettlementContext(content=content)), "authority_changes")[0]
    authority_id = int(grant["authority_id"])
    assert db.get_authority(authority_id)["dossier_id"] == grant_dossier_id
    assert grant_dossier_id != dossier_id

    stale_context = decree_mod.build_promulgation_judge_context(db, state, [stale])
    fresh_context = _judge_context_for_dossier(db, state, dossier_id)

    # Stale row still lacks executor/target projection inputs until reloaded.
    assert stale_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == []
    assert fresh_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == [
        str(authority_id),
    ]

def test_run_resolve_arm_recovers_settled_verdicts_from_history(game, monkeypatch, tmp_path):
    """Non-awaiting arms must read applied history at the pre-resolve turn."""
    from ming_sim.content import GameContent
    from ming_sim.models import LLMConfig
    from scripts import promulgation_gate_561 as gate

    content = GameContent.load()
    cfg = LLMConfig(
        api_key="", base_url="", model="test", channel="cli",
        cli_runner="codex", cli_model="test",
    )

    def fake_resolve(state, db, *_a, **_k):
        dossiers = db.list_decree_dossiers(status="proposed")
        verdicts = [
            {"dossier_id": int(row["id"]), "decision": "promulgated"}
            for row in dossiers
        ]
        apply_dossier_verdicts(db, state, verdicts, content=content)
        # Settlement advances turn — the bug surface (pending batch writer retired).
        state.turn += 1
        db.save_state(state)
        return decree_mod.ResolveResult(awaiting=False, report="settled")

    monkeypatch.setattr(gate, "resolve_directives", fake_resolve)
    result = gate._run_resolve_arm(
        str(tmp_path), content, cfg,
        name="settled_arm", authority=100, kinds=("hostile",),
    )
    assert result["awaiting"] is False
    assert result["verdicts"], "settled arm must recover applied verdicts"
    assert {int(row["dossier_id"]) for row in result["verdicts"]} == set(
        result["ids"].values()
    )
    assert all(row["decision"] == "promulgated" for row in result["verdicts"])

def test_gatekeeper_successor_removes_donglin_block_posture(game):
    """TD-9 successor must be registered and not recreate the 东林 block."""
    from scripts.promulgation_gate_561 import (
        GATEKEEPER_SUCCESSOR,
        _gatekeeper_names,
        _mutate_gatekeeper_replace,
    )

    db, state, _content = game
    seeded = db.conn.execute(
        "SELECT name, faction, status, power_id FROM characters WHERE name=?",
        (GATEKEEPER_SUCCESSOR,),
    ).fetchone()
    assert seeded is not None, f"successor {GATEKEEPER_SUCCESSOR!r} must be registered"
    assert seeded["power_id"] == "ming"
    assert seeded["faction"] != "东林"

    _mutate_gatekeeper_replace(db, state)
    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    names = _gatekeeper_names(context)
    assert GATEKEEPER_SUCCESSOR in names
    assert "许誉卿" not in names
    successor = next(
        row for row in context["gatekeepers"] if row["name"] == GATEKEEPER_SUCCESSOR
    )
    assert successor["faction"] != "东林"

def test_choose_rescripts_keeps_authority_edge_off_force_promulgated(game):
    """Rejected authority_edge must pick withdrawn/hold, never options[0] force."""
    from scripts.promulgation_gate_561 import _choose_rescripts

    db, state, _content = game
    hostile = _dossier(db, state, "敌对清丈")
    vital = _dossier(db, state, "命门中旨", mode="midzhi")
    appointment = db.create_decree_dossier(
        state, action_type="appointment", decree_text="调任",
        target_kind="character", target_id="许誉卿", payload={"任别": "真除"},
    )
    authority_edge = _dossier(db, state, "越一级特授")
    ordinary_opts = [
        {"label": "强颁", "dossier_id": authority_edge,
         "dossier_decision": "force_promulgated"},
        {"label": "收回", "dossier_id": authority_edge,
         "dossier_decision": "withdrawn"},
        {"label": "留中", "dossier_id": authority_edge,
         "dossier_decision": "hold"},
    ]
    decisions = [
        {"event_id": f"dossier:{hostile}", "title": "批红", "context": "h",
         "options": [
             {"label": "强颁", "dossier_id": hostile,
              "dossier_decision": "force_promulgated"},
             {"label": "收回", "dossier_id": hostile,
              "dossier_decision": "withdrawn"},
             {"label": "留中", "dossier_id": hostile,
              "dossier_decision": "hold"},
         ]},
        {"event_id": f"dossier:{vital}", "title": "批红", "context": "v",
         "options": [
             {"label": "收回", "dossier_id": vital,
              "dossier_decision": "withdrawn"},
             {"label": "留中", "dossier_id": vital,
              "dossier_decision": "hold"},
         ]},
        {"event_id": f"dossier:{appointment}", "title": "批红", "context": "a",
         "options": [
             {"label": "强颁", "dossier_id": appointment,
              "dossier_decision": "force_promulgated"},
             {"label": "收回", "dossier_id": appointment,
              "dossier_decision": "withdrawn"},
             {"label": "留中", "dossier_id": appointment,
              "dossier_decision": "hold"},
         ]},
        {"event_id": f"dossier:{authority_edge}", "title": "批红", "context": "e",
         "options": ordinary_opts},
    ]
    db.save_pending_decisions(state.turn, decisions)
    chosen = _choose_rescripts(
        db, state.turn, hostile, vital, appointment,
    )
    by_event = {row["event_id"]: row["choice"] for row in chosen}
    assert by_event[f"dossier:{hostile}"]["dossier_decision"] == "hold"
    assert by_event[f"dossier:{vital}"]["dossier_decision"] == "withdrawn"
    assert by_event[f"dossier:{appointment}"]["dossier_decision"] == "withdrawn"
    assert by_event[f"dossier:{authority_edge}"]["dossier_decision"] in {
        "withdrawn", "hold",
    }
    assert by_event[f"dossier:{authority_edge}"]["dossier_decision"] != (
        "force_promulgated"
    )

def test_ordinary_class_all_promulgated_covers_planted_ordinary_only():
    """TD-1 / ADR 0055 S6: ordinary class planted dossiers must all pass or the arm fails."""
    from scripts.promulgation_gate_561 import _ordinary_class_all_promulgated

    assert _ordinary_class_all_promulgated([
        ({"ordinary": 1, "hostile": 2},
         {1: {"decision": "promulgated"}, 2: {"decision": "rejected"}}),
        ({"ordinary": 3},
         {3: {"decision": "promulgated"}}),
    ]) is True
    assert _ordinary_class_all_promulgated([
        ({"ordinary": 1}, {1: {"decision": "rejected"}}),
    ]) is False
    assert _ordinary_class_all_promulgated([
        ({"ordinary": 1}, {1: {"decision": "promulgated"}}),
        ({"ordinary": 4}, {4: {"decision": "rejected"}}),
    ]) is False
    # Arms without ordinary do not invent a sample; empty plant is not a pass.
    assert _ordinary_class_all_promulgated([
        ({"hostile": 2}, {2: {"decision": "rejected"}}),
    ]) is False

def test_leader_only_mutation_changes_faction_posture_not_roster(game):
    """TD-9: 安抚首领 = 东林 agenda posture; 许誉卿 stays; no 钱谦益 roster swap."""
    from scripts.promulgation_gate_561 import (
        BASE_DONGLIN_AGENDA,
        LEADER_APPEASED_AGENDA,
        _apply_base_board,
        _faction_row,
        _gatekeeper_names,
        _mutate_leader_only,
        _plant_dossiers,
    )

    db, state, _content = game
    _apply_base_board(db, state, authority=100)
    _plant_dossiers(db, state, ("hostile",))
    before = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    qian_before = db.conn.execute(
        "SELECT status, office FROM characters WHERE name='钱谦益'"
    ).fetchone()

    _mutate_leader_only(db, state)
    after = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )

    # Gatekeeper bench unchanged — 安抚首领 ≠ 换把关人.
    assert "许誉卿" in _gatekeeper_names(after)
    assert _gatekeeper_names(after) == _gatekeeper_names(before)
    assert after["gatekeepers"] == before["gatekeepers"]

    before_faction = _faction_row(before, "东林")
    after_faction = _faction_row(after, "东林")
    assert before_faction["agenda"] == BASE_DONGLIN_AGENDA
    assert after_faction["agenda"] == LEADER_APPEASED_AGENDA
    # Posture moves only via fixed agenda pair (ADR 0143: no int() on qualitative leverage).
    assert after_faction["agenda"] != before_faction["agenda"]
    assert before_faction["leverage"] == after_faction["leverage"]
    assert isinstance(before_faction["leverage"], str)
    assert before_faction["leverage"] in IMPERIAL_AUTHORITY_BANDS
    # Full payload distinguishable so evidence trace can pair leader vs baseline.
    assert after["factions"] != before["factions"]
    assert after != before

    # Forbidden: only rehab 钱谦益 roster and pretend that is 安抚.
    qian_after = db.conn.execute(
        "SELECT status, office FROM characters WHERE name='钱谦益'"
    ).fetchone()
    assert qian_after["status"] == qian_before["status"]
    assert qian_after["office"] == qian_before["office"]

def _rejected_verdict(dossier_id, authority_band, *, midzhi=False):
    # Preserve suite-specific reason/intensity differences via builder knobs.
    return rejected_verdict(
        dossier_id, authority_band, midzhi=midzhi,
        reason="触犯钱粮命门，科臣封驳。", intensity="strong",
    )

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
