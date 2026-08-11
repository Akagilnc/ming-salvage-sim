import json

import pytest

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
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
    ]


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
    narrative = db.get_resolve_context(state.turn)["narrative"]
    assert "被打回" in narrative
    assert "尚待批红" in narrative
    assert all(term not in narrative for term in ("清丈已办成", "清丈已生效"))
