"""S1 — ming_sim/applier.py 事务包裹 + commit 暂停（ADR 0008 决定 2/8）。

覆盖 atomic contextmanager 的原子语义：暂停期 commit 变 no-op、正常退出真 commit、
异常回滚 + 透传、嵌套 flat 语义、暂停期 rollback 仍生效、atomic 外一切照旧。

用 conftest 的 game fixture（活存档副本，持 db.conn，连接走 _SuspendableConnection factory）。
"""

from __future__ import annotations

import sqlite3

import pytest

from ming_sim.applier import atomic


def test_atomic_rolls_back_on_error(game):
    """atomic 内多次显式 commit 后人为抛错 → 全部写入回滚。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_probe'")
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_probe','a')")
            db.conn.commit()  # 暂停期：no-op
            db.conn.execute("UPDATE kv_store SET value='b' WHERE key='s1_probe'")
            db.conn.commit()  # 暂停期：no-op
            raise RuntimeError("boom")

    row = db.conn.execute("SELECT value FROM kv_store WHERE key='s1_probe'").fetchone()
    assert row is None  # 暂停期的 commit 没真提交，回滚把全部写入撤销


def test_atomic_normal_exit_commits_to_disk(game):
    """atomic 正常退出 → 写入已落盘（另开新连接读同一 db 文件验真 commit）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_commit'")
    db.conn.commit()

    with atomic(db):
        db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_commit','done')")

    other = sqlite3.connect(db.path)
    try:
        row = other.execute("SELECT value FROM kv_store WHERE key='s1_commit'").fetchone()
    finally:
        other.close()
    assert row is not None and row[0] == "done"


def test_atomic_suspends_internal_method_commit(game):
    """atomic 内调用自带 conn.commit() 的真实 GameDB 方法（kv_set，db.py:5402）→
    中途抛错 → 该方法的写入也回滚（验 79 处存量 commit 被透明暂停）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_method'")
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            db.kv_set("s1_method", "via_method")  # 内部有 self.conn.commit()
            raise RuntimeError("boom")

    assert db.kv_get("s1_method") is None  # kv_set 的写入随回滚消失


def test_nested_atomic_inner_commit_held_outer_rolls_back(game):
    """嵌套：内层正常退出不提交，外层抛错 → 内外写入全回滚（flat 语义）。"""
    db, state, content = game
    for k in ("s1_inner", "s1_outer"):
        db.conn.execute("DELETE FROM kv_store WHERE key=?", (k,))
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_outer','o')")
            with atomic(db):
                db.kv_set("s1_inner", "i")  # 内层正常退出，但不该提前 commit
            # 内层退出后外层仍在事务内，未落定
            assert db.conn.in_transaction
            raise RuntimeError("boom")

    assert db.kv_get("s1_inner") is None
    assert db.kv_get("s1_outer") is None


def test_nested_atomic_both_succeed_commits_once(game):
    """嵌套：内外层都正常退出 → 只在最外层落定一次，写入全部已提交。"""
    db, state, content = game
    for k in ("s1_n_inner", "s1_n_outer"):
        db.conn.execute("DELETE FROM kv_store WHERE key=?", (k,))
    db.conn.commit()

    with atomic(db):
        db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_n_outer','o')")
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_n_inner','i')")
            # 内层退出前仍在外层事务中
        assert db.conn.in_transaction  # 内层退出未落定，外层接着写

    other = sqlite3.connect(db.path)
    try:
        rows = dict(other.execute(
            "SELECT key,value FROM kv_store WHERE key IN ('s1_n_inner','s1_n_outer')"
        ).fetchall())
    finally:
        other.close()
    assert rows == {"s1_n_inner": "i", "s1_n_outer": "o"}


def test_rollback_still_works_during_suspension(game):
    """暂停期内显式 conn.rollback() 仍是真 rollback（暂停只拦 commit）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_rb'")
    db.conn.commit()

    with atomic(db):
        db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_rb','x')")
        db.conn.rollback()  # 暂停期：rollback 照常生效
        # 回滚后该行已无，atomic 正常退出 commit 空事务
        assert db.conn.execute(
            "SELECT value FROM kv_store WHERE key='s1_rb'"
        ).fetchone() is None

    assert db.kv_get("s1_rb") is None


def test_outside_atomic_commit_is_real(game):
    """非暂停期（atomic 外）一切照旧：commit 真提交（factory 不破常态）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_plain'")
    db.conn.commit()

    db.kv_set("s1_plain", "committed")  # atomic 外，内部 commit 应真生效

    other = sqlite3.connect(db.path)
    try:
        row = other.execute("SELECT value FROM kv_store WHERE key='s1_plain'").fetchone()
    finally:
        other.close()
    assert row is not None and row[0] == "committed"


def test_atomic_reraises_original_exception(game):
    """异常类型透传：atomic 不吞、不包裹，原异常对象原样冒出（ADR 0005 fail-loud）。"""
    db, state, content = game

    class _MyErr(Exception):
        pass

    sentinel = _MyErr("specific")
    with pytest.raises(_MyErr) as ei:
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_exc','x')")
            raise sentinel
    assert ei.value is sentinel
    # 回滚后写入不留
    assert db.kv_get("s1_exc") is None
    # 异常后连接干净，无悬挂事务
    assert not db.conn.in_transaction


def test_nested_atomic_inner_error_rolls_back_at_outer(game):
    """嵌套：内层抛错（depth>1，内层不回滚不解暂停），冒到外层（depth==1）统一回滚。"""
    db, state, content = game
    for k in ("s1_ie_outer", "s1_ie_inner"):
        db.conn.execute("DELETE FROM kv_store WHERE key=?", (k,))
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_ie_outer','o')")
            with atomic(db):
                db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_ie_inner','i')")
                raise RuntimeError("inner boom")

    assert db.kv_get("s1_ie_outer") is None
    assert db.kv_get("s1_ie_inner") is None
    # 暂停标志已在最外层解除，深度归零，连接可正常续用
    assert db.conn._commit_suspended is False
    assert db.conn._atomic_depth == 0
    db.kv_set("s1_ie_after", "ok")
    assert db.kv_get("s1_ie_after") == "ok"
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_ie_after'")
    db.conn.commit()
