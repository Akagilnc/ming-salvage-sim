"""Append-only textual facts on world-record subjects (ADR 0156)."""

from __future__ import annotations
from ming_sim.exceptions import DeclarationDataError

from dataclasses import dataclass
from typing import Any

from ming_sim.applier import connection_owns_transaction
from ming_sim.entities.column_write import RowStore
from ming_sim.models import reign_period_label


TEXTUAL_FACT_SUBJECT_KINDS = frozenset({"character", "army", "region", "affair", "yamen"})

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS textual_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    body TEXT NOT NULL,
    origin_ref TEXT NOT NULL DEFAULT '',
    affair_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_textual_facts_subject
    ON textual_facts(subject_kind, subject_id, year, period, id);
CREATE INDEX IF NOT EXISTS idx_textual_facts_origin
    ON textual_facts(origin_ref, id);
"""


@dataclass(frozen=True)
class TextualFact:
    """One append-only world-record sentence, dated by the month it happened."""

    id: int
    subject_kind: str
    subject_id: str
    year: int
    period: int
    turn: int
    body: str
    origin_ref: str = ""
    affair_id: int = 0

    @property
    def occurred_month(self) -> str:
        return reign_period_label(self.year, self.period)


class TextualFactStore(RowStore):
    """World-record home for textual facts. Live writes append; undo restores a row."""

    TABLE = "textual_facts"
    PK = "id"
    TABLES = {"textual_facts": "id"}

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        conn.executescript(_SCHEMA_SQL)

    def append(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        body: str,
        year: int,
        period: int,
        turn: int,
        origin_ref: str = "",
        affair_id: int = 0,
    ) -> TextualFact:
        kind, target = _parse_subject(subject_kind, subject_id)
        if not isinstance(body, str) or not body.strip():
            raise DeclarationDataError("textual fact body cannot be empty")
        month = int(period)
        if not 1 <= month <= 12:
            raise DeclarationDataError(f"textual fact period must be 1..12, got {period}")
        year_n = int(year)
        turn_n = int(turn)
        stored = body
        origin = str(origin_ref or "").strip()
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "INSERT INTO textual_facts "
            "(subject_kind, subject_id, year, period, turn, body, origin_ref, affair_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, target, year_n, month, turn_n, stored, origin, int(affair_id)),
        )
        if owns:
            self._conn.commit()
        return TextualFact(
            id=int(cur.lastrowid),
            subject_kind=kind,
            subject_id=target,
            year=year_n,
            period=month,
            turn=turn_n,
            body=stored,
            origin_ref=origin,
            affair_id=int(affair_id),
        )

    def readable_materials(
        self, *, subject_kind: str, subject_id: str
    ) -> tuple[TextualFact, ...]:
        """All textual facts on this object, oldest month first. No collapse, no expiry.

        Affair queries also collect rows whose structured ``affair_id`` pointer
        targets this affair. Provenance stays on ``origin_ref``.
        """
        kind, target = _parse_subject(subject_kind, subject_id)
        rows = self._conn.execute(
            "SELECT id, subject_kind, subject_id, year, period, turn, body, origin_ref, affair_id "
            "FROM textual_facts "
            "WHERE (subject_kind = ? AND subject_id = ?) OR (affair_id = ? AND affair_id > 0) "
            "ORDER BY year ASC, period ASC, id ASC",
            (kind, target, int(target) if kind == "affair" and target.isdecimal() else 0),
        ).fetchall()
        return tuple(_row_to_fact(row) for row in rows)

    def subject_ids(self, table: str, subject_kind: str) -> Any:
        return self._conn.execute(
            f"SELECT id FROM {table} UNION "
            "SELECT subject_id AS id FROM textual_facts WHERE subject_kind=? ORDER BY id",
            (subject_kind,),
        ).fetchall()


def _row_to_fact(row: Any) -> TextualFact:
    return TextualFact(
        id=int(row["id"]),
        subject_kind=str(row["subject_kind"]),
        subject_id=str(row["subject_id"]),
        year=int(row["year"]),
        period=int(row["period"]),
        turn=int(row["turn"]),
        body=str(row["body"]),
        origin_ref=str(row["origin_ref"] or ""),
        affair_id=int(row["affair_id"]),
    )


def _parse_subject(subject_kind: object, subject_id: object) -> tuple[str, str]:
    kind = str(subject_kind or "").strip()
    if kind not in TEXTUAL_FACT_SUBJECT_KINDS:
        raise DeclarationDataError(
            f"textual fact subject_kind must be one of {sorted(TEXTUAL_FACT_SUBJECT_KINDS)}"
        )
    target = str(subject_id or "").strip()
    if not target:
        raise DeclarationDataError("textual fact subject_id cannot be empty")
    # 数值主体身份规范化：纯数字（含前导零）收成十进制，避免 '02'/'2' 分裂（#1915 F3）。
    # yamen 必须是整数 id；affair 历史测试/材料偶有非数字键，非数字原样保留。
    if kind in {"affair", "yamen"} and target.lstrip("-").isdecimal():
        from ming_sim.strict_types import strict_sqlite_id

        try:
            target = str(strict_sqlite_id(target))
        except (TypeError, ValueError) as exc:
            raise DeclarationDataError(f"textual fact {kind} subject_id must be an integer id") from exc
    elif kind == "yamen":
        raise DeclarationDataError("textual fact yamen subject_id must be an integer id")
    return kind, target
