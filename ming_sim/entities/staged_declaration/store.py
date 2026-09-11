"""旨意夜里预推的暂存声明：只暂存、可作废、按 decree_ref 序幂等结算（ADR 0157 步骤 1-2）。

产物全部暂存：不落账、不进材料目录、HUD 不动；皇帝撤旨 / 改旨作废该旨预算；
过月按下旨先后核算落账，一旨的全部声明与其落账标记同一次数据库提交（一旨一
提交）；已结算的旨幂等跳过，不重复落账。本存储只负责「存 / 作废 / 是否已结算」
三件事，落账本身（把暂存的声明分派到各域）由 `ming_sim.declaration_dispatch`
的 `settle_staged_declarations_in_decree_order` 消费。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ming_sim.applier import connection_owns_transaction, sanitize_sqlite_text

_STATUS_STAGED = "staged"
_STATUS_DISCARDED = "discarded"
_STATUS_SETTLED = "settled"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS staged_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decree_ref TEXT NOT NULL,
    declaration_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged'
        CHECK(status IN ('staged','discarded','settled')),
    created_turn INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_staged_declarations_decree
    ON staged_declarations(decree_ref, id);
CREATE INDEX IF NOT EXISTS idx_staged_declarations_status
    ON staged_declarations(decree_ref, status, id);
"""


class DecreeAlreadySettled(ValueError):
    """该 decree_ref 已经结算过，不能再暂存新声明（防止结算后悄悄多出永远不会
    被消费/拒绝的孤儿 staged 行——一个 decree_ref 的生命周期是单向的
    staged → (discarded | settled)，settled 是终态）。

    ADR 0157「改旨 = 作废后按新旨重起」：同一件事需要再来一轮，调用方应发一个
    新的 decree_ref，而不是向已终结的旧 ref 追加。"""


@dataclass(frozen=True)
class StagedDeclaration:
    id: int
    decree_ref: str
    declaration: dict
    status: str
    created_turn: int


class StagedDeclarationStore:
    """夜里预推产物的暂存家：只暂存、可作废、按 decree_ref 序幂等结算。"""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        conn.executescript(_SCHEMA_SQL)

    def stage(self, *, decree_ref: str, declaration: Mapping[str, object], turn: int) -> int:
        ref = str(decree_ref or "").strip()
        if not ref:
            raise ValueError("decree_ref 不能为空")
        if not isinstance(declaration, Mapping):
            raise ValueError("声明须为对象")
        if self.is_settled(ref):
            raise DecreeAlreadySettled(
                f"decree_ref 已结算，不能再暂存新声明：{ref}（如需再起该旨，请用新的 decree_ref）"
            )
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "INSERT INTO staged_declarations (decree_ref, declaration_json, status, created_turn) "
            "VALUES (?, ?, 'staged', ?)",
            (ref, sanitize_sqlite_text(json.dumps(declaration, ensure_ascii=False)), int(turn)),
        )
        if owns:
            self._conn.commit()
        return int(cur.lastrowid)

    def discard(self, decree_ref: str) -> int:
        """撤旨 / 改旨作废该旨全部仍 staged 的暂存产物；已结算的不受影响。"""
        ref = str(decree_ref or "").strip()
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "UPDATE staged_declarations SET status='discarded' "
            "WHERE decree_ref=? AND status='staged'",
            (ref,),
        )
        if owns:
            self._conn.commit()
        return int(cur.rowcount or 0)

    def staged_for(self, decree_ref: str) -> tuple[StagedDeclaration, ...]:
        ref = str(decree_ref or "").strip()
        rows = self._conn.execute(
            "SELECT id, decree_ref, declaration_json, status, created_turn "
            "FROM staged_declarations WHERE decree_ref=? AND status='staged' ORDER BY id",
            (ref,),
        ).fetchall()
        return tuple(_row_to_staged(row) for row in rows)

    def is_settled(self, decree_ref: str) -> bool:
        """幂等判据：该旨是否已有任一结算标记。"""
        ref = str(decree_ref or "").strip()
        row = self._conn.execute(
            "SELECT 1 FROM staged_declarations WHERE decree_ref=? AND status='settled' LIMIT 1",
            (ref,),
        ).fetchone()
        return row is not None

    def mark_settled(self, decree_ref: str) -> int:
        ref = str(decree_ref or "").strip()
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "UPDATE staged_declarations SET status='settled' "
            "WHERE decree_ref=? AND status='staged'",
            (ref,),
        )
        if owns:
            self._conn.commit()
        return int(cur.rowcount or 0)


def _row_to_staged(row: Any) -> StagedDeclaration:
    return StagedDeclaration(
        id=int(row["id"]), decree_ref=str(row["decree_ref"]),
        declaration=json.loads(row["declaration_json"] or "{}"),
        status=str(row["status"]), created_turn=int(row["created_turn"]),
    )
