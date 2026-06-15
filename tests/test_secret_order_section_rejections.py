"""secret_order 段拒收补精确 category（ADR 0008 决定 1 逐项拒收契约统一，#14 C2）。

secret_order_closes 早已逐项拒收（含未知 order_id「密令不存在」）、updates 此前对未知/非
active id 静默报成功（cmr r1 codex 抓出，#14 silent-success）。本组把两段数据校验类拒收
统一带精确 category（未知 order_id → missing_ref，坏值/坏状态/非 active → invalid_enum），
并补 updates 的未知 id 拒收（对齐 closes）。

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


def test_update_unknown_order_id_missing_ref(game):
    """secret_order_updates 引用不存在的整数 order_id → missing_ref 拒收达 rejection_reports
    （此前静默报「已应用」无留痕，cmr r1 codex，#14 silent-success）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "secret_order_updates": [
            {"order_id": 999999, "sim_note": "查无此密令的副作用"},
        ],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "secret_order_updates")
    assert len(rows) == 1, rows
    assert rows[0][2] == "missing_ref", rows


def _active_order_id(db):
    row = db.conn.execute(
        "SELECT id FROM secret_orders WHERE status='active' ORDER BY id LIMIT 1").fetchone()
    return row[0] if row else None


def test_update_valid_active_order_applies_no_reject(game):
    """正向守门（cmr r2 claude）：合法 active 密令 update 不被新 get_secret_order gate 误拒，
    sim_note 真写入、零拒收行。"""
    db, state, content = game
    turn = state.turn
    oid = _active_order_id(db)
    if oid is None:
        import pytest
        pytest.skip("基底无 active 密令")

    run_settle(db, state, content, {
        "secret_order_updates": [{"order_id": oid, "sim_note": "推演副作用XYZ"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "secret_order_updates") == []
    assert "推演副作用XYZ" in (db.get_secret_order(oid)["sim_note"] or "")


def test_oversized_order_id_rejected_not_crash(game):
    """超 SQLite 64-bit 范围的 order_id（int() 不抛但 get_secret_order 绑定会 OverflowError）
    → invalid_enum 逐项拒收，不崩整月结算（#63.5；cmr r2 codex）。updates + closes 都覆盖。"""
    db, state, content = game
    turn = state.turn
    huge = 10 ** 100

    run_settle(db, state, content, {
        "secret_order_updates": [{"order_id": huge, "sim_note": "超界 id"}],
        "secret_order_closes": [{"order_id": huge, "status": "done", "result": "超界 id"}],
    }, narrative="x", decree_text="y")

    up = [r for r in _rejection_rows(db, turn, "secret_order_updates") if r[2] == "invalid_enum"]
    cl = [r for r in _rejection_rows(db, turn, "secret_order_closes") if r[2] == "invalid_enum"]
    assert len(up) == 1, up
    assert len(cl) == 1, cl
