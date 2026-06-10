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
from typing import Any, Iterator, List


# ---------------------------------------------------------------------------
# 决定 2/8：事务边界 —— commit 暂停连接 + atomic 包裹
# ---------------------------------------------------------------------------

class _SuspendableConnection(sqlite3.Connection):
    """sqlite3.Connection 子类，可暂停 commit。

    暂停期内 commit() 变 no-op；非暂停期照常。db.py 以 factory= 此类建连，使
    GameDB 全库 79 处 self.conn.commit() 在 atomic 内自动失效、由最外层统一提交，
    一字不改。rollback() 不受暂停影响（暂停只拦 commit）。

    _commit_suspended 默认 off：保证 GameDB.__init__ 紧接的 init_schema 建表照常提交。
    """

    # 类属性兜底：sqlite3 可能在 __init__ 前调用 commit（理论上不会，但稳妥）。
    _commit_suspended = False

    def commit(self) -> None:
        if self._commit_suspended:
            return
        super().commit()


@contextmanager
def atomic(db: Any) -> Iterator[None]:
    """把 db.conn 上的一段写序列包成单事务，期内暂停所有 commit。

    进入：置暂停标志，期内全部 self.conn.commit() 变 no-op。
    正常退出：解除暂停 + 一次真 commit。
    异常：解除暂停 + rollback + 原样 re-raise（ADR 0005 fail-loud，不吞）。

    嵌套 flat/可重入：内层 atomic 不另起事务、不提前提交，由最外层统一
    commit/rollback（计数深度，仅深度归 0 时落定）。

    注意 db.backup_to 内部那次 self.conn.commit() 在 atomic 内也被暂停——这是
    接受的语义（错误包应在回滚后、atomic 外做备份），不特殊放行。
    """
    conn = db.conn
    conn._commit_suspended = True
    # 进入深度：>1 表示嵌套内层，退出时不落定。
    depth = getattr(conn, "_atomic_depth", 0) + 1
    conn._atomic_depth = depth
    try:
        yield
    except BaseException:
        conn._atomic_depth = depth - 1
        if depth == 1:
            conn._commit_suspended = False
            conn.rollback()
        raise
    else:
        conn._atomic_depth = depth - 1
        if depth == 1:
            conn._commit_suspended = False
            conn.commit()


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

    attempt 本切片固定为 1；后续切片接错误目录推导后改为从文件计数。
    """

    _buffer: List[dict] = field(default_factory=list, init=False, repr=False)
    _flushed: List[dict] = field(default_factory=list, init=False, repr=False)

    def record(self, section: str, rejected_item: RejectedItem, turn: int) -> None:
        """暂存一条拒收记录到内存缓冲，不写 DB。

        source 归一为 Provenance 值字符串；非法字符串响亮 ValueError。
        """
        self._buffer.append({
            "turn": turn,
            "section": section,
            "item_json": json.dumps(rejected_item.item, ensure_ascii=False),
            "reason": rejected_item.reason,
            "category": rejected_item.category,
            "source": Provenance(rejected_item.source).value,
            "attempt": 1,
        })

    def flush_to_db(self, db: Any) -> None:
        """把缓冲写进 rejection_reports 表，写完移入待镜像快照。

        首次调用时建表（CREATE TABLE IF NOT EXISTS）——确保老存档不需要迁移脚本。
        空缓冲时直接返回（幂等）。
        """
        db.conn.execute(_CREATE_REJECTION_REPORTS)
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
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._flushed.clear()

    def reset(self) -> None:
        """丢弃缓冲与待镜像快照（回滚路径：DB 行已随事务回滚，内存同步清场）。"""
        self._buffer.clear()
        self._flushed.clear()
