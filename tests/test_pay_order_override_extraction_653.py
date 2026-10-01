import json
import re

import pytest

import ming_sim.cli_backend as cli_backend


def test_single_pay_order_capture_grounds_relative_deadline_at_current_turn(game, monkeypatch):
    db, _state, content = game
    prompts = []
    db.conn.execute("UPDATE game_state SET turn=7 WHERE id=1")

    def fake(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return json.dumps({
            "拟旨意图": "拟旨",
            "动作类型": "pay_order_override",
            "entries": [
                {"key": "due_priority_军饷@shaanxi", "value": 40, "duration_months": 3},
                {"key": "due_priority_官俸@shaanxi", "value": 10, "duration_months": 3},
            ],
            "目标类型": "account",
            "目标ID": "pay_order",
            "颁布方式": "普通",
        }, ensure_ascii=False), {}

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", fake)
    result = cli_backend.capture_manual_directive_payload(
        "拟旨让陕西边饷居末、官俸优先三个月", None, db=db, content=content,
    )
    assert result["entries"] == [
        {"key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": 9},
        {"key": "due_priority_官俸@shaanxi", "value": 10, "until_turn": 9},
    ]

    # 真实草案→收夜成案 staging；案卷只留适配后的绝对期限。
    from ming_sim.session import GameSession
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = db.load_state("")
    directive = session.add_directive("陕西饷序三个月", dossier_payload=result)
    db.ensure_dossiers_for_draft_directives(session.state)
    dossier = db.get_dossier_for_directive(directive.id)
    staged_entries = json.loads(dossier["payload_json"])["entries"]
    assert staged_entries == result["entries"]
    assert all("duration_months" not in entry for entry in staged_entries)

    # 接地事实段的**结构化内容**是契约：地区 canonical id 映射、相对期限字段名、
    # 以及欠科目闭集与默认优先级的「科目集合 → 优先级取值」映射。取值一律回
    # pay_order 单一真源取，不在此复述其字面排布；事实段的措辞与分隔写法不是契约。
    from ming_sim.pay_order import ARREARS_SUBJECTS, DEFAULT_DUE_PRIORITY, DUE_SUBJECTS

    facts = prompts[0]
    assert "陕西=@shaanxi" in facts
    assert "duration_months" in facts
    for subject in DUE_SUBJECTS:
        assert subject in facts
    for subject in ARREARS_SUBJECTS:
        assert subject in facts

    # 默认优先级：解析事实段里每一处「左列=右列」配对，取左列提到全部 due 科目的
    # 那一处，核对其取值序列 == DEFAULT_DUE_PRIORITY 的取值序列。分隔符任写。
    candidates = [
        (left, right)
        for left, right in re.findall(r"([^\n；;。=]+)=([^\n；;。]+)", facts)
        if all(subject in left for subject in DUE_SUBJECTS)
    ]
    assert len(candidates) == 1, candidates
    values = [int(v) for v in re.findall(r"\d+", candidates[0][1])]
    assert values == [DEFAULT_DUE_PRIORITY[s] for s in DEFAULT_DUE_PRIORITY], candidates


def test_relative_deadline_cannot_stage_llm_computed_expired_turn(game, monkeypatch):
    db, _state, content = game
    db.conn.execute("UPDATE game_state SET turn=7 WHERE id=1")
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_args, **_kwargs: (json.dumps({
            "拟旨意图": "拟旨", "动作类型": "pay_order_override",
            "entries": [{"key": "due_priority_军饷@shaanxi", "value": 40,
                         "until_turn": 3}],
            "目标类型": "account", "目标ID": "pay_order", "颁布方式": "普通",
        }, ensure_ascii=False), {}),
    )
    with pytest.raises(ValueError, match="已过期"):
        cli_backend.capture_manual_directive_payload(
            "陕西边饷居末三个月", None, db=db, content=content,
        )


def test_single_pay_order_capture_rejects_missing_entries(monkeypatch):
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_args, **_kwargs: (json.dumps({
            "拟旨意图": "拟旨", "动作类型": "pay_order_override",
            "目标类型": "account", "目标ID": "pay_order", "颁布方式": "普通",
        }, ensure_ascii=False), {}),
    )
    result = cli_backend.extract_draft_intent("拟旨改饷序", "臣已拟妥")
    assert result["draft_action"] == "无"


def test_multi_pay_order_capture_preserves_reverse_non_tied_priorities(monkeypatch):
    entries = [
        {"key": "due_priority_宗禄@shaanxi", "value": 30},
        {"key": "due_priority_军饷@shaanxi", "value": 10},
    ]
    raw = {"成品旨稿": [
        {"正文": "改陕西饷序", "动作类型": "pay_order_override", "目标类型": "account",
         "目标ID": "pay_order", "颁布方式": "普通", "entries": entries},
        {"正文": "另改折发", "动作类型": "pay_order_override", "目标类型": "account",
         "目标ID": "pay_order", "颁布方式": "普通",
         "entries": [{"key": "due_haircut_bp_军饷@shaanxi#province", "value": 8000}]},
    ]}
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_args, **_kwargs: (json.dumps(raw, ensure_ascii=False), {}),
    )
    result = cli_backend.extract_draft_intent("分别拟两旨", "臣已拟妥", draft_count=2)
    assert result["drafts"][0]["entries"] == entries
    assert result["drafts"][1]["entries"][0]["value"] == 8000
