import json

import pytest

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
from ming_sim import audience_night
from ming_sim.exceptions import LLMContractError, SettlementAbort
from ming_sim.models import LLMConfig
from ming_sim.qualitative import qualitative_character_axis
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


def test_gate_extracts_actual_cli_judge_payload_and_rejects_ambiguous_capture():
    from scripts.promulgation_gate_561 import (
        _captured_judge_payload,
        _judge_payload_from_prompt,
    )

    expected = {"turn": {"turn": 7}, "dossiers": [{"id": 11}]}
    encoded = json.dumps(expected, ensure_ascii=False, sort_keys=True)
    prompt = f"【系统设定】\njudge\n\n【皇帝/输入】\n{encoded}\n\n【执行约束·必读】done"
    record = {
        "seq": 3, "attempts": 1, "error": None, "prompt": prompt,
        "prompt_chars": len(prompt),
    }

    assert _judge_payload_from_prompt(prompt) == expected
    actual, provenance = _captured_judge_payload([record], expected)
    assert actual == expected
    assert provenance == {
        "source": "MING_SIM_TRACE_PATH real CliChat.invoke prompt",
        "seq": 3, "attempts": 1, "error": None,
        "matches_builder_expectation": True,
    }
    for records in ([], [record, record], [{**record, "attempts": 2}],
                    [{**record, "prompt_chars": len(prompt) - 1}]):
        with pytest.raises(RuntimeError):
            _captured_judge_payload(records, expected)
    with pytest.raises(RuntimeError):
        _judge_payload_from_prompt(prompt.replace(encoded, encoded[:-1]))


def test_promulgation_verdict_list_shape_has_one_canonical_authority(game):
    db, _state, _content = game
    with pytest.raises(decree_mod.LLMContractError, match="颁布判官 verdicts 必须为列表"):
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

    with pytest.raises(decree_mod.LLMContractError, match="未知字段"):
        decree_mod.validate_promulgation_verdicts(
            [verdict], dossiers, db, prepared_context=context,
        )


def test_promulgated_verdict_rejects_rejection_only_fields(game):
    db, state, _content = game
    dossier_id = _dossier(db, state)
    dossiers = db.list_decree_dossiers(status="proposed")

    with pytest.raises(decree_mod.LLMContractError, match="不得携带打回专属字段"):
        decree_mod.validate_promulgation_verdicts([
            {"dossier_id": dossier_id, "decision": "promulgated", "reason": "已封驳"},
        ], dossiers, db)


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
        "name": "东林", "leverage": 5, "agenda": "失去许誉卿封驳支点，转入复议",
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
    from ming_sim.issues import apply_score_extraction

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
    grant = apply_score_extraction(db, state, {"authority_changes": [{
        "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
        "scope": f"issue:policy-{state.turn}", "dossier_id": grant_dossier_id,
    }]}, content=content)["authority_changes"][0]
    assert grant.get("rejected") is not True
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
    assert "fresh-authorization" not in (
        fresh_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"]
    )


def test_gate_second_verdict_reads_pending_or_applied_history_strictly():
    from scripts.promulgation_gate_561 import _select_second_verdict

    rejected = {"dossier_id": 7, "decision": "rejected"}
    promoted = {"dossier_id": 7, "decision": "promulgated"}
    assert _select_second_verdict(True, 7, [promoted], [rejected]) == promoted
    assert _select_second_verdict(False, 7, [rejected], [promoted]) == promoted
    for rows in ([], [{"dossier_id": 7, "decision": ""}],
                 [promoted, promoted], [{"dossier_id": 8, "decision": "promulgated"}]):
        with pytest.raises(RuntimeError):
            _select_second_verdict(True, 7, rows, [])


def test_promulgation_judge_preserves_role_resolved_token_budget(monkeypatch):
    seen = {}
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda _cfg, **kwargs: seen.update(kwargs) or object())
    monkeypatch.setattr(agents_mod, "Agent", lambda **kwargs: kwargs)
    cfg = LLMConfig(api_key="test", base_url="http://unused", model="test", max_tokens=321)

    agents_mod.create_promulgation_judge_agent(cfg, object())

    assert seen["max_tokens"] == 321


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
        if mode == "midzhi":
            verdict["affected_parties"] = [
                {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "weak"},
            ]
    else:
        verdict = _rejected_verdict(
            dossier_id, context["imperial_authority_band"], midzhi=mode == "midzhi",
        )

    assert decree_mod.validate_promulgation_verdicts(
        [verdict], dossiers, db, prepared_context=context,
    ) == [verdict]


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
        with pytest.raises(LLMContractError, match="完整 typed 判据快照"):
            decree_mod.validate_promulgation_verdicts(
                [verdict], dossiers, db, prepared_context=context,
            )


def _stop_after_promulgation(db, monkeypatch):
    monkeypatch.setattr(
        db, "list_decree_dossiers_for_simulation",
        lambda _turn: (_ for _ in ()).throw(RuntimeError("after promulgation")),
    )


def test_default_promulgation_judge_uses_one_batch_and_existing_validator(game, monkeypatch):
    db, state, content = game
    first = _dossier(db, state)
    second = db.create_decree_dossier(
        state, action_type="appointment", decree_text="擢任某官",
        target_kind="character", target_id="candidate",
    )
    calls = []

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())
    def canned(_agent, prompt, tag):
        calls.append((json.loads(prompt), tag))
        return json.dumps({"verdicts": [
            {"dossier_id": first, "decision": "promulgated"},
            {"dossier_id": second, "decision": "promulgated"},
        ]})
    monkeypatch.setattr(decree_mod, "run_agent_text", canned)
    _stop_after_promulgation(db, monkeypatch)

    try:
        decree_mod.resolve_directives(state, db, None, None, [object()], "两旨", content=content)
    except RuntimeError as exc:
        assert str(exc) == "after promulgation"
    else:
        raise AssertionError("resolve should reach the post-promulgation tracer")

    assert len(calls) == 1
    assert calls[0][1] == "promulgation-judge"
    assert [row["id"] for row in calls[0][0]["dossiers"]] == [first, second]
    assert db.get_pending_promulgation_verdicts(state.turn) == [
        {"dossier_id": first, "decision": "promulgated"},
        {"dossier_id": second, "decision": "promulgated"},
    ]


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

    with pytest.raises(decree_mod.LLMContractError, match="输入原值不一致"):
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

    with pytest.raises(decree_mod.LLMContractError, match="完整 typed 判据快照"):
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

    with pytest.raises(decree_mod.LLMContractError, match="只能标记中旨打回"):
        decree_mod.validate_promulgation_verdicts(
            [verdict], dossiers, db, prepared_context=context,
        )


def test_reviewed_and_palace_exempt_dossiers_close_in_one_default_batch(game, monkeypatch):
    db, state, content = game
    minister = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' ORDER BY name LIMIT 1"
    ).fetchone()["name"])

    # The unanswered candidate reaches its dossier only through the end-turn
    # default-approval owner.  Keep it out of an audience night so this is not
    # accidentally the oral-assent path below.
    default_pending = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        target_id=None, payload={
            "text": "未表态默认同意清丈", "actor": minister,
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "default-land",
        },
    )

    # A spoken assent is a different production admission seam: night-approved
    # first, then the close-night batch commits it.
    night = audience_night.open_night(db, state, location="乾清宫", time_of_day="夜")
    spoken_pending = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        target_id=None, payload={
            "text": "亲口应允补发边饷", "actor": minister,
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "spoken-pay",
        },
    )
    db.mark_pending_night_approved([spoken_pending], night_id=night["id"])
    audience_night.close_night(db, state, night_id=night["id"], content=content)
    spoken_assent = next(
        row["id"] for row in db.list_decree_dossiers()
        if row["pending_action_id"] == spoken_pending
    )

    # Secret orders use their real pending-action landing seam and are already
    # promulgated there; an inner-treasury allocation uses the same canonical
    # directive admission seam as the UI and remains an exempt proposed dossier.
    secret_pending = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister,
        target_id=None, payload={
            "title": "密令暗查", "content": "密查辽饷侵冒。", "assignee": minister,
            "tags": [], "deadline_months": 0,
        },
    )
    db.commit_pending_actions(state, action_ids=[secret_pending])
    secret = next(
        row["id"] for row in db.list_decree_dossiers()
        if row["pending_action_id"] == secret_pending
    )
    inner_pending = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        target_id=None, payload={
            "text": "内库内批补饷", "actor": minister,
            "dossier_action_type": "grant_allocation", "target_kind": "issue",
            "target_id": "inner-pay", "account": "内库", "amount": 10,
        },
    )
    db.commit_pending_actions(state, content=content, action_ids=[inner_pending])
    inner = next(
        row["id"] for row in db.list_decree_dossiers()
        if row["pending_action_id"] == inner_pending
    )
    calls = []
    admitted = {}
    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())

    def judge(_agent, prompt, tag):
        context = json.loads(prompt)
        calls.append((context, tag))
        admitted.update({row["decree_text"]: row["id"] for row in context["dossiers"]})
        return json.dumps({"verdicts": [
            {"dossier_id": admitted["未表态默认同意清丈"], "decision": "promulgated"},
            {"dossier_id": admitted["亲口应允补发边饷"], "decision": "promulgated"},
        ]})

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    _stop_after_promulgation(db, monkeypatch)
    with pytest.raises(RuntimeError, match="after promulgation"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "四旨", content=content,
        )

    default_assent = next(
        row["id"] for row in db.list_decree_dossiers()
        if row["pending_action_id"] == default_pending
    )
    assert len(calls) == 1
    assert {row["id"] for row in calls[0][0]["dossiers"]} == {
        default_assent, spoken_assent,
    }
    assert db.get_pending_promulgation_verdicts(state.turn) == [
        {"dossier_id": dossier_id, "decision": "promulgated"}
        for dossier_id in sorted((default_assent, spoken_assent, inner))
    ]
    assert db.get_decree_dossier(secret)["status"] == "promulgated"
    assert db.get_decree_dossier(inner)["promulgation_decision"] == ""


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
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type=action_type, decree_text="密旨照准",
        target_kind="issue", target_id=f"exempt-{action_type}", payload={"mode": mode},
    )
    monkeypatch.setattr(
        decree_mod, "create_promulgation_judge_agent",
        lambda *_a, **_k: pytest.fail("review-exempt 案卷不得送入 LLM"),
    )
    _stop_after_promulgation(db, monkeypatch)

    with pytest.raises(RuntimeError, match="after promulgation"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "密旨照准", content=content,
        )

    assert db.get_pending_promulgation_verdicts(state.turn) == [
        {"dossier_id": dossier_id, "decision": "promulgated"},
    ]
    assert db.list_decree_dossier_decisions(dossier_id) == []


def test_default_rejected_verdict_is_validated_persisted_and_becomes_rescript_decision(
    game, monkeypatch,
):
    db, state, content = game
    dossier_id = _dossier(db, state)
    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
    )
    verdict = _rejected_verdict(dossier_id, context["imperial_authority_band"])
    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"verdicts": [verdict]}, ensure_ascii=False),
    )
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("清丈诏在六科被打回，正等待批红。", k["simulator_payload"]),
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "清丈天下田亩", content=content,
    )

    assert result.awaiting is True
    assert db.get_pending_promulgation_verdicts(state.turn) == [verdict]
    assert result.decisions[0]["event_id"] == f"dossier:{dossier_id}"
    assert {option["label"] for option in result.decisions[0]["options"]} == {"强颁", "收回", "留中"}


@pytest.mark.parametrize(
    "parsed_payload",
    [{}, {"verdicts": None}, {"verdicts": {}}, {"verdicts": "bad"}],
)
def test_malformed_default_top_level_preserves_parsed_payload_in_rejection_report(
    game, monkeypatch, tmp_path, parsed_payload,
):
    db, state, content = game
    _dossier(db, state)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps(parsed_payload, ensure_ascii=False),
    )

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清丈天下田亩", content=content,
        )

    assert exc_info.value.stage == "promulgation"
    rows = db.conn.execute(
        "SELECT item_json FROM rejection_reports WHERE turn=? ORDER BY id", (state.turn,),
    ).fetchall()
    assert [json.loads(row["item_json"]) for row in rows] == [
        parsed_payload if isinstance(parsed_payload, dict)
        else {"raw_value": parsed_payload},
    ]
    assert db.get_pending_promulgation_verdicts(state.turn) == []


def test_invalid_default_rejected_verdict_reaches_rejection_tracer(game, monkeypatch, tmp_path):
    db, state, content = game
    dossier_id = _dossier(db, state)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"verdicts": [{
            "dossier_id": dossier_id, "decision": "rejected",
        }]}),
    )

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清丈天下田亩", content=content,
        )

    assert exc_info.value.stage == "promulgation"
    row = db.conn.execute(
        "SELECT section,item_json,category FROM rejection_reports WHERE turn=?",
        (state.turn,),
    ).fetchone()
    assert (row["section"], row["category"]) == ("promulgation_verdicts", "invalid_shape")
    assert json.loads(row["item_json"])["dossier_id"] == dossier_id
    assert db.get_pending_promulgation_verdicts(state.turn) == []


def test_judge_gate_examples_and_simulator_rejection_narrative_boundary(game, monkeypatch):
    db, state, content = game
    hostile_land = _dossier(db, state, "敌对清丈田亩")
    ordinary_pay = _dossier(db, state, "寻常补发边饷")
    midzhi_pay = _dossier(db, state, "中旨补发边饷", mode="midzhi")
    vital_midzhi = _dossier(db, state, "中旨强夺钱粮命门", mode="midzhi")
    seen_payload = {}

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object())
    def gate_examples(_agent, prompt, tag):
        assert tag == "promulgation-judge"
        context = json.loads(prompt)
        band = context["imperial_authority_band"]
        assert [row["decree_text"] for row in context["dossiers"]] == [
            "敌对清丈田亩", "寻常补发边饷", "中旨补发边饷", "中旨强夺钱粮命门",
        ]
        return json.dumps({"verdicts": [
            _rejected_verdict(hostile_land, band),
            {"dossier_id": ordinary_pay, "decision": "promulgated"},
            {"dossier_id": midzhi_pay, "decision": "promulgated", "affected_parties": [
                {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "weak"},
            ]},
            _rejected_verdict(vital_midzhi, band, midzhi=True),
        ]}, ensure_ascii=False)
    monkeypatch.setattr(decree_mod, "run_agent_text", gate_examples)
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: object())
    def simulator_boundary(_agent, *_a, **kwargs):
        seen_payload.update(kwargs["simulator_payload"])
        return "两道清丈旨意均被打回，尚待批红；两道补饷旨意方进入办理。", kwargs["simulator_payload"]
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", simulator_boundary)

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "四旨并下", content=content,
    )

    assert result.awaiting is True
    assert [row["dossier_id"] for row in db.get_pending_promulgation_verdicts(state.turn)] == [
        hostile_land, ordinary_pay, midzhi_pay, vital_midzhi,
    ]
    assert {row["event_id"] for row in result.decisions} == {
        f"dossier:{hostile_land}", f"dossier:{vital_midzhi}",
    }
    vital = next(row for row in result.decisions if row["event_id"] == f"dossier:{vital_midzhi}")
    assert {option["label"] for option in vital["options"]} == {"收回", "留中"}
    assert {row["id"] for row in seen_payload["decree_dossiers"]} == {ordinary_pay, midzhi_pay}
    # This deterministic test proves payload filtering and rescript options only;
    # semantic narrative acceptance belongs to the real-model gate artifact.
    assert "promulgation_instruction" in seen_payload
