"""economy_moves 段迁入逐项拒收契约（ADR 0008 决定 1，#14 economy 残留 / ADR 0012）。

原先 `_clean_economy_moves`（cleaner，pre-apply）与 `_apply_economy_list`（applier）对
非法 account（∉国库/内库）/非整数 delta（含 bool/float）都 `continue` 静默丢、零拒收留痕
（#14 模式 A/C）。改为：统一在 applier 逐项拒收（invalid_enum），cleaner 不再丢、透传坏项
给 apply 拒收；delta==0/缺额 仍按 no-op 静默跳。顶层拒收落独立 economy_moves_rejections 段
（不污染玩家可见 economy_moves list、_player_visible pop）；issue-effect 路 economy 拒收经
entity/inertia sink 达 rejection_reports，不蒸发。

从现役原子声明入口验证 applier 的拒收契约。
"""

from __future__ import annotations

from functools import partial

from tests.section_rejection_helpers import run_declaration as run_settle
from tests.section_rejection_helpers import game, rejection_rows

ECO_REJ = "economy_moves_rejections"


_rejection_rows = partial(rejection_rows, columns="section, reason, category")


def _guoku(db):
    return db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger WHERE account='国库'").fetchone()[0]


def test_top_level_bad_account_rejected_good_lands(game):
    """顶层 economy_moves 账户非法 → invalid_enum 逐项拒收达 rejection_reports（applier 拒收），同信封合法项照落。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [
            {"origin_ref": "盘面自发", "account": "金库", "delta": -5, "reason": "非法账户"},
            {"origin_ref": "盘面自发", "account": "国库", "delta": -3, "reason": "合法"},
        ],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, ECO_REJ)
    assert len(rows) == 1, rows
    assert rows[0][2] == "invalid_enum", rows
    assert rows[0][1]


def test_top_level_nonint_delta_rejected(game):
    """顶层 economy_moves delta 非整数 → invalid_enum 逐项拒收。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [{"origin_ref": "盘面自发", "account": "国库", "delta": "很多", "reason": "坏 delta"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, ECO_REJ) if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows






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


def test_float_and_bool_delta_rejected(game):
    """delta 为 float/bool（int() 不抛但非合法整数 delta）→ invalid_enum 逐项拒收，不静默落账
    （与 faction/region/army _strict_int 同约，cmr r1 codex）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [
            {"origin_ref": "盘面自发", "account": "国库", "delta": 3.7, "reason": "float"},
            {"origin_ref": "盘面自发", "account": "国库", "delta": True, "reason": "bool"},
        ],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, ECO_REJ) if r[2] == "invalid_enum"]
    assert len(rows) == 2, rows




def test_issue_effect_cancel_economy_reaches_reports(game):
    """撤局势 applied_cost 的 economy 账户非法 → 拒收经 entity_rejections 达 rejection_reports
    （issue-effect 第二条路 cancel，sourcery r1 覆盖；与 close 路同 sink）。"""
    db, state, content = game
    turn = state.turn
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试撤局 economy 拒收", origin_kind="decree",
        origin_ref="", bar_value=50, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=0, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, effect_on_resolve={}, effect_on_fail={},
        resolve_condition="", fail_condition="", cancellable="decree", cancel_cost={},
    )
    db.conn.commit()

    run_settle(db, state, content, {
        "cancels": [{"issue_id": issue_id,
                     "applied_cost": {"economy": [{"account": "金库", "delta": -4, "reason": "非法"}]},
                     "narrative": "撤"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "issue_summary.entity_rejections")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows
