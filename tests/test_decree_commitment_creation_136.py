import json
from pathlib import Path

import ming_sim.issues as I
from ming_sim.simulation import _extractor_context_payload


ROOT = Path(__file__).resolve().parents[1]


def _issue_by_title(db, title: str):
    return db.conn.execute("SELECT * FROM issues WHERE title=?", (title,)).fetchone()


def test_issue_extractor_prompt_routes_until_stop_decree_commitments():
    prompt = (ROOT / "content/prompts/score_extractor_issues.md").read_text(encoding="utf-8")

    assert "每月 X 直到补齐" in prompt
    assert "commitment_kind" in prompt
    assert "until_stop" in prompt
    assert "origin_ref" in prompt
    assert "ongoing_effects" in prompt
    assert "stop_condition" in prompt
    assert '{"army.guanning.arrears":"<=0"}' in prompt


def test_issue_extractor_prompt_routes_limited_duration_decree_commitments():
    prompt = (ROOT / "content/prompts/score_extractor_issues.md").read_text(encoding="utf-8")

    assert "连续 N 月" in prompt
    assert "半年为限" in prompt
    assert "end_turn = turn + N" in prompt
    assert "ongoing_effects" in prompt
    assert "stop_condition" in prompt


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
    assert payload["condition_role"] == "commitment_stop_condition"
    extractor_payload = _extractor_context_payload(db, state, "", "")
    extractor_issue = next(
        item for item in extractor_payload["active_issues"]
        if item["title"] == "每月补关宁军饷直到补齐"
    )
    assert extractor_issue["commitment_kind"] == "until_stop"
    assert json.loads(extractor_issue["stop_condition"]) == stop_condition
    assert extractor_issue["condition_role"] == "commitment_stop_condition"


def test_until_stop_commitment_shape_rejects_without_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:pay-two-fronts-arrears",
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

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "每月补宣大蓟镇直到补齐") is None


def test_limited_duration_commitment_shape_rejects_without_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:two-month-pay",
                    "kind": "initiative",
                    "title": "连续两月补饷但缺承诺标记",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -40,
                                "category": "补饷承诺",
                                "reason": "连续两月补饷",
                                "purpose": "补饷",
                            }
                        ]
                    },
                    "end_turn": state.turn + 2,
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "连续两月补饷但缺承诺标记") is None


def test_until_stop_commitment_requires_initiative_kind(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:bad-kind",
                    "kind": "situation",
                    "title": "每月补辽饷但类型写成局势",
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "initiative" in rejected["reason"]
    assert _issue_by_title(db, "每月补辽饷但类型写成局势") is None


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
                    "origin_ref": "decree:turn-1:appease-mao",
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


def test_until_stop_commitment_rejects_non_dict_stop_condition(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:bad-stop-string",
                    "kind": "initiative",
                    "title": "每月补辽饷但停止条件是坏串",
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "stop_condition": "army.guanning.arrears <= 0",
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "stop_condition" in rejected["reason"]
    assert _issue_by_title(db, "每月补辽饷但停止条件是坏串") is None


def test_until_stop_commitment_rejects_stop_condition_without_table_prefix(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:bad-stop-key",
                    "kind": "initiative",
                    "title": "每月补辽饷但停止条件无表前缀",
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "stop_condition": {"arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "stop_condition" in rejected["reason"]
    assert _issue_by_title(db, "每月补辽饷但停止条件无表前缀") is None


def test_until_stop_commitment_requires_origin_ref(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "kind": "initiative",
                    "title": "每月补辽饷但无诏书引用",
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "origin_ref" in rejected["reason"]
    assert _issue_by_title(db, "每月补辽饷但无诏书引用") is None


def test_until_stop_commitment_requires_ongoing_effects(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:empty-monthly-action",
                    "kind": "initiative",
                    "title": "每月补辽饷但没有月度动作",
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "ongoing_effects" in rejected["reason"]
    assert _issue_by_title(db, "每月补辽饷但没有月度动作") is None


def test_until_stop_commitment_rejects_direct_resolved_close(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:pay-liao-close-guard",
                    "kind": "initiative",
                    "title": "每月补辽饷直到补齐防误结案",
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )
    row = _issue_by_title(db, "每月补辽饷直到补齐防误结案")

    out = I.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": row["id"], "reason": "resolved", "narrative": "误按承诺完成结案"}]},
    )

    close = out["closes"][0]
    assert close["rejected"] is True
    assert close["category"] == "invalid_enum"
    assert "承诺" in close["reason"]
    after = db.conn.execute("SELECT status FROM issues WHERE id=?", (row["id"],)).fetchone()
    assert after["status"] == "active"


def test_until_stop_commitment_advance_to_full_stays_active(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:pay-liao-advance-guard",
                    "kind": "initiative",
                    "title": "每月补辽饷直到补齐防推进误结案",
                    "bar_value": 90,
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )
    row = _issue_by_title(db, "每月补辽饷直到补齐防推进误结案")

    advanced = db.advance_issue(
        state,
        row["id"],
        trigger_kind="decree",
        delta_bar=20,
        narrative="承诺履行有进展，但停止条件尚未由专门闭环判定。",
    )

    assert advanced["bar_value"] == 100
    assert advanced["status"] == "active"
    assert advanced["closed_turn"] is None


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
                    "origin_ref": "decree:turn-1:pay-liao-arrears",
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
