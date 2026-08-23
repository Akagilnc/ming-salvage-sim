import json

import ming_sim.cli_backend as cli_backend


def test_single_pay_order_capture_requires_entries_and_teaches_canonical_context(game, monkeypatch):
    db, _state, content = game
    prompts = []

    def fake(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return json.dumps({
            "拟旨意图": "拟旨",
            "动作类型": "pay_order_override",
            "entries": [{"key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": 3}],
            "目标类型": "account",
            "目标ID": "pay_order",
            "颁布方式": "普通",
        }, ensure_ascii=False), {}

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", fake)
    result = cli_backend.extract_draft_intent_with_roster_heal(
        "拟旨让陕西边饷居末三个月", "臣已拟妥", db=db, content=content,
    )
    assert result["entries"][0]["key"] == "due_priority_军饷@shaanxi"
    assert "陕西=@shaanxi" in prompts[0]
    assert "until_turn=当前 turn+N-1" in prompts[0]
    assert "默认军饷/官俸/宗禄/赈济=10/20/30/40" in prompts[0]


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
