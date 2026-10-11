"""存读档热替换核心（#1902 F2）——Web 使用的唯一实现。

本模块**实际导出**（本文件不再另留同构副本）：

- ``replace_database``：排空已接纳工作 → 单独占区备份 → 关旧会话 → 破坏性替换 →
  重建候选会话；失败则处置候选、还原备份、重建。**禁**在独占区外换库。
- ``runtime_restorable``：失败 close 后可否恢复为活局——db 与 agno 都必须仍可用，
  且未进入 close 半态。探测异常必 log（ADR 0005），不得宽 catch 静默 False。
- ``delete_sqlite_db_files_or_raise`` / ``SaveSlotCleanupError``：删主库及 WAL/SHM
  的唯一实现；核只判定并归类失败原因，对玩家说什么由入口翻。
- ``copy_sqlite_file``：「用存档覆盖主库」那一步的唯一实现。

**共同候选生命周期**（``open_candidate_session``）：GameSession 构造、自有队列归属、
begin_turn、崩溃对账、宿主 ``prepare``（呈现等发布前准备）、失败时在**候选
自有队列**上关闭并把活残留挂到**实际传出的异常**。禁入口另写一份
关闭逻辑，或把候选挂回正持 barrier 的旧队列（父子屏障自等待）。

**各端自有**（经 ``prepare`` / ``SaveSlotHost.rebuild`` 发布 / ``dispose_residual``）：

- 发布前准备回调：Web 聊天缓存与收藏；
- 发布赋值与失败候选宿主残留登记。

换库的时序与失败恢复顺序只有 ``replace_database`` 一份；本模块不认识任何入口类型，
也不知道 HTTP。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SaveSlotCleanupError(OSError):
    """删主库/WAL/SHM 失败：核抛此错，入口各自翻成对外形态（Web → 500）。

    ``reason`` 取 ``not_a_file`` / ``permission`` / ``os_error``，供入口写自己的
    指引文案；核只负责判定与归类，不决定对玩家说什么。
    """

    def __init__(self, target: str, reason: str, cause: BaseException | None = None) -> None:
        super().__init__(f"{reason}: {target}")
        self.target = target
        self.reason = reason
        self.cause = cause


def delete_sqlite_db_files_or_raise(db_path: str) -> None:
    """删主库及其 WAL/SHM；删不掉就抛 ``SaveSlotCleanupError``（不假装干净）。

    这是删库唯一实现（#1902 判词：此前 web_app 另有一份同构的
    ``_delete_sqlite_db_files_or_raise``，两份只差异常形态——那份已删，
    Web 侧改在本函数调用点把 ``SaveSlotCleanupError`` 翻成 HTTPException 500）。
    """
    for suffix in ("", "-wal", "-shm"):
        target = f"{db_path}{suffix}"
        if not os.path.exists(target):
            continue
        if not os.path.isfile(target):
            raise SaveSlotCleanupError(target, "not_a_file")
        try:
            os.remove(target)
        except PermissionError as exc:
            raise SaveSlotCleanupError(target, "permission", exc) from exc
        except OSError as exc:
            raise SaveSlotCleanupError(target, "os_error", exc) from exc


def copy_sqlite_file(source: str, dest: str) -> None:
    """把 ``source`` 的库内容整份覆盖到 ``dest``（SQLite backup API，两端共用）。

    这是「读档 = 用存档覆盖主库」那一步的唯一实现（#1902 判词：此前
    ``WebGame.load_save`` 与 ``cli._cli_load`` 各带一份逐行相同的 sqlite backup
    闭包——两份已删，两端都把本函数当 ``replace_database`` 的 destructive_replace）。
    两个连接都必须关（``finally``），否则 Windows/打包环境下源文件仍被占用。
    """
    import sqlite3

    src_conn = sqlite3.connect(source)
    dst_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


def runtime_restorable(runtime: Any) -> bool:
    """#1749：失败 close 后可否恢复为活局——db 与 agno 都必须仍可用，且未进入 close 半态。

    探测异常必 logger.exception（ADR 0005）；不得宽 catch 静默 False。
    """
    session = getattr(runtime, "session", None)
    if session is None:
        session = runtime
    if int(getattr(session, "_close_epoch", 0) or 0) > 0:
        return False
    db = getattr(session, "db", None)
    conn = getattr(db, "conn", None) if db is not None else None
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1")
    except Exception:
        logger.exception("runtime restorable probe: db.conn failed")
        return False
    agno = getattr(session, "agno_db", None)
    if agno is None:
        return False
    engine = getattr(agno, "db_engine", None)
    if engine is None:
        return False
    try:
        with engine.connect() as c:
            c.exec_driver_sql("SELECT 1")
    except Exception:
        logger.exception("runtime restorable probe: agno engine failed")
        return False
    return True


class SaveSlotBusyError(RuntimeError):
    """独占区里发现结算在飞：核抛此错，入口各自翻成自己的对外形态（Web → 409）。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def open_candidate_session(
    db_path: str,
    llm_config: Any,
    *,
    prepare: Callable[[Any], Any] | None = None,
) -> Any:
    """换库候选共同生命周期：构造 → 自有队列 → begin_turn → 对账 → 可选 prepare。

    ``prepare(candidate)`` 在**发布前**跑（宿主呈现/同步补跑），仍在失败关闭保护区内：
    任一步失败都在候选自有队列上关闭，不得挂到正执行 replace barrier 的旧队列。

    返回值：无 ``prepare`` 时为候选；有 ``prepare`` 时为 ``(candidate, prepare的返回值)``。
    关闭仍失败时，把活残留挂到**实际向外抛出的那只异常**的 ``residual_session``
    （关闭异常），并以 ``from`` 保留初始化/准备故障链，供宿主 dispose 在换文件前接到。
    发布赋值仍由入口 rebuild 在本函数成功返回后完成。
    """
    from ming_sim.session import GameSession
    from ming_sim.session_write_queue import get_session_write_queue

    candidate = None
    try:
        candidate = GameSession(db_path, llm_config)
        # GameSession 构造已装自有队列；此处只解析，禁改挂到父 runtime 队列。
        get_session_write_queue(candidate)
        candidate.begin_turn()
        candidate.reconcile_crashed_audience_turns()
        if prepare is not None:
            prepared = prepare(candidate)
            return candidate, prepared
        return candidate
    except Exception as exc:
        residual = candidate or getattr(exc, "residual_session", None)
        if residual is None:
            raise
        try:
            residual.close()
        except Exception as close_exc:
            logger.exception(
                "open_candidate_session: rejected candidate close failed path=%s",
                db_path,
            )
            # 活残留必须挂在实际传出的异常上；bare raise 会抛 close_exc 而非 originating。
            try:
                setattr(close_exc, "residual_session", residual)
            except Exception:
                pass
            raise close_exc from exc
        raise


class SaveSlotHost:
    """换库所需的宿主能力（入口实现之，核心不认识入口类型）。

    - ``write_queue(runtime)``：该宿主的会话写队列（换库期间要 seal/barrier）。
    - ``entry_lock(runtime)`` / ``settlement_inflight(runtime)``：结算准入互斥与在飞计数。
    - ``rebuild(runtime, llm_config)``：造候选会话（各端自有，见模块头说明）。
    - ``dispose_residual(runtime, residual)``：处置失败候选（各端自有）。
    - ``busy_detail()``：独占区内发现结算在飞时的对外文案。
    """

    def write_queue(self, runtime: Any): raise NotImplementedError
    def entry_lock(self, runtime: Any): raise NotImplementedError
    def settlement_inflight(self, runtime: Any) -> int: raise NotImplementedError
    def rebuild(self, runtime: Any, llm_config: Any) -> None: raise NotImplementedError
    def dispose_residual(self, runtime: Any, residual: Any) -> bool: raise NotImplementedError
    def busy_detail(self) -> str: return "月末结算或上一步写入进行中，请稍候再操作。"


def replace_database(
    runtime: Any,
    host: SaveSlotHost,
    destructive_replace: Callable[[], None],
) -> None:
    """Drain admitted work, then replace the main DB under one exclusive barrier.

    ``runtime`` 须提供 ``session`` / ``db_path``；换库成功后其 ``session`` 已指向
    新建的候选会话。失败则还原替换前的数据库与 runtime，并照原异常上抛。

    #1902 J2：旧关闭未完成且文件尚未替换时，**不得**无条件删库/复制备份/重建。
    文件恢复只在 close 已完成或破坏性替换已发生之后，按既有 close／restorable 接缝处置。
    """
    backup_fd, backup_path = tempfile.mkstemp(prefix="ming-hot-replace-", suffix=".db")
    os.close(backup_fd)
    old_session = runtime.session
    old_config = old_session.llm_config
    backup_complete = False
    old_closed = False
    files_replaced = False
    queue = host.write_queue(runtime)
    entry_lock = host.entry_lock(runtime)
    queue.seal()

    def _replace() -> None:
        nonlocal backup_complete, old_closed, files_replaced
        gate = queue.write_gate
        gate.acquire()
        entry_lock.acquire()
        try:
            # 全局锁序固定为 gate → entry_lock（失败清理亦同序）。HTTP
            # 预检不是安全边界；必须在此最终独占区拒绝预检后新进入的结算。
            if int(host.settlement_inflight(runtime) or 0) > 0:
                raise SaveSlotBusyError(host.busy_detail())
            # Backup and close share the same exclusive span: an admitted writer
            # cannot change the snapshot between prepare and destructive replace.
            runtime.db.backup_to(backup_path)
            backup_complete = True
            old_session.close(write_gate_already_held=True)
            old_closed = True
            destructive_replace()
            files_replaced = True
            host.rebuild(runtime, old_config)
        except Exception as replace_exc:
            # 备份前失败、或 close 未完成且文件未动：原样上抛，不碰主库文件。
            if not backup_complete or (not old_closed and not files_replaced):
                raise
            try:
                # 恢复重建前必须处置失败候选；仍活则禁止改文件/二次 rebuild。
                if not host.dispose_residual(runtime, getattr(runtime, "_rebuild_residual_runtime", None)):
                    logger.error(
                        "hot replace recovery blocked: rebuild residual still live path=%s",
                        runtime.db_path,
                    )
                    raise replace_exc
                delete_sqlite_db_files_or_raise(runtime.db_path)
                shutil.copy2(backup_path, runtime.db_path)
                host.rebuild(runtime, old_config)
            except Exception as recovery_exc:
                if recovery_exc is replace_exc:
                    raise
                logger.exception("hot replace recovery failed")
                raise replace_exc from recovery_exc
            raise
        finally:
            entry_lock.release()
            gate.release()

    try:
        queue.barrier(_replace)
    finally:
        queue.unseal()
        try:
            os.remove(backup_path)
        except OSError:
            logger.exception("failed to remove hot replace backup %s", backup_path)
