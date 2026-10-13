from __future__ import annotations
import sqlite3
import pytest
from ming_sim.applier import atomic, connection_owns_transaction
"""S1 — ming_sim/applier.py 事务包裹 + commit 暂停（ADR 0008 决定 2/8）。

覆盖 atomic contextmanager 的原子语义：暂停期 commit 变 no-op、正常退出真 commit、
异常回滚 + 透传、嵌套 flat 语义、暂停期 rollback 仍生效、atomic 外一切照旧。

用 conftest 的 game fixture（活存档副本，持 db.conn，连接走 _SuspendableConnection factory）。
"""






def _fiscal_config_value(db, key: str) -> int:
    row = db.conn.execute(
        "SELECT value FROM fiscal_config WHERE key = ?",
        (key,),
    ).fetchone()
    assert row is not None
    return int(row["value"])


def test_transaction_ownership_tracks_atomic_and_open_transactions(game):
    db, state, content = game
    assert connection_owns_transaction(db.conn) is True

    with atomic(db):
        assert connection_owns_transaction(db.conn) is False

    assert connection_owns_transaction(db.conn) is True
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_owns_tx'")
    db.conn.commit()
    db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_owns_tx','open')")
    try:
        assert connection_owns_transaction(db.conn) is False
    finally:
        db.conn.rollback()


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
            db.reign.kv_set("s1_method", "via_method")  # 内部有 self.conn.commit()
            raise RuntimeError("boom")

    assert db.reign.kv_get("s1_method") is None  # kv_set 的写入随回滚消失


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
                db.reign.kv_set("s1_inner", "i")  # 内层正常退出，但不该提前 commit
            # 内层退出后外层仍在事务内，未落定
            assert db.conn.in_transaction
            raise RuntimeError("boom")

    assert db.reign.kv_get("s1_inner") is None
    assert db.reign.kv_get("s1_outer") is None


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

    assert db.reign.kv_get("s1_rb") is None


def test_outside_atomic_commit_is_real(game):
    """非暂停期（atomic 外）一切照旧：commit 真提交（factory 不破常态）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_plain'")
    db.conn.commit()

    db.reign.kv_set("s1_plain", "committed")  # atomic 外，内部 commit 应真生效

    other = sqlite3.connect(db.path)
    try:
        row = other.execute("SELECT value FROM kv_store WHERE key='s1_plain'").fetchone()
    finally:
        other.close()
    assert row is not None and row[0] == "committed"


def test_set_fiscal_config_respects_caller_owned_transaction(game):
    db, _state, _content = game
    key = "官俸_base"
    before = _fiscal_config_value(db, key)

    db.conn.execute("DELETE FROM kv_store WHERE key='s1_fiscal_cfg_open'")
    db.conn.commit()
    db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_fiscal_cfg_open','open')")
    assert db.conn.in_transaction

    db.set_fiscal_config(key, before + 1)

    assert db.conn.in_transaction
    assert _fiscal_config_value(db, key) == before + 1
    db.conn.rollback()
    assert _fiscal_config_value(db, key) == before


def test_set_fiscal_config_batch_respects_caller_owned_transaction(game):
    db, _state, _content = game
    first_key = "官俸_base"
    second_key = "工程_base"
    first_before = _fiscal_config_value(db, first_key)
    second_before = _fiscal_config_value(db, second_key)

    db.conn.execute("DELETE FROM kv_store WHERE key='s1_fiscal_batch_open'")
    db.conn.commit()
    db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_fiscal_batch_open','open')")
    assert db.conn.in_transaction

    db.set_fiscal_config_batch({
        first_key: first_before + 1,
        second_key: second_before + 2,
    })

    assert db.conn.in_transaction
    assert _fiscal_config_value(db, first_key) == first_before + 1
    assert _fiscal_config_value(db, second_key) == second_before + 2
    db.conn.rollback()
    assert _fiscal_config_value(db, first_key) == first_before
    assert _fiscal_config_value(db, second_key) == second_before


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
    assert db.reign.kv_get("s1_exc") is None
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

    assert db.reign.kv_get("s1_ie_outer") is None
    assert db.reign.kv_get("s1_ie_inner") is None
    # 回滚后连接可正常续用
    db.reign.kv_set("s1_ie_after", "ok")
    assert db.reign.kv_get("s1_ie_after") == "ok"
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_ie_after'")
    db.conn.commit()


# ---------------------------------------------------------------------------
# cmr S1 r1 修复回归（F1-F4）
# ---------------------------------------------------------------------------

def test_connection_context_inside_atomic_rolls_back(game):
    """`with db.conn:` 块在 atomic 内不得逃逸提交（cmr S1 r1 F1，codex 实证）。

    sqlite3.Connection.__exit__ 原生在 C 层 commit、绕过 Python override；
    真实路径 db.py undo_chat_turn 用 `with self.conn:`。
    """
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_ctx'")
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            with db.conn:
                db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_ctx','x')")
            raise RuntimeError("boom after conn-context")

    assert db.reign.kv_get("s1_ctx") is None  # 外层回滚必须救回


def test_connection_context_outside_atomic_still_commits(game):
    """atomic 外 `with db.conn:` 保持原生语义：成功退出真提交。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_ctx_out'")
    db.conn.commit()
    with db.conn:
        db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_ctx_out','y')")
    assert db.reign.kv_get("s1_ctx_out") == "y"
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_ctx_out'"); db.conn.commit()


def test_swallowed_inner_exception_forces_outer_rollback(game):
    """内层 atomic 异常被中间层吞掉 → 最外层退出必须回滚并响亮抛错（cmr S1 r1 F2）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_swallow'")
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            try:
                with atomic(db):
                    db.conn.execute(
                        "INSERT INTO kv_store(key,value) VALUES('s1_swallow','z')"
                    )
                    raise ValueError("inner fails")
            except ValueError:
                pass  # 中间层吞掉——flat 语义下这是禁手

    assert db.reign.kv_get("s1_swallow") is None
    # 回滚后连接可续用
    db.reign.kv_set("s1_swallow_after", "ok")
    assert db.reign.kv_get("s1_swallow_after") == "ok"
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_swallow_after'"); db.conn.commit()


def test_backup_to_inside_atomic_fails_loud(game, tmp_path):
    """atomic 内 backup_to 响亮拒绝（备份会带未提交脏页，cmr S1 r1 F3）。"""
    db, state, content = game
    dest = str(tmp_path / "snap.db")
    with pytest.raises(RuntimeError):
        with atomic(db):
            db.backup_to(dest)


def test_connection_rollback_attempts_all_runtime_callbacks(game):
    """online R3 Gemini：一个 runtime 回滚 callback 失败时，其余 callback 仍须尝试。"""
    db, _state, _content = game
    calls = []

    def first():
        calls.append("first")

    def broken():
        calls.append("broken")
        raise RuntimeError("callback boom")

    def last():
        calls.append("last")

    db.conn.execute("BEGIN")
    db.conn._runtime_rollback_callbacks = [first, broken, last]

    with pytest.raises(RuntimeError):
        db.conn.rollback()

    assert calls == ["last", "broken", "first"]


def test_connection_commit_attempts_all_runtime_callbacks(game):
    """online PR #236 Gemini：一个 runtime commit callback 失败时，其余 callback 仍须尝试。"""
    db, _state, _content = game
    calls = []

    def first():
        calls.append("first")

    def broken():
        calls.append("broken")
        raise RuntimeError("callback boom")

    def last():
        calls.append("last")

    db.conn.execute("BEGIN")
    db.conn._runtime_commit_callbacks = [first, broken, last]

    with pytest.raises(RuntimeError):
        db.conn.commit()

    assert calls == ["first", "broken", "last"]


def test_executescript_inside_atomic_fails_loud(game):
    """atomic 内 executescript 响亮拒绝（C 层隐式 commit 绕过暂停，cmr S1 r1 F4）。"""
    db, state, content = game
    with pytest.raises(RuntimeError):
        with atomic(db):
            db.conn.executescript("SELECT 1;")


# ---------------------------------------------------------------------------
# cmr S1 r2 修复回归（F1-F4）
# ---------------------------------------------------------------------------

def test_swallowed_conn_context_exception_forces_outer_rollback(game):
    """`with db.conn:` 内抛错被吞 → 最外层必须回滚+响亮（cmr S1 r2 F1，3/3 共识）。

    异常时 __exit__ 已回滚掉前序写入 W1；若不置 rollback-only，
    外层会把吞异常后的 W2 照常提交 = W1 静默丢 + W2 半提交。
    """
    db, state, content = game
    for k in ("s1r2_w1", "s1r2_w2"):
        db.conn.execute("DELETE FROM kv_store WHERE key=?", (k,))
    db.conn.commit()

    with pytest.raises(RuntimeError):
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1r2_w1','W1')")
            try:
                with db.conn:
                    raise ValueError("conn-context fails")
            except ValueError:
                pass  # 吞
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1r2_w2','W2')")

    assert db.reign.kv_get("s1r2_w1") is None
    assert db.reign.kv_get("s1r2_w2") is None


def test_commit_failure_in_conn_context_rolls_back(game, monkeypatch):
    """atomic 外 `with db.conn:` body 干净但 commit 失败 → 回滚再抛（原生语义）。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1r2_cf'")
    db.conn.commit()

    conn_cls = type(db.conn)  # 公共连接对象自身的类（不引私有符号）
    real_commit = conn_cls.commit
    def failing_commit(self):
        monkeypatch.setattr(conn_cls, "commit", real_commit)
        raise sqlite3.OperationalError("simulated commit failure")
    monkeypatch.setattr(conn_cls, "commit", failing_commit)

    with pytest.raises(sqlite3.OperationalError):
        with db.conn:
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1r2_cf','x')")

    assert not db.conn.in_transaction  # 已回滚，不留开事务
    assert db.reign.kv_get("s1r2_cf") is None


def test_commit_failure_at_atomic_exit_rolls_back(game, monkeypatch):
    """atomic 最外层 commit 失败 → 回滚再抛，不留开事务。"""
    db, state, content = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1r2_acf'")
    db.conn.commit()

    from ming_sim.applier import _SuspendableConnection
    real_commit = _SuspendableConnection.commit
    calls = {"n": 0}
    def failing_commit(self):
        # atomic 解除暂停后的那次真 commit 才失败
        if not self._commit_suspended and calls["n"] == 0:
            calls["n"] += 1
            raise sqlite3.OperationalError("simulated commit failure")
        return real_commit(self)
    monkeypatch.setattr(_SuspendableConnection, "commit", failing_commit)

    with pytest.raises(sqlite3.OperationalError):
        with atomic(db):
            db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1r2_acf','x')")

    assert not db.conn.in_transaction
    assert db.reign.kv_get("s1r2_acf") is None


def test_atomic_rejects_plain_connection(tmp_path):
    """atomic 对普通 sqlite3.Connection 响亮拒绝（cmr S1 r2 F4，静默失效=最危险）。"""
    class PlainDB:
        def __init__(self):
            self.conn = sqlite3.connect(str(tmp_path / "plain.db"))

    with pytest.raises(TypeError):
        with atomic(PlainDB()):
            pass


# ---------------------------------------------------------------------------
# cmr S1 r3 修复回归（F1/F2）
# ---------------------------------------------------------------------------

def test_begin_failure_at_entry_restores_flags(game, monkeypatch):
    """入口 BEGIN 抛错不得泄漏暂停标志（cmr S1 r3 F2，泄漏=79 处 commit 全静默失效）。"""
    db, state, content = game
    from ming_sim.applier import _SuspendableConnection

    real_execute = _SuspendableConnection.execute
    def failing_execute(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper() == "BEGIN":
            raise sqlite3.OperationalError("simulated BEGIN failure")
        return real_execute(self, sql, *args, **kwargs)
    monkeypatch.setattr(_SuspendableConnection, "execute", failing_execute)

    with pytest.raises(sqlite3.OperationalError):
        with atomic(db):
            pass  # 不应到达

    monkeypatch.setattr(_SuspendableConnection, "execute", real_execute)
    # 后续写照常真提交
    db.reign.kv_set("s1r3_after_begin_fail", "ok")
    assert db.reign.kv_get("s1r3_after_begin_fail") == "ok"
    db.conn.execute("DELETE FROM kv_store WHERE key='s1r3_after_begin_fail'")
    db.conn.commit()
