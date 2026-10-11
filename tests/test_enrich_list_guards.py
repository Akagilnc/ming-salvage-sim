"""#117：apply 路径对 LLM 给的「真值非 list/dict」集合加 isinstance 守卫，不崩回合。

根因：`X.get(key) or []` 只兜 None/假值，兜不住真值非 list（true/数字/字符串）——`for x in 它`
抛 TypeError（字符串还逐字符迭代）。
issue-effect 的 economy（经 _apply_economy_list apply choke）与展示用 _format_issue_ongoing。
"""
from __future__ import annotations

import ming_sim.issues as I
from ming_sim.flows import (
    _apply_class_dict,
    _apply_faction_dict,
    _apply_metric_dict,
)


def _close_issue_with_economy(db, state, title: str, economy: list) -> None:
    """经现役结案入口：立国策（effect_on_resolve.economy）后 close_issues，效果经 _apply_economy_list 落账。"""
    dossier_id = db.create_decree_dossier(state, action_type="policy", decree_text=title, target_kind="issue", target_id=title)
    db.record_dossier_decision(dossier_id, "promulgated")
    I.apply_issue_tracker_output(db, state, {"new_issues": [{
        "origin_kind": "decree", "origin_ref": f"dossier:{dossier_id}", "title": title,
        "kind": "initiative", "effect_on_resolve": {"economy": economy},
    }]})
    issue_id = int(db.conn.execute("SELECT id FROM issues WHERE title=?", (title,)).fetchone()[0])
    I.apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": issue_id, "reason": "resolved"}]})






def test_apply_economy_list_valid_still_works(game):
    """守卫不误伤正常 list：合法 economy 项经现役结案入口（close_issues 效果）确实落账。"""
    db, state, _content = game
    before = db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0]
    _close_issue_with_economy(db, state, "合法经济项", [{"account": "国库", "delta": -5, "reason": "测试"}])
    rows = db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE reason='测试'").fetchone()[0]
    assert rows >= 1, "合法 economy 项被守卫误吞"
    assert db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0] > before






def test_apply_economy_list_skips_non_dict_items(game):
    """list 内混非 dict 项不崩，跳过非 dict、只落合法项（#117 codex 逐项守），经现役结案入口断言。"""
    db, state, _content = game
    _close_issue_with_economy(db, state, "混杂经济项", [1, "x", None, {"account": "国库", "delta": -3, "reason": "混杂测试"}])
    n = db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE reason='混杂测试'").fetchone()[0]
    assert n == 1, f"非 dict 项未被跳过/合法项未恰落一条：{n}"
