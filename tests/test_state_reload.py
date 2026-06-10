"""S5 — 内存态与 DB 同源恢复（ADR 0008 决定 3 第三条）。

DB 回滚不还原内存副作用（state.metrics 直加 flows.py:192、turn_phase、next_period）。
回滚后重跑前把 state 从 DB 重载（与 restore/load_state 同路径），原地刷新同一对象
（各处持引用，不能换新对象）。
"""

from __future__ import annotations

import sqlite3

import pytest

import ming_sim.decree as decree_mod
from ming_sim.decree import pre_settle, reload_state_from_db


def test_reload_refreshes_state_in_place(game):
    """DB 改值后调 reload → state 字段被刷成 DB 值，且仍是同一对象（id 不变）。"""
    db, state, content = game
    state_id_before = id(state)

    # 制造内存/DB 分歧：直接改 DB 的相位与某 metric，不动内存 state。
    db.conn.execute("UPDATE game_state SET turn_phase='reviewing' WHERE id=1")
    db.conn.execute("UPDATE metrics SET value=7 WHERE key='皇威'")
    db.conn.commit()
    # 内存仍是旧值
    assert state.turn_phase != "reviewing"
    assert state.metrics["皇威"] != 7

    returned = reload_state_from_db(db, state)

    # 原地刷新：同一对象、字段已是 DB 值。
    assert id(state) == state_id_before
    assert returned is state
    assert state.turn_phase == "reviewing"
    assert state.metrics["皇威"] == 7


def test_reload_scrubs_next_period_advance(game):
    """reload 刷掉 next_period 的内存推进（turn/year/period）——DB 回滚不还原它们（ADR 0008 决定 3）。"""
    db, state, content = game
    db_turn = state.turn
    db_year, db_period = state.year, state.period

    state.next_period()  # 内存推进，未落盘
    assert state.turn == db_turn + 1

    reload_state_from_db(db, state)

    assert state.turn == db_turn
    assert state.year == db_year and state.period == db_period


def test_reload_passthrough_content_registry_no_crash(game):
    """content/registry 非 None 时本切片只透传不处理（占位待 S7），不报错、state 仍刷新。"""
    db, state, content = game
    db.conn.execute("UPDATE game_state SET turn_phase='reviewing' WHERE id=1")
    db.conn.commit()

    returned = reload_state_from_db(db, state, content=content, registry=object())

    assert returned is state
    assert state.turn_phase == "reviewing"


def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def test_reload_scrubs_dirty_settling_phase(game):
    """reload 单元：手工造脏 settling 相位（DB 是旧相位）→ reload 刷回 DB 真相（非 settling）。

    伤口本质：dirty settling 会被 pre_settle 守门跳过=整月财政丢；reload 是解药。
    """
    db, state, content = game
    db_phase = db.conn.execute(
        "SELECT turn_phase FROM game_state WHERE id=1").fetchone()[0]
    assert db_phase != "settling"

    state.turn_phase = "settling"  # 模拟 save_state 崩前已被赋的脏相位

    reload_state_from_db(db, state)

    assert state.turn_phase == db_phase != "settling"


def test_pre_settle_self_reloads_memory_on_rollback(game, monkeypatch):
    """pre_settle 内任一步抛错 → atomic 回滚后 pre_settle 自己 reload 刷净内存（调用方不必手动 reload）
    → 异常仍透传 → 再调 pre_settle 能完整跑（不被脏相位守门跳过）。脏读防线钉死（ADR 0008 决定 3 第三条）。"""
    db, state, content = game
    turn = state.turn
    before_phase = state.turn_phase
    before_metrics = dict(state.metrics)
    before_ledger = _ledger_count(db, turn)

    # save_state 抛错：此时内存 phase 已被赋成 settling、apply_fixed_period_flows 已直改 state.metrics。
    def _boom_save(st):
        raise RuntimeError("save boom")

    monkeypatch.setattr(db, "save_state", _boom_save)

    with pytest.raises(RuntimeError, match="save boom"):
        pre_settle(state, db)

    # pre_settle 已在回滚后自我 reload：内存与 DB 同源（phase 非 settling、metrics 回到回滚态）。
    assert state.turn_phase == before_phase != "settling"
    on_disk_phase = sqlite3.connect(db.path).execute(
        "SELECT turn_phase FROM game_state WHERE id=1").fetchone()[0]
    assert state.turn_phase == on_disk_phase
    # metrics 与 DB 同源：财政副作用随回滚消失，内存被刷回。
    assert state.metrics == before_metrics
    assert _ledger_count(db, turn) == before_ledger

    # 再调 pre_settle（恢复 save_state）能完整跑、不被脏相位跳过。
    monkeypatch.setattr(db, "save_state", db.__class__.save_state.__get__(db))
    pre_settle(state, db)
    assert state.turn_phase == "settling"
    assert _ledger_count(db, turn) > before_ledger
