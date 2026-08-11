"""economy_moves 段迁入逐项拒收契约（ADR 0008 决定 1，#14 economy 残留 / ADR 0012）。

原先 `_clean_economy_moves`（cleaner，pre-apply）与 `_apply_economy_list`（applier）对
非法 account（∉国库/内库）/非整数 delta（含 bool/float）都 `continue` 静默丢、零拒收留痕
（#14 模式 A/C）。改为：统一在 applier 逐项拒收（invalid_enum），cleaner 不再丢、透传坏项
给 apply 拒收；delta==0/缺额 仍按 no-op 静默跳。顶层拒收落独立 economy_moves_rejections 段
（不污染玩家可见 economy_moves list、_player_visible pop）；issue-effect 路 economy 拒收经
entity/inertia sink 达 rejection_reports，不蒸发。

注：driver.run_settle 走 canonicalize_extraction（不调 cleaner）→ 这些端到端测试覆盖
**applier 拒收**；cleaner（_sanitize_module_output 路）的透传由 test_clean_economy_moves_*
直接单测覆盖（cmr r1 claude）。
"""

from __future__ import annotations

from functools import partial

from driver import run_settle
from tests.section_rejection_helpers import game, rejection_rows

ECO_REJ = "economy_moves_rejections"


_rejection_rows = partial(rejection_rows, columns="section, reason, category")


def _guoku(db):
    return db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger WHERE account='国库'").fetchone()[0]


def test_top_level_bad_account_rejected_good_lands(game):
    """顶层 economy_moves 账户非法 → invalid_enum 逐项拒收达 rejection_reports（applier 拒收；cleaner 透传由单测另覆盖），同信封合法项照落。"""
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


def test_economy_rejections_not_in_player_visible(game):
    """拒收项不进玩家可见 extractor_output（P4，cmr r1 codex）：economy_moves 段无 rejected 项、
    无 economy_moves_rejections 段。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "economy_moves": [{"origin_ref": "盘面自发", "account": "金库", "delta": -5, "reason": "非法"},
                          {"origin_ref": "盘面自发", "account": "国库", "delta": -3, "reason": "合法"}],
    }, narrative="x", decree_text="y")

    visible = db.get_turn_extraction(turn)["extractor_output"]
    em = visible.get("economy_moves") or []
    assert not any(isinstance(x, dict) and x.get("rejected") for x in em), em
    assert "economy_moves_rejections" not in visible


# ── cleaner（_sanitize_module_output 路）透传单测（cmr r1 claude：run_settle 不走 cleaner）──

def test_clean_economy_moves_passes_bad_through():
    """_clean_economy_moves 不再静默丢坏 account / 非整数 delta（含 bool/float）——透传给 apply
    拒收（#14）。合法项规范化保留；delta==0 / 缺 delta = no-op 仍跳。"""
    from ming_sim.simulation import _clean_economy_moves
    out = _clean_economy_moves([
        {"account": "金库", "delta": -5, "reason": "坏账户"},      # 透传
        {"account": "国库", "delta": "很多", "reason": "坏串"},     # 透传
        {"account": "国库", "delta": 3.7, "reason": "float"},      # 透传
        {"account": "国库", "delta": True, "reason": "bool"},      # 透传
        {"account": "国库", "delta": -7, "reason": "合法"},        # 保留(规范化)
        {"account": "国库", "delta": 0, "reason": "no-op"},        # 跳
        {"account": "国库", "reason": "缺delta"},                  # 跳(no-op)
    ])
    accounts = [str(x.get("account")) for x in out]
    # 4 个坏项透传 + 1 合法 = 5；2 个 no-op 跳
    assert len(out) == 5, out
    assert "金库" in accounts            # 坏账户透传(非静默丢)
    assert sum(1 for x in out if x.get("account") == "国库") == 4
    # 合法项规范化后 delta 为 int
    legit = [x for x in out if x.get("reason") == "合法"]
    assert legit and legit[0]["delta"] == -7


def test_clean_economy_moves_non_list_returns_empty():
    from ming_sim.simulation import _clean_economy_moves
    assert _clean_economy_moves("x") == []
    assert _clean_economy_moves(None) == []
