"""S4 — pre_settle 自成事务 + settling 完成相位 + begin_turn 白名单（ADR 0008 决定 3 第二条）。

pre_settle（暂存动作 commit + 固定财政 + auto_trigger + auto_submit_due_secret_orders）
整体包成自己的单事务：完成时同事务内落中间相位 settling；崩在内部=全回滚=相位未变=
重进时干净重跑前半段。settling 加进 begin_turn 保活白名单，重载不被重置回 summoning。

用 conftest 的 game fixture（活存档副本，连接走 _SuspendableConnection factory，atomic 可用）。
"""

from __future__ import annotations

import sqlite3

import pytest

import ming_sim.decree as decree_mod
from ming_sim.decree import pre_settle


def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def test_crash_reload_at_settling_no_double_fiscal_tick(game):
    """pre_settle 完成（phase=settling 已落盘）→ 模拟崩溃重载（新开 GameDB 读盘）→
    重进 pre_settle 幂等守门直接 return，economy_ledger 不二次增行（ADR 0008 验收测试①）。"""
    from ming_sim.db import GameDB

    db, state, content = game
    turn = state.turn

    auto = pre_settle(state, db)
    assert isinstance(auto, list)
    assert state.turn_phase == "settling"
    after_first = _ledger_count(db, turn)
    assert after_first > 0  # 财政确已落
    db.conn.close()

    # 崩溃重载：新开 GameDB（落盘的 phase=settling 读回），重进 pre_settle 不重跑前半段。
    db2 = GameDB(db.path, content)
    try:
        state2 = db2.load_state()
        assert state2.turn_phase == "settling"  # 同事务落库，崩溃前已持久
        auto2 = pre_settle(state2, db2)
        assert auto2 == []  # 幂等守门：直接 return
        assert _ledger_count(db2, turn) == after_first  # 财政只落一次
    finally:
        db2.conn.close()


def test_settling_survives_begin_turn_phase_whitelist(game, monkeypatch):
    """phase=settling 重载走 begin_turn → 保活不被重置回 summoning（白名单生效，
    ADR 0008 S4；白名单外的相位重载即被重置，守门失效）。"""
    from ming_sim.session import GameSession, TurnPhase
    import ming_sim.session as session_mod

    db, state, content = game
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    # 用 __new__ 跳过重型 __init__（agno/registry/LLM），只装 begin_turn 需要的协作者；
    # 重型协作者打桩（registry 建 agent / auto_save / office 同步均与白名单无关）。
    monkeypatch.setattr(session_mod, "MinisterRegistry", lambda *a, **k: object())
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl", lambda *a, **k: None)
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    sess.llm_config = None
    sess.agno_db = None
    monkeypatch.setattr(GameSession, "auto_save", lambda self, tag: None)

    snap = sess.begin_turn()

    assert snap.phase == TurnPhase.SETTLING.value
    assert sess.state.turn_phase == TurnPhase.SETTLING.value
    # 落盘也仍是 settling（未被重置写回 summoning）
    assert db.load_state().turn_phase == TurnPhase.SETTLING.value


def test_due_secret_order_submission_rolls_back_on_pre_settle_crash(game, monkeypatch):
    """auto_submit_due_secret_orders 挪进 pre_settle 事务（ADR 0008 S4）：到期密令本应
    转 pending_review，但 pre_settle 内部崩溃 → 该状态翻转随事务回滚，order 仍是 active。"""
    db, state, content = game
    turn = state.turn
    # 让某 active 密令本回合到期（due_turn <= 当前 turn），auto_submit 应将其转 pending_review。
    db.conn.execute(
        "UPDATE secret_orders SET status='active', due_turn=? WHERE id=2", (turn,))
    db.conn.commit()
    assert db.conn.execute(
        "SELECT status FROM secret_orders WHERE id=2").fetchone()[0] == "active"

    # 在 auto_submit 之后的相位写处崩：用 save_state 抛错，验前面 auto_submit 的写回滚。
    orig_save = db.save_state
    def _boom_save(st):
        raise RuntimeError("phase-write boom")
    monkeypatch.setattr(db, "save_state", _boom_save)

    with pytest.raises(RuntimeError, match="phase-write boom"):
        pre_settle(state, db)

    monkeypatch.setattr(db, "save_state", orig_save)
    # 用新连接读盘：密令呈递随事务整体回滚，仍是 active（没有事务外散写）。
    other = sqlite3.connect(db.path)
    try:
        st = other.execute("SELECT status FROM secret_orders WHERE id=2").fetchone()[0]
    finally:
        other.close()
    assert st == "active"


def test_driver_pre_settle_same_transaction_semantics(game, monkeypatch):
    """driver 路径（直接调 pre_settle）同样获得自事务语义：内部崩溃 → 财政回滚、phase 未推进
    （ADR 0004/0008，driver 与真实流程同核同位）。"""
    import ming_sim.decree as dm
    db, state, content = game
    turn = state.turn
    before_phase = state.turn_phase
    before_ledger = _ledger_count(db, turn)

    def _boom(*a, **k):
        raise RuntimeError("driver pre_settle boom")
    monkeypatch.setattr(dm, "auto_trigger_seed_issues", _boom)

    # driver.run_settle 内部第一步即 pre_settle；这里直接调 pre_settle 等价（同函数同核）。
    with pytest.raises(RuntimeError, match="driver pre_settle boom"):
        pre_settle(state, db)

    other = sqlite3.connect(db.path)
    try:
        on_disk = other.execute(
            "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    finally:
        other.close()
    assert on_disk == before_ledger
    assert state.turn_phase == before_phase != "settling"
    assert not db.conn.in_transaction


def test_crash_inside_pre_settle_no_missing_fiscal(game, monkeypatch):
    """pre_settle 内部注入异常（auto_trigger 抛）→ 异常透传、economy_ledger 无半行、
    phase 仍是入口态（非 settling）——整体回滚干净（ADR 0008 验收测试②）。"""
    db, state, content = game
    turn = state.turn
    before_phase = state.turn_phase
    before_ledger = _ledger_count(db, turn)

    # auto_trigger_seed_issues 在固定财政落账之后调；让它抛，验前面已落的财政被回滚。
    def _boom(*a, **k):
        raise RuntimeError("auto_trigger boom")
    monkeypatch.setattr(decree_mod, "auto_trigger_seed_issues", _boom)

    with pytest.raises(RuntimeError, match="auto_trigger boom"):
        pre_settle(state, db)

    # 财政落账随回滚消失（用新连接读盘，验真回滚到磁盘态）
    other = sqlite3.connect(db.path)
    try:
        on_disk = other.execute(
            "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
        ).fetchone()[0]
    finally:
        other.close()
    assert on_disk == before_ledger
    # 内存 phase 未推进到 settling（pre_settle 尾部才写，异常在此前）
    assert state.turn_phase == before_phase
    assert state.turn_phase != "settling"
    # 连接干净，无悬挂事务
    assert not db.conn.in_transaction


# ---------------------------------------------------------------------------
# cmr S4 r1 修复回归（F1 settling 复位 / F2 sticky / F3 skip 路守门）
# ---------------------------------------------------------------------------

def test_two_consecutive_driver_settles_both_get_fiscal_tick(game):
    """driver 连续结算两回合，第二回合财政照常落账（cmr S4 r1 F1，3/3 critical）。

    settling 推进回合后不复位的话，第二回合 pre_settle 被守门跳过=
    此后每月财政/暂存/密令全静默丢。
    """
    from driver import run_settle
    db, state, content = game
    t1 = state.turn
    run_settle(db, state, content, {})
    t2 = state.turn
    assert t2 == t1 + 1
    assert state.turn_phase != "settling"  # 推进后复位

    run_settle(db, state, content, {})
    assert state.turn == t2 + 1
    rows_t2 = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (t2,)).fetchone()[0]
    assert rows_t2 > 0  # 第二回合财政 tick 真跑了


def test_enter_review_does_not_clobber_settling(game):
    """enter_review 不得抹掉崩溃保活的 settling（cmr S4 r1 F2）。

    抹成 reviewing 后 pre_settle 守门失效=同回合二次财政 tick。
    """
    from ming_sim.session import GameSession, TurnPhase
    db, state, content = game
    state.turn_phase = "settling"
    db.save_state(state)

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state

    sess.enter_review()
    assert state.turn_phase == "settling"

    sess.back_to_summoning()
    assert state.turn_phase == "settling"


def test_advance_without_edict_after_settling_no_double_tick(game):
    """崩溃重载后走 skip 路：前半段已提交则不二跑财政，且复位 phase（cmr S4 r1 F3）。"""
    from ming_sim.decree import advance_without_edict, pre_settle
    db, state, content = game
    turn = state.turn
    pre_settle(state, db)  # 真跑：落财政 + settling
    rows_after_pre = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    assert rows_after_pre > 0
    assert state.turn_phase == "settling"

    advance_without_edict(state, db, content=content)

    rows_final = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    assert rows_final == rows_after_pre  # 不二跑
    assert state.turn == turn + 1
    assert state.turn_phase != "settling"  # 推进后复位
