"""结算落库统一拒收契约与事务边界（ADR 0008 S0 骨架）。

契约住此模块；各 section 适配器将原地迁入（PR2）。
公开类型：Provenance / RejectedItem / SectionResult / ApplyContext / RejectionCollector。
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, List


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
    """内存缓冲拒收项，commit 成功后由调用方触发 flush/mirror。

    mirror_to_jsonl 调用契约：仅在事务 commit 成功后调用——文件 append 不可回滚，
    commit 前调用会在 DB 回滚后留下孤立行。本类不做时序判断，由调用方保证。

    attempt 本切片固定为 1；后续切片接错误目录推导后改为从文件计数。
    """

    _buffer: List[dict] = field(default_factory=list, init=False, repr=False)

    def record(self, section: str, rejected_item: RejectedItem, turn: int) -> None:
        """暂存一条拒收记录到内存缓冲，不写 DB。"""
        self._buffer.append({
            "turn": turn,
            "section": section,
            "item_json": json.dumps(rejected_item.item, ensure_ascii=False),
            "reason": rejected_item.reason,
            "category": rejected_item.category,
            "source": rejected_item.source.value,
            "attempt": 1,
        })

    def flush_to_db(self, db: Any) -> None:
        """把缓冲写进 rejection_reports 表，写完清空缓冲。

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
        self._buffer.clear()

    def mirror_to_jsonl(self, path: str) -> None:
        """把缓冲 append 到 jsonl 文件（每行一条 JSON）。

        调用契约：仅在事务 commit 成功后调用，事务回滚不会撤销已 append 的行。
        调用方负责时序；本方法只做机械写入。
        """
        if not self._buffer:
            return
        with open(path, "a", encoding="utf-8") as fh:
            for row in self._buffer:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
