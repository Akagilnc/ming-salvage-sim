"""#117：apply 路径对 LLM 给的「真值非 list/dict」集合加 isinstance 守卫，不崩回合。

根因：`X.get(key) or []` 只兜 None/假值，兜不住真值非 list（true/数字/字符串）——`for x in 它`
抛 TypeError（字符串还逐字符迭代）。
issue-effect 的 economy（经 _apply_economy_list apply choke）与展示用 _format_issue_ongoing。
"""
from __future__ import annotations

from tests.dossier_test_helpers import close_issue_with_effect


def test_apply_economy_list_valid_still_works(game):
    """守卫不误伤正常 list：合法 economy 项经现役结案入口（close_issues 效果）确实落账。"""
    db, state, _content = game
    before = db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0]
    close_issue_with_effect(db, state, "合法经济项", {
        "economy": [{"account": "国库", "delta": -5, "reason": "测试"}],
    })
    rows = db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE reason='测试'").fetchone()[0]
    assert rows >= 1, "合法 economy 项被守卫误吞"
    assert db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0] > before


def test_apply_economy_list_skips_non_dict_items(game):
    """list 内混非 dict 项不崩，跳过非 dict、只落合法项（#117 codex 逐项守），经现役结案入口断言。"""
    db, state, _content = game
    close_issue_with_effect(db, state, "混杂经济项", {
        "economy": [1, "x", None, {"account": "国库", "delta": -3, "reason": "混杂测试"}],
    })
    n = db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE reason='混杂测试'").fetchone()[0]
    assert n == 1, f"非 dict 项未被跳过/合法项未恰落一条：{n}"
