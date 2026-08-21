"""#108 保留：legacy pending_review 注入不被满载 active 截断（#1504 迁移窗仍全保）。

#1504 后不再新产 pending_review 作结案链；选择器仍全保遗留 pending + active 填 cap。
"""
from __future__ import annotations

from ming_sim.decree import _select_secret_orders_for_sim


def _insert_order(db, state, title, status):
    db.conn.execute(
        "INSERT INTO secret_orders (turn_issued,due_turn,year_issued,period_issued,"
        "minister_name,title,content,tags,importance,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (state.turn, 0, state.year, state.period, "测试臣", title, "x", "[]", 4, status))


def test_pending_review_not_starved_by_full_active(game):
    """20 条 active（满载）+ 1 条 pending_review → pending_review 仍进推演（#108）。"""
    db, state, _content = game
    db.conn.execute("DELETE FROM secret_orders")  # 临时库，清净构造满载场景
    for i in range(20):
        _insert_order(db, state, f"active令{i}", "active")
    _insert_order(db, state, "待核议令甲", "pending_review")
    db.conn.commit()
    sel = _select_secret_orders_for_sim(db, cap=20)
    titles = [o["title"] for o in sel]
    assert "待核议令甲" in titles, "pending_review 被满载 active 饿死（#108）"
    assert sum(1 for o in sel if o["status"] == "pending_review") == 1


def test_all_pending_review_kept_even_over_cap(game):
    """pending_review 超 cap 也全保（本回合都须核议，绝不截断）。"""
    db, state, _content = game
    db.conn.execute("DELETE FROM secret_orders")
    for i in range(22):
        _insert_order(db, state, f"待核议令{i}", "pending_review")
    db.conn.commit()
    sel = _select_secret_orders_for_sim(db, cap=20)
    assert sum(1 for o in sel if o["status"] == "pending_review") == 22


def test_active_capped_when_no_pending(game):
    """无 pending 时 active 仍受 cap 限制（payload 预算不破）。"""
    db, state, _content = game
    db.conn.execute("DELETE FROM secret_orders")
    for i in range(25):
        _insert_order(db, state, f"active令{i}", "active")
    db.conn.commit()
    sel = _select_secret_orders_for_sim(db, cap=20)
    assert len(sel) == 20


def test_active_fills_remaining_budget_after_pending(game):
    """pending 占预算后 active 填满剩余：5 pending + 20 active, cap=20 → 5 pending + 15 active = 20。"""
    db, state, _content = game
    db.conn.execute("DELETE FROM secret_orders")
    for i in range(20):
        _insert_order(db, state, f"active令{i}", "active")
    for i in range(5):
        _insert_order(db, state, f"待核议令{i}", "pending_review")
    db.conn.commit()
    sel = _select_secret_orders_for_sim(db, cap=20)
    assert sum(1 for o in sel if o["status"] == "pending_review") == 5  # pending 全进
    assert sum(1 for o in sel if o["status"] == "active") == 15        # active 填满剩余
    assert len(sel) == 20                                              # 预算不破
