"""economy_moves 段迁入逐项拒收契约（ADR 0008 决定 1，#14 economy 残留 / ADR 0012）。

原先 `_clean_economy_moves`（cleaner，pre-apply）与 `_apply_economy_list`（applier）对
非法 account（∉国库/内库）/非整数 delta 都 `continue` 静默丢、零拒收留痕（#14 模式 A/C）。
改为：统一在 applier 逐项拒收（invalid_enum），cleaner 不再丢、透传坏项给 apply 拒收；
delta==0 仍按 no-op 静默跳。issue-effect 路的 economy 拒收也经 entity/inertia sink 达
rejection_reports，不蒸发。

经 driver.run_settle 端到端查 rejection_reports（与 test_*_section_rejections 同风格）。
"""

from __future__ import annotations

from driver import run_settle


def _rejection_rows(db, turn, section):
    return db.conn.execute(
        "SELECT section, reason, category FROM rejection_reports"
        " WHERE turn=? AND section=? ORDER BY id", (turn, section)
    ).fetchall()


def _guoku(db):
    return db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger WHERE account='国库'").fetchone()[0]


def test_top_level_bad_account_rejected_good_lands(game):
    """顶层 economy_moves 账户非法 → invalid_enum 逐项拒收达 rejection_reports（经 cleaner 透传
    + applier 拒收），同信封合法项照落。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [
            {"account": "金库", "delta": -5, "reason": "非法账户"},
            {"account": "国库", "delta": -3, "reason": "合法"},
        ],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "economy_moves")
    assert len(rows) == 1, rows
    assert rows[0][2] == "invalid_enum", rows
    assert rows[0][1]


def test_top_level_nonint_delta_rejected(game):
    """顶层 economy_moves delta 非整数 → invalid_enum 逐项拒收。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [{"account": "国库", "delta": "很多", "reason": "坏 delta"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "economy_moves") if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows


def test_valid_economy_still_applies_no_reject(game):
    """合法 economy 照常落账、零拒收（不误伤）。"""
    db, state, content = game
    turn = state.turn
    before = _guoku(db)

    run_settle(db, state, content, {
        "economy_moves": [{"account": "国库", "delta": -7, "reason": "正常"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "economy_moves") == []
    assert _guoku(db) < before  # 确实扣账


def test_zero_delta_economy_no_reject_no_apply(game):
    """delta==0 是 no-op，不拒收也不落账（不误报）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [{"account": "国库", "delta": 0, "reason": "空动作"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "economy_moves") == []


def test_issue_effect_bad_account_economy_reaches_reports(game):
    """局势 effect_on_resolve 的 economy 账户非法 → 拒收经 entity_rejections 达
    rejection_reports，不蒸发（与 faction issue-effect 同契约，#14）。"""
    db, state, content = game
    turn = state.turn
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试 economy 拒收留痕", origin_kind="decree",
        origin_ref="", bar_value=50, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=0, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={},
        effect_on_resolve={"economy": [{"account": "金库", "delta": -9, "reason": "非法账户"}]},
        effect_on_fail={}, resolve_condition="", fail_condition="",
        cancellable="decree", cancel_cost={},
    )
    db.conn.commit()

    run_settle(db, state, content, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "issue_summary.entity_rejections")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows
