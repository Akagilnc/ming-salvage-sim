"""存读档热替换核心（#1902 F2）——Web 与 CLI 共用的唯一实现。

此前备份、热替换、失败恢复、候选会话重建与「可否恢复为活局」判定全在
``web_app.WebGame`` 私有方法里（``_replace_database`` / ``_rebuild_session`` /
``_dispose_rebuild_residual``）加模块级 ``_runtime_restorable``：CLI 入口因此
**根本无法读档**——它连主库文件在哪、换库要过哪几道闸都不知道，两端的存读档事实
天然不一致。#1902 票面要求两端共用 #1813 存读档核心，故把这套机制整体搬到这里：

- ``replace_database``：排空已接纳工作 → 单独占区备份 → 关旧会话 → 破坏性替换 →
  重建候选会话；失败则处置候选、还原备份、重建。**禁**在独占区外换库。
- ``rebuild_session``：候选会话完整初始化后才发布为活会话；上一失败候选仍活则拒新候选。
- ``dispose_rebuild_residual``：处置上一失败 rebuild 候选（成功关闭返回 True）。
- ``runtime_restorable``：失败 close 后可否恢复为活局——db 与 agno 都必须仍可用，
  且未进入 close 半态。探测异常必 log（ADR 0005），不得宽 catch 静默 False。

入口适配（Web 呈现缓存 / CLI 文本呈现）由调用方在 ``on_publish`` 回调里做；
本模块不认识任何入口类型，也不知道 HTTP。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Callable

logger = logging.getLogger(__name__)


def delete_sqlite_db_files_or_raise(db_path: str) -> None:
    """删主库及其 WAL/SHM；删不掉就响亮失败（不假装干净）。"""
    for suffix in ("", "-wal", "-shm"):
        target = f"{db_path}{suffix}"
        if os.path.exists(target):
            os.remove(target)


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


class SaveSlotHost:
    """换库所需的宿主能力（入口实现之，核心不认识入口类型）。

    - ``write_queue(runtime)``：该宿主的会话写队列（换库期间要 seal/barrier）。
    - ``entry_lock(runtime)`` / ``settlement_inflight(runtime)``：结算准入互斥与在飞计数。
    - ``rebuild(runtime, llm_config)``：造候选会话（见 ``rebuild_session``）。
    - ``dispose_residual(runtime, residual)``：处置失败候选（见 ``dispose_rebuild_residual``）。
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
    """
    backup_fd, backup_path = tempfile.mkstemp(prefix="ming-hot-replace-", suffix=".db")
    os.close(backup_fd)
    old_session = runtime.session
    old_config = old_session.llm_config
    backup_complete = False
    queue = host.write_queue(runtime)
    entry_lock = host.entry_lock(runtime)
    queue.seal()

    def _replace() -> None:
        nonlocal backup_complete
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
            destructive_replace()
            host.rebuild(runtime, old_config)
        except Exception as replace_exc:
            if not backup_complete:
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
