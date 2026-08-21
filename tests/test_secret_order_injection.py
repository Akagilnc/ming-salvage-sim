"""#1504：密令注入选择器只扫 active；legacy pending_review 由开库一次迁移消化。

due_commitment ACK 仍走 augment → 待核议分组，不经 secret_orders 表 status。
"""
from __future__ import annotations

from ming_sim.db import GameDB
from ming_sim.decree import _select_secret_orders_for_sim
from ming_sim.settlement_payload import (
    augment_secret_orders_with_due_commitments,
    group_secret_orders_for_sim,
)


def _insert_order(db, state, title, status, *, due_turn=0):
    db.conn.execute(
        "INSERT INTO secret_orders (turn_issued,due_turn,year_issued,period_issued,"
        "minister_name,title,content,tags,importance,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (state.turn, int(due_turn), state.year, state.period, "测试臣", title, "x", "[]", 4, status),
    )


def test_select_only_active_after_migration(game):
    """选择器不再长期并行保 pending_review；开库迁移后只见 active。"""
    db, state, content = game
    db.conn.execute("DELETE FROM secret_orders")
    for i in range(5):
        _insert_order(db, state, f"active令{i}", "active")
    _insert_order(db, state, "旧待核议", "pending_review", due_turn=0)
    db.conn.commit()

    # 同连接未再跑 open 迁移：手动调用一次确定迁移
    db._migrate_legacy_pending_review_secret_orders()
    db.conn.commit()

    row = db.conn.execute(
        "SELECT status, due_turn, result FROM secret_orders WHERE title=?",
        ("旧待核议",),
    ).fetchone()
    assert row["status"] == "active"
    assert int(row["due_turn"]) > 0
    assert "[到期迁移]" in (row["result"] or "")

    sel = _select_secret_orders_for_sim(db, cap=20)
    assert all(o["status"] == "active" for o in sel)
    assert "旧待核议" in [o["title"] for o in sel]


def test_active_capped(game):
    """active 受 cap 限制（payload 预算不破）。"""
    db, state, _content = game
    db.conn.execute("DELETE FROM secret_orders")
    for i in range(25):
        _insert_order(db, state, f"active令{i}", "active")
    db.conn.commit()
    sel = _select_secret_orders_for_sim(db, cap=20)
    assert len(sel) == 20
    assert all(o["status"] == "active" for o in sel)


def test_reopen_migrates_pending_review_due_zero(game):
    """重开 GameDB：due_turn=0 的 pending_review 迁 active 并得未来实况窗（不立即 due）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM secret_orders")
    _insert_order(db, state, "零期核议", "pending_review", due_turn=0)
    db.conn.commit()
    path = db.path
    db.close()

    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        row = db2.conn.execute(
            "SELECT status, due_turn FROM secret_orders WHERE title=?",
            ("零期核议",),
        ).fetchone()
        assert row["status"] == "active"
        assert int(row["due_turn"]) > 0
        # 尚缺 target 时给未来窗，禁止 due<=current 空实况即死
        assert int(row["due_turn"]) > int(state2.turn)
    finally:
        db2.close()


def test_due_commitment_ack_channel_untouched(game):
    """due_commitment 仍进「待核议」分组（承诺 ACK），不依赖 secret_orders.pending_review。"""
    db, state, _content = game
    # 无密令时 augment 仍应返回分组结构
    grouped = group_secret_orders_for_sim([])
    out = augment_secret_orders_with_due_commitments(grouped, db, state)
    assert "在办" in out and "待核议" in out
    # 条目若有，必须带 entry_kind
    for item in out.get("待核议") or []:
        if item.get("entry_kind") == "due_commitment":
            assert "issue_id" in item
