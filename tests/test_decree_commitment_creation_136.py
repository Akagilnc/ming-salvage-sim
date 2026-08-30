import json
from pathlib import Path

import ming_sim.issues as I
from ming_sim.db import _has_stop_condition
from ming_sim.simulation import _extractor_context_payload


ROOT = Path(__file__).resolve().parents[1]


def _promulgated_commitment_origin(db, state, token: str) -> str:
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"测试承诺：{token}",
        target_kind="issue",
        target_id=token,
        payload={"token": token},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


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
                    "origin_ref": _promulgated_commitment_origin(db, state, "pay-guanning-arrears"),
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
    assert row["origin_ref"].startswith("dossier:")
    assert db.dossier_authorizes_effects(int(row["origin_ref"].split(":", 1)[1]))
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


def test_decree_commitment_dedups_same_batch_fiscal_create_carrier(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "xixue-monthly"),
                    "kind": "initiative",
                    "title": "每月拨西学经费",
                    "stage_text": "太仓每月拨银五十万两办西学。",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -50,
                                "category": "西学经费",
                                "reason": "每月拨西学经费",
                            }
                        ]
                    },
                    "commitment_kind": "until_stop",
                }
            ],
            "fiscal_creates": [
                {
                    "key": "西学经费_base",
                    "account": "国库",
                    "direction": "expense",
                    "init_value": 50,
                    "display": "西学经费",
                    "reason": "同批 extractor 误产的重复月支",
                    "origin_ref": "盘面自发",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert _issue_by_title(db, "每月拨西学经费") is not None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key IN ('西学经费_base', '西学经费_rate')"
    ).fetchone()[0] == 0
    fiscal_result = out["fiscal_creates"][0]
    assert fiscal_result["rejected"] is True
    assert fiscal_result["category"] == "deduped_commitment_carrier"
    assert "承诺 issue" in fiscal_result["reason"]


def test_decree_commitment_does_not_dedup_same_name_income_fiscal_create(game, monkeypatch):
    """ADR0027 dedup 只对【支出】fiscal_create 生效（integrated cmr Gate2 codex correctness）：
    同账户、同名但 direction=income 的新科目（如同名新税收入）与月度【支出】承诺载体无关，
    不得被误去重——否则会静默丢掉真实月收入。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "xixue-monthly"),
                    "kind": "initiative",
                    "title": "每月拨西学经费",
                    "stage_text": "太仓每月拨银五十万两办西学。",
                    "ongoing_effects": {
                        "economy": [
                            {"account": "国库", "delta": -50, "category": "西学经费",
                             "reason": "每月拨西学经费"}
                        ]
                    },
                    "commitment_kind": "until_stop",
                }
            ],
            "fiscal_creates": [
                {
                    # 同账户(国库)、同名(西学经费)，但这是一笔【收入】新科目——与支出承诺无关
                    "key": "西学经费_base",
                    "account": "国库",
                    "direction": "income",
                    "init_value": 50,
                    "display": "西学经费",
                    "reason": "新设西学专项捐输（收入）",
                    "origin_ref": "盘面自发",
                }
            ],
        },
        content=content,
    )

    fiscal_result = out["fiscal_creates"][0]
    assert fiscal_result.get("rejected") is not True   # 收入科目未被误去重
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key IN ('西学经费_base', '西学经费_rate')"
    ).fetchone()[0] >= 1


def test_decree_commitment_same_account_alias_miss_emits_residual_signal(game, monkeypatch, capsys):
    """ADR0027 残留观测：同批、同账户、有 decree 承诺却**异名**未匹配上的 fiscal_create
    照常落账，但必须打日志当试玩信号（便于发现异名漏匹规律，#340 US8）。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "xixue-monthly"),
                    "kind": "initiative",
                    "title": "每月拨西学经费",
                    "stage_text": "太仓每月拨银五十万两办西学。",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -50,
                                "category": "西学经费",
                                "reason": "每月拨西学经费",
                            }
                        ]
                    },
                    "commitment_kind": "until_stop",
                }
            ],
            "fiscal_creates": [
                {
                    # 同账户(国库)、但科目名与承诺(西学经费)对不上 = 异名漏匹
                    "key": "xuguangqi_gongfei_base",
                    "account": "国库",
                    "direction": "expense",
                    "init_value": 50,
                    "display": "徐光启三务公费",
                    "reason": "月支",
                    "origin_ref": "盘面自发",
                }
            ],
        },
        content=content,
    )

    # 异名 → 未去重，fiscal_create 照常落账（不被拒）
    fiscal_result = out["fiscal_creates"][0]
    assert fiscal_result.get("rejected") is not True
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key IN "
        "('xuguangqi_gongfei_base', 'xuguangqi_gongfei_rate')"
    ).fetchone()[0] >= 1
    # 但必须留下 ADR0027 残留观测信号（试玩可见 = 能发现异名漏匹规律）
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "ADR0027 残留观测" in combined
    assert "徐光启三务公费" in combined


def test_decree_commitment_unrelated_account_no_residual_signal(game, monkeypatch, capsys):
    """残留观测只在【同账户】触发：不同账户的无关 fiscal_create 不应误报信号。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "xixue-monthly"),
                    "kind": "initiative",
                    "title": "每月拨西学经费",
                    "stage_text": "太仓每月拨银五十万两办西学。",
                    "ongoing_effects": {
                        "economy": [
                            {"account": "国库", "delta": -50, "category": "西学经费",
                             "reason": "每月拨西学经费"}
                        ]
                    },
                    "commitment_kind": "until_stop",
                }
            ],
            "fiscal_creates": [
                {
                    "key": "neiku_dujiang_base",
                    "account": "内库",  # 不同账户
                    "direction": "expense",
                    "init_value": 10,
                    "display": "督江差役",
                    "reason": "月支",
                }
            ],
        },
        content=content,
    )

    captured = capsys.readouterr()
    assert "ADR0027 残留观测" not in (captured.out + captured.err)


def test_until_stop_commitment_shape_rejects_without_explicit_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_limited_duration_commitment_shape_rejects_without_explicit_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_limited_duration_ongoing_commitment_rejects_current_turn_end_turn(read_game, monkeypatch):
    db, state, content = read_game
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "sunchengzong-review"),
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "open-ended-appeasement"),
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


def test_open_ended_ongoing_commitment_shape_rejects_without_explicit_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_future_one_shot_commitment_shape_rejects_without_explicit_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_stop_condition_only_commitment_shape_rejects_without_explicit_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_string_stop_condition_only_with_origin_ref_rejects_without_explicit_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_legacy_resolve_condition_person_commitment_rejects_without_marker(read_game, monkeypatch):
    db, state, content = read_game
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


def test_until_stop_commitment_requires_initiative_kind(read_game, monkeypatch):
    db, state, content = read_game
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "appease-mao"),
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


def test_commitment_rejects_new_person_loyalty_ongoing_effect(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "new-rating"),
                    "kind": "initiative",
                    "title": "字符串忠诚安抚承诺",
                    "stage_text": "每月安抚毛文龙，但 loyalty 错写成字符串。",
                    "ongoing_effects": {
                        "人物变更": [
                            {
                                "name": "毛文龙",
                                "动作": "评定",
                                "loyalty": 2,
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
    assert "评定" in rejected["reason"]
    assert _issue_by_title(db, "字符串忠诚安抚承诺") is None


def test_until_stop_commitment_rejects_non_dict_stop_condition(read_game, monkeypatch):
    db, state, content = read_game
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


def test_until_stop_commitment_rejects_stop_condition_without_table_prefix(read_game, monkeypatch):
    db, state, content = read_game
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


def test_until_stop_commitment_requires_origin_ref(read_game, monkeypatch):
    db, state, content = read_game
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


def test_person_loyalty_commitment_accepts_typed_gate_without_ongoing_effects(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "appease-mao"),
                    "kind": "initiative",
                    "title": "安抚毛文龙",
                    "stop_condition": {"character.毛文龙.loyalty": ">=65"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is not True
    row = _issue_by_title(db, "安抚毛文龙")
    assert row is not None
    assert json.loads(row["ongoing_effects"]) == {}
    assert json.loads(row["stop_condition"]) == {"character.毛文龙.loyalty": ">=65"}


def test_reverse_person_loyalty_gate_gets_no_empty_ongoing_exemption(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = I.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "reverse-loyalty-gate"),
                    "kind": "initiative",
                    "title": "反向忠诚门",
                    "stop_condition": {"character.毛文龙.loyalty": "<=40"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    rejected = out["issue_summary"]["new_issues"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert rejected["item"]["stop_condition"] == {"character.毛文龙.loyalty": "<=40"}
    assert _issue_by_title(db, "反向忠诚门") is None


def test_until_stop_commitment_rejects_semantically_empty_ongoing_effects(read_game, monkeypatch):
    db, state, content = read_game
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


def test_until_stop_commitment_rejects_one_shot_entity_creation_as_monthly_work(read_game, monkeypatch):
    db, state, content = read_game
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "pay-liao-close-guard"),
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "pay-liao-fail-guard"),
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "pay-liao-advance-guard"),
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
                    "origin_ref": _promulgated_commitment_origin(db, state, "pay-liao-arrears"),
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
                    "origin_ref": "盘面自发",
                }
            ]
        },
        content=content,
    )

    assert out["economy_moves"][0]["delta"] == -20
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before
