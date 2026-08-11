import json

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
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
    monkeypatch.setattr(
        db, "list_decree_dossiers_for_simulation",
        lambda _turn: (_ for _ in ()).throw(RuntimeError("after promulgation")),
    )

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
