import json

import pytest

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
from ming_sim import audience_night
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import LLMConfig
from ming_sim.strict_types import IMPERIAL_AUTHORITY_BANDS


def _dossier(db, state, text="清丈天下田亩", **payload):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text=text,
        target_kind="issue", target_id=f"policy-{state.turn}", payload=payload,
    )


def test_promulgation_context_is_deterministic_and_excludes_satisfaction(game):
    db, state, _content = game
    dossier_id = _dossier(db, state, mode="中旨")
    context = decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
        break_rank_by_dossier={dossier_id: {"office_rank": "越三级"}},
    )

    assert context == decree_mod.build_promulgation_judge_context(
        db, state, db.list_decree_dossiers(status="proposed"),
        break_rank_by_dossier={dossier_id: {"office_rank": "越三级"}},
    )
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True)
    assert "satisfaction" not in encoded
    assert "满意" not in encoded
    assert context["dossiers"][0]["mode"] == "中旨"
    assert context["dossiers"][0]["break_rank"] == {"office_rank": "越三级"}
    assert set(context["factions"][0]) == {"name", "leverage", "agenda"}
    assert context["imperial_authority_band"] in IMPERIAL_AUTHORITY_BANDS
    assert context["classes"]
    assert all(isinstance(name, str) for name in context["classes"])
    assert context["gatekeepers"]
    assert all(set(row) == {
        "name", "office", "office_type", "faction", "courage", "integrity",
    } for row in context["gatekeepers"])
    assert context["dossiers"][0]["criteria_snapshot_source"] == {
        "imperial_authority_band": context["imperial_authority_band"],
        "involved_office_types": ["未指定"], "authorization_ids": [],
        "endorsement_entry_ids": [],
    }


def test_promulgation_history_only_projects_forced_and_midzhi_markers(game):
    db, state, _content = game
    regular = _dossier(db, state)
    midzhi_pass = _dossier(db, state, text="中旨补饷", mode="中旨")
    midzhi_reject = _dossier(db, state, text="中旨清丈", mode="中旨")
    for dossier_id, decision, action in (
        (regular, "rejected", ""),
        (regular, "rejected", "force_promulgated"),
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
        {"dossier_id": regular, "turn": state.turn, "mode": "regular",
         "marker": "批红强颁", "outcome": "promulgated"},
        {"dossier_id": midzhi_pass, "turn": state.turn, "mode": "中旨",
         "marker": "中旨", "outcome": "promulgated"},
        {"dossier_id": midzhi_reject, "turn": state.turn, "mode": "中旨",
         "marker": "中旨", "outcome": "rejected"},
        {"dossier_id": midzhi_reject, "turn": state.turn, "mode": "中旨",
         "marker": "批红强颁", "outcome": "promulgated"},
    ]


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
    assert second["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == [
        "御笔特准清丈不经部议",
    ]
    assert second["imperial_authority_band"] == "强盛"


def test_gate_evidence_reloads_dossier_after_reconsideration_mutation(game):
    from scripts.promulgation_gate_561 import _judge_context_for_dossier

    db, state, _content = game
    dossier_id = _dossier(db, state)
    stale = db.get_decree_dossier(dossier_id)
    payload = json.loads(stale["payload_json"])
    payload["authorization_ids"] = ["fresh-authorization"]
    db.conn.execute(
        "UPDATE decree_dossiers SET payload_json=? WHERE id=?",
        (json.dumps(payload), dossier_id),
    )
    db.conn.commit()

    stale_context = decree_mod.build_promulgation_judge_context(db, state, [stale])
    fresh_context = _judge_context_for_dossier(db, state, dossier_id)

    assert stale_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == []
    assert fresh_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == [
        "fresh-authorization",
    ]


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
    return {
        "dossier_id": dossier_id,
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": ["东林"],
        "gatekeeper_id": None,
        "reason": "触犯钱粮命门，科臣封驳。",
        "criteria_snapshot": {
            "imperial_authority_band": authority_band,
            "involved_office_types": ["未指定"],
            "authorization_ids": [],
            "endorsement_entry_ids": [],
        },
        "affected_parties": [
            {"kind": "faction", "key": "东林", "severity": "大怒"},
        ],
        **({"midzhi_unpromulgatable": True} if midzhi else {}),
    }


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
        ("involved_office_types", ["六部"]),
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


def test_regular_rejection_cannot_claim_midzhi_unpromulgatable(game):
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
    midzhi_pay = _dossier(db, state, "中旨补发边饷", mode="中旨")
    vital_midzhi = _dossier(db, state, "中旨强夺钱粮命门", mode="中旨")
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
                {"kind": "faction", "key": "东林", "severity": "不满"},
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
