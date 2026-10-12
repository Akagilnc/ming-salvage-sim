from __future__ import annotations
"""economy_moves 段迁入逐项拒收契约（ADR 0008 决定 1，#14 economy 残留 / ADR 0012）。

原先 `_clean_economy_moves`（cleaner，pre-apply）与 `_apply_economy_list`（applier）对
非法 account（∉国库/内库）/非整数 delta（含 bool/float）都 `continue` 静默丢、零拒收留痕
（#14 模式 A/C）。改为：统一在 applier 逐项拒收（invalid_enum），cleaner 不再丢、透传坏项
给 apply 拒收；delta==0/缺额 仍按 no-op 静默跳。拒收由 SectionResult.rejected 交给框架写入 rejection_reports。

从现役原子声明入口验证 applier 的拒收契约。
"""


from functools import partial
import json

import pytest

from tests.section_rejection_helpers import run_declaration as run_settle
from tests.section_rejection_helpers import game, rejection_rows

ECO_REJ = "economy_moves"


_rejection_rows = partial(rejection_rows, columns="section, reason, category")


def _guoku(db):
    return db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger WHERE account='国库'").fetchone()[0]


@pytest.mark.parametrize("bad_items", [
    [{"account": "金库", "delta": -5}],
    [{"account": "国库", "delta": "很多"}],
    [{"account": "国库", "delta": 3.7}, {"account": "国库", "delta": True}],
])
def test_economy_refusal_keeps_valid_sibling(game, bad_items):
    db, state, content = game
    from ming_sim.decree import pre_settle
    pre_settle(state, db, content=content)
    before = _guoku(db)
    items = [{**item, "origin_ref": "盘面自发", "reason": "坏项"} for item in bad_items]
    items.append({"origin_ref": "盘面自发", "account": "国库", "delta": 3, "reason": "好项"})
    run_settle(db, state, content, {"economy_moves": items})
    rows = _rejection_rows(db, state.turn, ECO_REJ)
    assert len(rows) == len(bad_items)
    assert all(row["category"] == "invalid_enum" and row["reason"] for row in rows)
    assert _guoku(db) == before + 3


def test_valid_economy_still_applies_no_reject(saved_game):
    """合法 economy 照常落账、零拒收（不误伤）。
    用 saved_game：断言依赖玩过存档的国库余额基线，fresh seed 不复现（#5）。"""
    db, state, content = saved_game
    turn = state.turn
    before = _guoku(db)

    run_settle(db, state, content, {
        "economy_moves": [{"origin_ref": "盘面自发", "account": "国库", "delta": -7, "reason": "正常"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, ECO_REJ) == []
    assert _guoku(db) < before  # 确实扣账


def test_zero_delta_economy_no_reject_no_apply(game):
    """delta==0 是 no-op，不拒收也不落账（不误报）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [{"origin_ref": "盘面自发", "account": "国库", "delta": 0, "reason": "空动作"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, ECO_REJ) == []


def test_issue_effect_bad_account_economy_reaches_reports(game):
    """局势 effect_on_resolve 的 economy 账户非法 → 拒收经 issue_summary.rejected 达
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
        cancellable="decree",
    )
    db.conn.commit()

    run_settle(db, state, content, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "issue_summary")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows


def test_noop_bad_account_skipped_not_rejected(game):
    """no-op 空占位行（delta==0/缺额）即便 account 空/非法也静默跳，不拒收（免噪声+假提示，
    codex r1 线上）；只有真有钱动（delta≠0）的非法 account 才拒。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [
            {"origin_ref": "盘面自发", "account": "金库", "delta": 0, "reason": "空占位非法账户"},  # no-op → 跳
            {"origin_ref": "盘面自发", "account": "", "reason": "缺 delta 空账户"},                # no-op → 跳
        ],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, ECO_REJ) == []


def test_issue_effect_cancel_economy_reaches_reports(game):
    """Cancel refusals retain each bad reference/cost without losing valid siblings."""
    db, state, content = game
    turn = state.turn
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试撤局 economy 拒收", origin_kind="decree",
        origin_ref="", bar_value=50, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=0, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, effect_on_resolve={}, effect_on_fail={},
        resolve_condition="", fail_condition="", cancellable="decree",
    )
    inactive_ids = {}
    for status in ("resolved", "failed", "dropped"):
        inactive_id = db.insert_issue(state, kind="initiative", title=status,
                                      cancellable="decree")
        db.issues.update(inactive_id, {"status": status})
        inactive_ids[inactive_id] = status
    db.conn.commit()

    invalid_refs = [{"issue_id": value} for value in
                    ("oops", None, True, False, 1.5, float(issue_id), 10**100, -(10**100))]
    invalid_refs.append({})
    missing_refs = [{"issue_id": -1}, *({"issue_id": i} for i in inactive_ids)]
    result = run_settle(db, state, content, {
        "metric_delta": {"皇威": 1},
        "cancels": [*invalid_refs, *missing_refs,
                    {"issue_id": str(issue_id),
                     "applied_cost": {"economy": [{"account": "金库", "delta": -4, "reason": "非法"}]},
                     "narrative": "撤"}],
    }, narrative="x", decree_text="y")

    outcome = result.effects.applied[0]
    assert outcome.metric.applied == [("皇威", 1)]
    assert [item["issue_id"] for item in outcome.issue.cancels] == [issue_id]
    assert db.issues.row(issue_id)["status"] == "dropped"
    assert {i: db.issues.row(i)["status"] for i in inactive_ids} == inactive_ids

    rows = rejection_rows(db, turn, "issue_summary",
                          columns="item_json, reason, category, source")
    assert len(rows) == len(invalid_refs) + len(missing_refs) + 1
    expected_refs = [(item, "invalid_enum") for item in invalid_refs]
    expected_refs += [(item, "missing_ref") for item in missing_refs]
    for row, (item, category) in zip(rows, expected_refs):
        assert json.loads(row["item_json"]) == item
        assert row["category"] == category
    assert rows[-1]["category"] == "invalid_enum"  # The existing bad-cost refusal.
    assert all(row["reason"] and row["source"] == "player_decree" for row in rows)
    assert len(outcome.issue.rejected) == len(rows)
