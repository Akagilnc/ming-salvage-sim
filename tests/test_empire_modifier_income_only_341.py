"""帝国修正只作用收入、不放大支出（issue #341）。

根因：record_issue_economy_move 对支出（delta < 0）也调 apply_legacy_pct，
把「国库 -12%」从「收入缩水 12%」错误地变成「支出涨价 12%」。
修法：帝国修正只对正向流水（delta > 0）生效；负向流水按面值落账。

开局 4 条负 legacy 累加：-2-3-4-3 = -12% 国库修正（可从 opening_legacies.json 核实）。
"""

from __future__ import annotations
from ming_sim.db import GameDB


def test_expenditure_not_amplified_by_legacy(game):
    """国库 -12% 帝国修正 → 支出 50 万实扣 50，不放大成 56（issue #341 主 seam）。"""
    db, state, content = game
    net_pct = int(db.legacy_modifiers(state).get("国库", 0) or 0)
    assert net_pct < 0, f"前置条件：游戏开局应有负的国库帝国修正（实为 {net_pct}）"

    state.metrics["国库"] = 100
    actual = db.record_issue_economy_move(state, "国库", -50, "测试", "测试支出 #341")

    assert actual == -50, (
        f"支出 50 万应按面值扣账（-50），不被帝国修正放大；"
        f"实扣 {actual}（net_pct={net_pct}）"
    )


def test_income_still_modified_by_legacy(game):
    """国库 -12% 帝国修正 → 收入 100 万仍被折减（issue #341：只去掉支出侧放大，收入侧保持修正）。"""
    db, state, content = game
    net_pct = int(db.legacy_modifiers(state).get("国库", 0) or 0)
    assert net_pct < 0, f"前置条件：游戏开局应有负的国库帝国修正（实为 {net_pct}）"

    state.metrics["国库"] = 0
    actual = db.record_issue_economy_move(state, "国库", 100, "测试", "测试收入 #341")

    expected = int(round(100 * (1 + net_pct / 100.0)))
    assert actual == expected, (
        f"收入 100 万应经帝国修正折为 {expected}（net_pct={net_pct}）；实入 {actual}"
    )


def test_expenditure_zero_net_pct_unchanged(game):
    """无帝国修正（net_pct=0）时支出原值落账（回归：不因代码路径改动误伤 net=0 情形）。"""
    db, state, content = game
    # 清空所有 active legacies 使 国库 修正归零
    db.conn.execute("UPDATE legacies SET status='expired' WHERE status='active'")
    db.conn.commit()
    db._legacy_mod_cache = None

    net_pct = int(db.legacy_modifiers(state).get("国库", 0) or 0)
    assert net_pct == 0, f"前置条件失败：清空 legacy 后国库修正应为 0，实为 {net_pct}"

    state.metrics["国库"] = 100
    actual = db.record_issue_economy_move(state, "国库", -30, "测试", "零修正支出 #341")
    assert actual == -30, f"无修正时支出 30 应原值 -30 落账，实得 {actual}"
