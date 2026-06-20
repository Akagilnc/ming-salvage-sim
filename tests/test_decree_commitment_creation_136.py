import json
from pathlib import Path

import ming_sim.issues as I
from ming_sim.db import _has_stop_condition
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


def test_issue_extractor_prompt_routes_future_one_shot_decree_commitments():
    prompt = (ROOT / "content/prompts/score_extractor_issues.md").read_text(encoding="utf-8")

    assert "圣旨承诺 form③" in prompt
    assert "未来一次性" in prompt
    assert "X 月后复试/复核" in prompt
    assert "三月后复试" in prompt
    assert "到期待裁" in prompt
    assert "end_turn" in prompt
    assert "commitment_kind" in prompt
    assert "ongoing_effects 可留空" in prompt
    assert "acknowledged" in prompt
    assert "ACK 收尾" in prompt


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


def test_limited_duration_ongoing_commitment_rejects_current_turn_end_turn(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:current-turn-expired-pay",
                    "kind": "initiative",
                    "title": "本回合即到期的每月补饷承诺",
                    "stage_text": "户部按月拨银补饷，但 end_turn 错落在当前回合。",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -50,
                                "category": "补饷承诺",
                                "reason": "每月补饷",
                                "purpose": "补饷",
                            }
                        ]
                    },
                    "end_turn": state.turn,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "end_turn" in rejected["reason"]
    assert _issue_by_title(db, "本回合即到期的每月补饷承诺") is None


def test_limited_duration_ongoing_commitment_rejects_past_end_turn(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    state.turn = 4
    db.save_state(state)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-4:past-expired-pay",
                    "kind": "initiative",
                    "title": "过去回合已到期的每月补饷承诺",
                    "stage_text": "户部按月拨银补饷，但 end_turn 错落在过去回合。",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -50,
                                "category": "补饷承诺",
                                "reason": "每月补饷",
                                "purpose": "补饷",
                            }
                        ]
                    },
                    "end_turn": state.turn - 1,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "end_turn" in rejected["reason"]
    assert _issue_by_title(db, "过去回合已到期的每月补饷承诺") is None


def test_future_one_shot_commitment_issue_is_created_with_deadline_only(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:sunchengzong-review",
                    "kind": "initiative",
                    "title": "三月后复试孙承宗",
                    "stage_text": "孙承宗暂听候政，三月后复试军国大计。",
                    "end_turn": state.turn + 3,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is False
    row = _issue_by_title(db, "三月后复试孙承宗")
    assert row is not None
    assert row["commitment_kind"] == "until_stop"
    assert row["end_turn"] == state.turn + 3
    assert row["stop_condition"] == ""
    assert json.loads(row["ongoing_effects"]) == {}
    assert row["inertia"] == 0
    assert row["cancellable"] == "decree"
    payload = I.issue_to_payload(row, [])
    assert payload["end_turn"] == state.turn + 3
    assert payload["commitment_kind"] == "until_stop"


def test_open_ended_ongoing_commitment_issue_is_created_with_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:open-ended-appeasement",
                    "kind": "initiative",
                    "title": "长期安抚毛文龙",
                    "stage_text": "遣臣常驻皮岛安抚，未设硬时限。",
                    "ongoing_effects": {"metrics": {"皇威": -1}},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is False
    row = _issue_by_title(db, "长期安抚毛文龙")
    assert row is not None
    assert row["commitment_kind"] == "until_stop"
    assert row["end_turn"] == 0
    assert row["stop_condition"] == ""
    assert json.loads(row["ongoing_effects"]) == {"metrics": {"皇威": -1}}
    assert row["cancellable"] == "decree"


def test_open_ended_ongoing_commitment_shape_rejects_without_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:open-ended-without-marker",
                    "kind": "initiative",
                    "title": "长期安抚毛文龙但缺承诺标记",
                    "stage_text": "遣臣常驻皮岛安抚，未设硬时限。",
                    "ongoing_effects": {"metrics": {"皇威": -1}},
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "长期安抚毛文龙但缺承诺标记") is None


def test_future_one_shot_commitment_shape_rejects_without_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:sunchengzong-review-without-marker",
                    "kind": "initiative",
                    "title": "三月后复核孙承宗但缺承诺标记",
                    "stage_text": "孙承宗暂听候政，三月后复核。",
                    "end_turn": state.turn + 3,
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "三月后复核孙承宗但缺承诺标记") is None


def test_stop_condition_only_commitment_shape_rejects_without_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:stop-only-mao",
                    "kind": "initiative",
                    "title": "只写停止条件的安抚毛文龙",
                    "stage_text": "只写达到忠诚阈值，没有月度安抚动作。",
                    "stop_condition": {"character.毛文龙.loyalty": ">=65"},
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "只写停止条件的安抚毛文龙") is None


def test_string_stop_condition_only_with_origin_ref_rejects_without_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:stop-only-string",
                    "kind": "initiative",
                    "title": "字符串停止条件但无月度动作",
                    "stage_text": "有诏书来源和停止条件，但没有每月动作。",
                    "stop_condition": "character.毛文龙.loyalty >= 65",
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "字符串停止条件但无月度动作") is None


def test_legacy_resolve_condition_person_commitment_rejects_without_marker(game, monkeypatch):
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
                    "title": "旧形状安抚毛文龙",
                    "stage_text": "旧 payload 用 resolve_condition 表达人物承诺阈值。",
                    "resolve_condition": "character.毛文龙.loyalty >= 65",
                    "ongoing_effects": {
                        "人物变更": [
                            {
                                "name": "毛文龙",
                                "动作": "评定",
                                "loyalty": 2,
                                "reason": "每月安抚",
                            }
                        ]
                    },
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is True
    assert created["category"] == "invalid_enum"
    assert "commitment_kind" in created["reason"]
    assert _issue_by_title(db, "旧形状安抚毛文龙") is None


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


def test_commitment_rejects_string_numeric_person_loyalty_ongoing_effect(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:string-loyalty-appease",
                    "kind": "initiative",
                    "title": "字符串忠诚安抚承诺",
                    "stage_text": "每月安抚毛文龙，但 loyalty 错写成字符串。",
                    "ongoing_effects": {
                        "人物变更": [
                            {
                                "name": "毛文龙",
                                "动作": "评定",
                                "loyalty": "2",
                                "reason": "奉旨持续安抚",
                            }
                        ]
                    },
                    "end_turn": state.turn + 2,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert "loyalty" in rejected["reason"]
    assert _issue_by_title(db, "字符串忠诚安抚承诺") is None


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


def test_until_stop_commitment_rejects_semantically_empty_ongoing_effects(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:empty-shell-monthly-action",
                    "kind": "initiative",
                    "title": "每月补辽饷但月度动作只是空壳",
                    "ongoing_effects": {"economy": [], "metrics": {}},
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
    assert _issue_by_title(db, "每月补辽饷但月度动作只是空壳") is None


def test_until_stop_commitment_rejects_one_shot_entity_creation_as_monthly_work(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:bad-monthly-army-create",
                    "kind": "initiative",
                    "title": "每月重复建军的错误承诺",
                    "ongoing_effects": {
                        "new_armies": [
                            {"id": "bad_monthly_army", "name": "月度重复新军", "manpower": 1000}
                        ]
                    },
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
    assert "new_armies" in rejected["reason"]
    assert _issue_by_title(db, "每月重复建军的错误承诺") is None


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


def test_until_stop_commitment_rejects_direct_failed_close_without_effects(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    starting_popular_support = int(state.metrics["民心"])

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": "decree:turn-1:pay-liao-fail-guard",
                    "kind": "initiative",
                    "title": "每月补辽饷直到补齐防失败误结案",
                    "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补饷"}]},
                    "effect_on_fail": {"metrics": {"民心": -7}},
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )
    row = _issue_by_title(db, "每月补辽饷直到补齐防失败误结案")

    out = I.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": row["id"], "reason": "failed", "narrative": "误按承诺失败结案"}]},
    )

    close = out["closes"][0]
    assert close["rejected"] is True
    assert close["category"] == "invalid_enum"
    assert "承诺" in close["reason"]
    after = db.conn.execute("SELECT status FROM issues WHERE id=?", (row["id"],)).fetchone()
    assert after["status"] == "active"
    assert int(state.metrics["民心"]) == starting_popular_support
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='close'",
        (row["id"],),
    ).fetchone()[0] == 0


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


def test_stop_condition_without_commitment_kind_advance_to_full_stays_active(game):
    """insert_issue 可直接持久化 stop_condition；即便 commitment_kind 为空，
    advance_issue 也不能仅因 bar_value 到 100 自动 resolved，必须等停止条件闭环判定。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="直接插入停止条件防推进误结案",
        origin_kind="decree",
        origin_ref="decree:turn-1:direct-stop",
        bar_value=90,
        stop_condition={"army.guanning.arrears": "<=0"},
    )

    advanced = db.advance_issue(
        state,
        issue_id,
        trigger_kind="decree",
        delta_bar=20,
        narrative="进度满值，但停止条件尚未由专门闭环判定。",
    )

    assert advanced["bar_value"] == 100
    assert advanced["status"] == "active"
    assert advanced["closed_turn"] is None


def test_has_stop_condition_handles_preparsed_and_json_whitespace():
    assert _has_stop_condition({"army.guanning.arrears": "<=0"}) is True
    assert _has_stop_condition(["legacy"]) is True
    assert _has_stop_condition({}) is False
    assert _has_stop_condition(" { } ") is False
    assert _has_stop_condition("\n[]\n") is False
    # legacy fallback 条件串属于 resolve_condition，不是结构化 commitment stop gate。
    assert _has_stop_condition("character.毛文龙.loyalty >= 65") is False


def test_empty_json_stop_condition_allows_advance_to_resolved(game):
    """stop_condition 里若只是带空白的空 JSON 对象，不应被误判为承诺停止条件。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="空停止条件不阻止结案",
        origin_kind="decree",
        origin_ref="decree:turn-1:empty-stop",
        bar_value=90,
        stop_condition=" { } ",
    )

    advanced = db.advance_issue(
        state,
        issue_id,
        trigger_kind="decree",
        delta_bar=20,
        narrative="进度满值且没有真实停止条件。",
    )

    assert advanced["bar_value"] == 100
    assert advanced["status"] == "resolved"
    assert advanced["closed_turn"] == state.turn


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
