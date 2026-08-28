"""secret_order 段拒收补精确 category（ADR 0008 决定 1 逐项拒收契约统一，#14 C2）。

updates 数据校验类拒收带精确 category（未知 order_id → missing_ref，坏值/非 active → invalid_enum）。

只覆盖 LLM 数据校验类拒收；落库真异常（except）的拒收不在此（属 #63.4 设计待定，不动）。
经 driver.run_settle 端到端查 rejection_reports。
"""

from __future__ import annotations

from functools import partial

from tests.section_rejection_helpers import prepare_then_settle as run_settle
from ming_sim import issues
from tests.section_rejection_helpers import game, rejection_rows


_rejection_rows = partial(rejection_rows, columns="section, reason, category")


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


def test_update_valid_active_order_applies_no_reject(game):
    """正向守门（cmr r2 claude）：合法 active 密令 update 不被新 get_secret_order gate 误拒，
    sim_note 真写入、零拒收行。"""
    db, state, content = game
    turn = state.turn
    oid = db.create_secret_order(
        state,
        "测试密令官",
        "合法更新正向守门",
        "先建 active 密令，再验证推演更新真实落库。",
        [],
        deadline_months=1,
    )

    run_settle(db, state, content, {
        "secret_order_updates": [{"order_id": oid, "sim_note": "推演副作用XYZ"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "secret_order_updates") == []
    assert "推演副作用XYZ" in (db.get_secret_order(oid)["sim_note"] or "")


def test_apply_score_extraction_secret_order_update_respects_outer_transaction_rollback(game):
    """post-merge CMR R8：secret_order_updates 不得绕过外层事务硬提交。"""
    db, state, content = game
    oid = db.create_secret_order(state, "测试密令官R8", "测试密令", "测试内容", [], deadline_months=1)
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_score_extraction(
        db,
        state,
        {"secret_order_updates": [{"order_id": oid, "sim_note": "测试密令副作用R8"}]},
        content=content,
    )
    assert out["secret_order_updates"][0]["order_id"] == oid
    in_tx = db.get_secret_order(oid)
    assert in_tx is not None
    assert "测试密令副作用R8" in (in_tx["sim_note"] or "")
    db.conn.rollback()

    row = db.get_secret_order(oid)
    assert row is not None
    assert "测试密令副作用R8" not in (row["sim_note"] or "")


def test_oversized_order_id_rejected_not_crash(game):
    """超 SQLite 64-bit 范围的 order_id（int() 不抛但 get_secret_order 绑定会 OverflowError）
    → invalid_enum 逐项拒收，不崩整月结算（#63.5；cmr r2 codex）。"""
    db, state, content = game
    turn = state.turn
    huge = 10 ** 100

    run_settle(db, state, content, {
        "secret_order_updates": [{"order_id": huge, "sim_note": "超界 id"}],
    }, narrative="x", decree_text="y")

    up = [r for r in _rejection_rows(db, turn, "secret_order_updates") if r[2] == "invalid_enum"]
    assert len(up) == 1, up
