"""结算落库统一拒收契约与事务边界（ADR 0008 S0 骨架）。

契约住此模块；各 section 适配器将原地迁入（PR2）。
公开类型：Provenance / RejectedItem / SectionResult / ApplyContext / RejectionCollector。
"""

from __future__ import annotations

import enum
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, List


def sanitize_sqlite_text(value: Any) -> Any:
    """Return value with strings safe to bind into SQLite UTF-8 TEXT.

    Python can hold lone surrogate codepoints produced by permissive JSON
    parsing, but sqlite3 refuses to UTF-8 encode them at bind time. Preserve
    normal text (including Chinese) and escape only unencodable codepoints.
    """
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, list):
        return [sanitize_sqlite_text(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_sqlite_text(item) for item in value)
    if isinstance(value, dict):
        return {
            sanitize_sqlite_text(key): sanitize_sqlite_text(val)
            for key, val in value.items()
        }
    return value


def safe_json_dumps(value: Any, **kwargs: Any) -> str:
    """json.dumps that preserves readable UTF-8 while escaping bad codepoints."""
    return json.dumps(sanitize_sqlite_text(value), **kwargs)


# ---------------------------------------------------------------------------
# 决定 2/8：事务边界 —— commit 暂停连接 + atomic 包裹
# ---------------------------------------------------------------------------

class _SuspendableConnection(sqlite3.Connection):
    """sqlite3.Connection 子类，可暂停 commit。

    暂停期内 commit() 变 no-op；非暂停期照常。db.py 以 factory= 此类建连，使
    GameDB 全库 79 处 self.conn.commit() 在 atomic 内自动失效、由最外层统一提交，
    一字不改。rollback() 暂停期仍真回滚，且回滚后立即重开事务（维持「atomic 内
    永远有开着的事务」，防 DDL autocommit 逃逸）。

    _commit_suspended 默认 off：保证 GameDB.__init__ 紧接的 init_schema 建表照常提交。

    原生 `with conn:` 的 __exit__ 在 C 层直接 commit、绕过本 override（cmr S1 F1
    实证），故重写 __enter__/__exit__ 改走 Python 层 commit/rollback——atomic 内
    `with conn:` 块的提交被暂停、由最外层统一落定，atomic 外保持原生语义。
    executescript 在 legacy 模式 C 层先隐式 commit、同样绕过暂停（cmr S1 F4），
    暂停期直接拒绝。
    """

    # 类属性兜底：sqlite3 可能在 __init__ 前调用 commit（理论上不会，但稳妥）。
    _commit_suspended = False

    def commit(self) -> None:
        if self._commit_suspended:
            return
        callbacks = list(getattr(self, "_runtime_commit_callbacks", []))
        self._runtime_commit_callbacks = []
        super().commit()
        self._runtime_rollback_callbacks = []
        callback_errors = []
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                callback_errors.append(exc)
        if callback_errors:
            raise RuntimeError(
                f"runtime commit callback failed ({len(callback_errors)} error(s))"
            ) from callback_errors[0]

    def rollback(self) -> None:
        super().rollback()
        callbacks = list(getattr(self, "_runtime_rollback_callbacks", []))
        self._runtime_rollback_callbacks = []
        self._runtime_commit_callbacks = []
        callback_errors = []
        try:
            for callback in reversed(callbacks):
                try:
                    callback()
                except Exception as exc:
                    callback_errors.append(exc)
        finally:
            if self._commit_suspended:
                # 中途回滚（显式或 with conn: 异常）结束了 BEGIN 的事务；立即重开，
                # 维持「atomic 内永远有开着的事务」——否则后续 DDL 跑 autocommit
                # 逃逸外层回滚（cmr S1 r3 F1）。atomic 终态退出前已清暂停标志，不误触。
                self.execute("BEGIN")
        if callback_errors:
            raise RuntimeError(
                f"runtime rollback callback failed ({len(callback_errors)} error(s))"
            ) from callback_errors[0]

    def __enter__(self) -> "_SuspendableConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            try:
                self.commit()
            except BaseException:
                # 原生语义：body 干净但 commit 失败 → 回滚再抛，不留开事务。
                self.rollback()
                raise
        else:
            if self._commit_suspended:
                # atomic 内：异常已回滚共享事务（前序写入一并消失），必须让
                # 最外层 rollback-only，防调用方吞掉异常后半提交（cmr S1 r2 F1）。
                self._atomic_rollback_only = True
            self.rollback()
        return False

    def executescript(self, sql_script):
        if self._commit_suspended:
            raise RuntimeError(
                "executescript 在 atomic 事务内禁止：C 层隐式 commit 会绕过暂停、"
                "提前提交半成品。请改用逐条 execute，或移到 atomic 外。"
            )
        return super().executescript(sql_script)


@contextmanager
def atomic(db: Any) -> Iterator[None]:
    """把 db.conn 上的一段写序列包成单事务，期内暂停所有 commit。

    进入：置暂停标志，期内全部 self.conn.commit() 变 no-op。
    正常退出：解除暂停 + 一次真 commit。
    异常：解除暂停 + rollback + 原样 re-raise（ADR 0005 fail-loud，不吞）。

    嵌套 flat/可重入：内层 atomic 不另起事务、不提前提交，由最外层统一
    commit/rollback（计数深度，仅深度归 0 时落定）。内层异常即使被中间层
    try/except 吞掉，最外层退出也强制回滚并响亮抛错（rollback-only 标志，
    cmr S1 F2）——flat 语义下「吞内层异常后继续提交」结构上不可达。

    备份请在 rollback/commit 之后、atomic 之外做：db.backup_to 在 atomic 内
    会响亮拒绝（备份走同连接 pager，会带上未提交脏页，cmr S1 F3）。
    """
    conn = db.conn
    if not isinstance(conn, _SuspendableConnection):
        raise TypeError(
            "atomic() 要求 db.conn 是 _SuspendableConnection（GameDB 默认 factory）；"
            "普通 sqlite3.Connection 的 commit 拦不住，会静默失去原子性。"
        )
    # 进入深度：>1 表示嵌套内层，退出时不落定。
    depth = getattr(conn, "_atomic_depth", 0) + 1
    # 状态变更全部在 try 内：BEGIN 抛错 / KeyboardInterrupt 落在入口窗口时，
    # except 分支照常复位，暂停标志不泄漏（泄漏=79 处 commit 永久静默失效，
    # cmr S1 r3 F2）。
    try:
        conn._commit_suspended = True
        conn._atomic_depth = depth
        if depth == 1 and not conn.in_transaction:
            # legacy 模式只有 DML 隐式开事务；不显式 BEGIN 的话，DDL 打头的
            # 序列（如 flush_to_db 建表）跑在 autocommit 里、回滚留表（cmr S1 r2 F2）。
            conn.execute("BEGIN")
        yield
    except BaseException:
        conn._atomic_depth = depth - 1
        if depth == 1:
            conn._atomic_rollback_only = False
            conn._commit_suspended = False
            conn.rollback()
        else:
            # 内层异常：标记 rollback-only，防中间层吞掉后外层照常提交。
            conn._atomic_rollback_only = True
        raise
    else:
        conn._atomic_depth = depth - 1
        if depth == 1:
            conn._commit_suspended = False
            if getattr(conn, "_atomic_rollback_only", False):
                conn._atomic_rollback_only = False
                conn.rollback()
                raise RuntimeError(
                    "atomic: 内层异常被调用方吞掉，事务已整体回滚。"
                    "flat 语义下内层无独立原子性——请勿在 atomic 之间吞内层异常。"
                )
            try:
                conn.commit()
            except BaseException:
                # commit 失败不留开事务（与原生 with conn: 语义一致）。
                conn.rollback()
                raise


# ---------------------------------------------------------------------------
# 决定 5：拒收来源枚举
# ---------------------------------------------------------------------------

class Provenance(str, enum.Enum):
    """delta 来源标记，灌注到适配器入参，决定拒收报告可见性与问责路径。"""

    player_decree = "player_decree"
    hitl_decision = "hitl_decision"
    secret_order = "secret_order"
    system_simulation = "system_simulation"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# 决定 1：拒收记录
# ---------------------------------------------------------------------------

@dataclass
class RejectedItem:
    """一条被拒收的 delta 项，附原因与分析类别。

    category 约定值（非 exhaustive）：hallucinated_id / invalid_enum / missing_ref。
    source 由 driver/extractor 灌注，决定是否向玩家可见（ADR 0008 决定 5）。
    """

    item: dict                  # 原始 dict，原样保留便于重放分析
    reason: str                 # 人读原因
    category: str               # 机读类别，供聚合
    source: Provenance          # 来源


# ---------------------------------------------------------------------------
# 决定 1：段适配器返回值
# ---------------------------------------------------------------------------

@dataclass
class SectionResult:
    """一个 section 适配器的返回值。

    applied: 已落库的原始项列表（用于摘要日志）。
    rejected: 被拒收的项，带原因与类别。
    """

    applied: List[Any]
    rejected: List[RejectedItem]

    def merge(self, other: SectionResult) -> SectionResult:
        """聚合两个 SectionResult（编排层按 section 顺序折叠）。"""
        return SectionResult(
            applied=self.applied + other.applied,
            rejected=self.rejected + other.rejected,
        )


# ---------------------------------------------------------------------------
# 决定 1：适配器入参上下文
# ---------------------------------------------------------------------------

@dataclass
class ApplyContext:
    """适配器入参，持结算所需的全部外部依赖。

    registry 可为 None（向后兼容无 registry 路径）。
    source 由 driver/extractor 在调用前灌注。
    """

    db: Any          # GameDB（不在 applier 层导入 GameDB 避免循环）
    state: Any       # GameState
    content: Any     # GameContent
    registry: Any    # 可为 None
    source: Provenance


# ---------------------------------------------------------------------------
# 决定 5：拒收收集器
# ---------------------------------------------------------------------------

class RejectionCollectorRequired(ValueError):
    """段/核需 record 拒收但未获外层 RejectionCollector（0150-D2 / #1745）。

    typed 控制流标记：catch 只认本类，禁止解析异常散文。
    """

_CREATE_REJECTION_REPORTS = """
CREATE TABLE IF NOT EXISTS rejection_reports (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    turn     INTEGER NOT NULL,
    section  TEXT    NOT NULL,
    item_json TEXT   NOT NULL,
    reason   TEXT    NOT NULL,
    category TEXT    NOT NULL,
    source   TEXT    NOT NULL,
    attempt  INTEGER NOT NULL DEFAULT 1,
    resimulation_invalidated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class RejectionCollector:
    """内存缓冲拒收项。生命周期与事务对齐（ADR 0008 决定 5）：

        record×N → flush_to_db（事务内，行随回滚消失）→ commit
                 → mirror_to_jsonl（仅 commit 成功后——文件 append 不可回滚）
        回滚路径：rollback → reset()（丢弃缓冲与待镜像快照）

    mirror 只镜像已 flush 进 DB 的行：未落库的行可能随回滚消失，镜像它们
    会留孤立行。本类不做时序判断，由调用方保证。

    attempt 由调用方在构造时灌注（PR2-S0 接错误目录推导，ADR 决定 5：不从 DB 取
    ——DB 计数随回滚重置即失真；error_pack._next_attempt 是同一推导的唯一真源）。
    """

    attempt: int = 1
    _buffer: List[dict] = field(default_factory=list, init=False, repr=False)
    _flushed: List[dict] = field(default_factory=list, init=False, repr=False)

    def record(self, section: str, rejected_item: RejectedItem, turn: int) -> None:
        """暂存一条拒收记录到内存缓冲，不写 DB。

        source 归一为 Provenance 值字符串；非法字符串响亮 ValueError。
        """
        self._buffer.append({
            "turn": turn,
            "section": section,
            "item_json": safe_json_dumps(rejected_item.item, ensure_ascii=False),
            "reason": rejected_item.reason,
            "category": rejected_item.category,
            "source": Provenance(rejected_item.source).value,
            "attempt": self.attempt,
        })

    def flush_to_db(self, db: Any) -> None:
        """把缓冲写进 rejection_reports 表，写完移入待镜像快照。

        首次调用时建表（CREATE TABLE IF NOT EXISTS）——确保老存档不需要迁移脚本。
        空缓冲时直接返回（幂等）。
        """
        db.conn.execute(_CREATE_REJECTION_REPORTS)
        cols = {
            str(row[1]) for row in db.conn.execute("PRAGMA table_info(rejection_reports)").fetchall()
        }
        if "resimulation_invalidated" not in cols:
            db.conn.execute(
                "ALTER TABLE rejection_reports "
                "ADD COLUMN resimulation_invalidated INTEGER NOT NULL DEFAULT 0"
            )
        if not self._buffer:
            return
        db.conn.executemany(
            "INSERT INTO rejection_reports (turn, section, item_json, reason, category, source, attempt)"
            " VALUES (:turn, :section, :item_json, :reason, :category, :source, :attempt)",
            self._buffer,
        )
        self._flushed.extend(self._buffer)
        self._buffer.clear()

    def mirror_to_jsonl(self, path: str) -> None:
        """把待镜像快照（已 flush 进 DB 的行）append 到 jsonl，写完清空快照。

        调用契约：仅在事务 commit 成功后调用。成功调用后重复调用幂等（只写一次）；
        写入中途失败（如磁盘满）后重试可能重复 append——jsonl 是可回收镜像，DB 为真源。
        """
        if not self._flushed:
            return
        with open(path, "a", encoding="utf-8") as fh:
            for row in self._flushed:
                fh.write(safe_json_dumps(row, ensure_ascii=False) + "\n")
        self._flushed.clear()

    def reset(self) -> None:
        """丢弃缓冲与待镜像快照（回滚路径：DB 行已随事务回滚，内存同步清场）。"""
        self._buffer.clear()
        self._flushed.clear()

    def has_player_visible_rejection(self) -> bool:
        """本回合是否有 player_decree / hitl_decision 来源的拒收——决定玩家面邸报是否给一句
        in-world 提示（ADR 0008 决定 5：仅这两来源对玩家可见，系统推演来源安静）。
        检 _buffer + _flushed：报告组装在事务内、commit/mirror 前，拒收已 record 可能已 flush 未 mirror。"""
        _visible = {Provenance.player_decree.value, Provenance.hitl_decision.value}
        return any(row["source"] in _visible for row in (*self._buffer, *self._flushed))


def register_runtime_outcome_callbacks(
    db: Any,
    *,
    on_commit: Callable[[], None] | None = None,
    on_rollback: Callable[[], None] | None = None,
) -> None:
    """Run callbacks at the real outermost commit/rollback boundary.

    Nested owners register on the shared connection so side effects (JSONL mirror,
    registry refresh) only fire after the outermost commit, and are discarded on
    rollback. Depth 0 runs on_commit immediately.
    """
    if getattr(db.conn, "_atomic_depth", 0) == 0:
        if on_commit is not None:
            on_commit()
        return
    if on_commit is not None:
        commit_callbacks = getattr(db.conn, "_runtime_commit_callbacks", None)
        if commit_callbacks is None:
            commit_callbacks = []
            db.conn._runtime_commit_callbacks = commit_callbacks
        commit_callbacks.append(on_commit)
    if on_rollback is not None:
        rollback_callbacks = getattr(db.conn, "_runtime_rollback_callbacks", None)
        if rollback_callbacks is None:
            rollback_callbacks = []
            db.conn._runtime_rollback_callbacks = rollback_callbacks
        rollback_callbacks.append(on_rollback)


def mirror_rejections_after_commit(
    db: Any,
    collector: RejectionCollector,
    path_provider: Callable[[], str],
) -> None:
    """Mirror a collector at its real transaction outcome boundary.

    A nested owner registers both terminal actions on the shared connection:
    commit mirrors the flushed snapshot, while rollback clears it so reusing the
    collector cannot leak rolled-back rows into a later JSONL mirror.
    """
    def _mirror() -> None:
        try:
            collector.mirror_to_jsonl(path_provider())
        except Exception as mirror_exc:
            from ming_sim.token_stats import tlog
            tlog(f"[rejection] jsonl 镜像失败（DB 行已落，仅副本丢失）：{mirror_exc}")

    register_runtime_outcome_callbacks(
        db, on_commit=_mirror, on_rollback=collector.reset,
    )
