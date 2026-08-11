import json

import ming_sim.decree as decree_mod


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
