"""secret_order 段拒收补精确 category（ADR 0008 决定 1 逐项拒收契约统一，#14 C2）。

secret_order_updates/closes 早已逐项拒收（含未知 order_id「密令不存在」），但拒收项无
`category` 键 → 桥接 _collect_inline_rejections 兜底记成 legacy_inline，与已迁 section
（region/army/power/faction/class 的 missing_ref/invalid_enum）不一致。本组验数据校验类拒收
带上精确 category（未知 order_id → missing_ref，坏值/坏状态 → invalid_enum）。

只覆盖 LLM 数据校验类拒收；落库真异常（except）的拒收不在此（属 #63.4 设计待定，不动）。
经 driver.run_settle 端到端查 rejection_reports。
"""

from __future__ import annotations

from driver import run_settle


def _rejection_rows(db, turn, section):
    return db.conn.execute(
        "SELECT section, reason, category FROM rejection_reports"
        " WHERE turn=? AND section=? ORDER BY id", (turn, section)
    ).fetchall()


def test_close_unknown_order_id_missing_ref(game):
    """secret_order_closes 引用不存在的 order_id → missing_ref 拒收达 rejection_reports
    （不再兜底 legacy_inline）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "secret_order_closes": [
            {"order_id": 999999, "status": "done", "result": "查无此密令"},
        ],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "secret_order_closes")
    assert len(rows) == 1, rows
    assert rows[0][2] == "missing_ref", rows
    assert rows[0][1]  # 人读原因非空


def test_close_nonint_order_id_invalid_enum(game):
    """secret_order_closes order_id 非整数 → invalid_enum 拒收达 rejection_reports。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "secret_order_closes": [
            {"order_id": "甲", "status": "done", "result": "坏 id"},
        ],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "secret_order_closes")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows


def test_close_bad_status_invalid_enum(game):
    """secret_order_closes status 非 done/failed → invalid_enum 拒收。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "secret_order_closes": [
            {"order_id": 1, "status": "搁置", "result": "非法状态"},
        ],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "secret_order_closes")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows


def test_update_nonint_order_id_invalid_enum(game):
    """secret_order_updates order_id 非整数 → invalid_enum 拒收达 rejection_reports。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "secret_order_updates": [
            {"order_id": "乙", "sim_note": "坏 id 副作用"},
        ],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "secret_order_updates")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows
