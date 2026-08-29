"""#1504：密令注入选择器只扫 active。

due_commitment ACK 仍走 augment → 待核议分组，不经 secret_orders 表 status。
"""
from __future__ import annotations

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


def test_select_only_active(game):
    db, state, _content = game
    db.conn.execute("DELETE FROM secret_orders")
    for i in range(5):
        _insert_order(db, state, f"active令{i}", "active")
    _insert_order(db, state, "已结令", "done", due_turn=0)
    db.conn.commit()

    sel = _select_secret_orders_for_sim(db, cap=20)
    assert all(o["status"] == "active" for o in sel)
    assert "已结令" not in [o["title"] for o in sel]


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


def test_due_commitment_ack_channel_untouched(game):
    """due_commitment 仍进「待核议」分组（承诺 ACK），不依赖 secret_orders.pending_review。"""
    db, state, _content = game
    grouped = group_secret_orders_for_sim([])
    out = augment_secret_orders_with_due_commitments(grouped, db, state)
    assert "在办" in out and "待核议" in out
    for item in out.get("待核议") or []:
        if item.get("entry_kind") == "due_commitment":
            assert "issue_id" in item
