import json

import ming_sim.issues as I


def _issue_by_title(db, title: str):
    return db.conn.execute("SELECT * FROM issues WHERE title=?", (title,)).fetchone()


def test_until_stop_commitment_issue_is_created_with_carrier_fields(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    stop_condition = {"army.guanning.arrears": "<=0"}

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:pay-guanning-arrears",
                    "kind": "initiative",
                    "title": "每月补关宁军饷直到补齐",
                    "bar_value": 20,
                    "stage_text": "户部按月拨银补关宁旧欠",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -50,
                                "category": "补饷承诺",
                                "reason": "每月补关宁欠饷",
                                "purpose": "补饷",
                                "target_kind": "army",
                                "target_id": "guanning",
                            }
                        ]
                    },
                    "stop_condition": stop_condition,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is False
    row = _issue_by_title(db, "每月补关宁军饷直到补齐")
    assert row is not None
    assert row["origin_kind"] == "decree"
    assert row["origin_ref"] == "decree:turn-1:pay-guanning-arrears"
    assert row["kind"] == "initiative"
    assert row["commitment_kind"] == "until_stop"
    assert row["inertia"] == 0
    assert row["cancellable"] == "decree"
    assert json.loads(row["ongoing_effects"])["economy"][0]["target_id"] == "guanning"
    assert json.loads(row["stop_condition"]) == stop_condition
    assert json.loads(row["effect_on_resolve"]) == {}
    payload = I.issue_to_payload(row, [])
    assert payload["commitment_kind"] == "until_stop"
    assert json.loads(payload["stop_condition"]) == stop_condition
    assert payload["结案条件"] == "(未填)"


def test_until_stop_commitment_marker_can_be_inferred_from_carrier_shape(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "kind": "initiative",
                    "title": "每月补宣大蓟镇直到补齐",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -80,
                                "category": "补饷承诺",
                                "reason": "每月补宣大蓟镇欠饷",
                                "purpose": "补饷",
                            }
                        ]
                    },
                    "stop_condition": {"army.xuan_da|jizhen.arrears.sum": "<=0"},
                }
            ]
        },
        content=content,
    )

    row = _issue_by_title(db, "每月补宣大蓟镇直到补齐")
    assert row["commitment_kind"] == "until_stop"
    assert row["cancellable"] == "decree"
    assert row["inertia"] == 0
    assert json.loads(row["stop_condition"]) == {"army.xuan_da|jizhen.arrears.sum": "<=0"}


def test_until_stop_commitment_supports_character_loyalty_condition(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "kind": "initiative",
                    "title": "安抚毛文龙直到效顺",
                    "stage_text": "遣臣赴皮岛安抚",
                    "ongoing_effects": {"metrics": {"皇威": -1}},
                    "stop_condition": {"character.毛文龙.loyalty": ">=65"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    row = _issue_by_title(db, "安抚毛文龙直到效顺")
    assert row["commitment_kind"] == "until_stop"
    assert json.loads(row["stop_condition"]) == {"character.毛文龙.loyalty": ">=65"}


def test_commitment_skips_cli_resolve_effect_enrich(game, monkeypatch):
    import ming_sim.cli_backend as _cb

    db, state, content = game
    calls = []
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(
        _cb,
        "enrich_initiative_effects",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or {"effect_on_resolve": {"metrics": {"民心": 9}}, "ongoing_effects": {}, "effect_on_fail": {}},
    )

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "kind": "initiative",
                    "title": "每月补辽饷直到补齐",
                    "ongoing_effects": {
                        "economy": [
                            {"account": "国库", "delta": -50, "category": "补饷承诺", "reason": "每月补辽饷"}
                        ]
                    },
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    row = _issue_by_title(db, "每月补辽饷直到补齐")
    assert calls == []
    assert json.loads(row["effect_on_resolve"]) == {}


def test_one_shot_appeasement_economy_move_does_not_create_commitment_issue(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    before = db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]

    out = I.apply_score_extraction(
        db,
        state,
        {
            "economy_moves": [
                {
                    "account": "内库",
                    "delta": -20,
                    "category": "一次性赏赐",
                    "reason": "赏毛文龙银二十万安其心",
                }
            ]
        },
        content=content,
    )

    assert out["economy_moves"][0]["delta"] == -20
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before
