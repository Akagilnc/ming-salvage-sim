"""Append-only textual facts on world-record subjects (ADR 0156)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ming_sim.applier import connection_owns_transaction, sanitize_sqlite_text
from ming_sim.models import reign_period_label

TEXTUAL_FACT_SUBJECT_KINDS = frozenset({"character", "army", "region", "affair"})

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

    @property
    def occurred_month(self) -> str:
        return reign_period_label(self.year, self.period)


class TextualFactStore:
    """World-record home for textual facts. INSERT only; never UPDATE."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

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
    ) -> TextualFact:
        kind, target = _parse_subject(subject_kind, subject_id)
        if not isinstance(body, str) or not body.strip():
            raise ValueError("textual fact body cannot be empty")
        month = int(period)
        if not 1 <= month <= 12:
            raise ValueError(f"textual fact period must be 1..12, got {period}")
        year_n = int(year)
        turn_n = int(turn)
        stored = sanitize_sqlite_text(body)
        origin = sanitize_sqlite_text(str(origin_ref or "").strip())
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "INSERT INTO textual_facts "
            "(subject_kind, subject_id, year, period, turn, body, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, target, year_n, month, turn_n, stored, origin),
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
        )

    def readable_materials(self, *, subject_kind: str, subject_id: str) -> tuple[TextualFact, ...]:
        """All textual facts on this object, oldest month first. No collapse, no expiry."""
        kind, target = _parse_subject(subject_kind, subject_id)
        rows = self._conn.execute(
            "SELECT id, subject_kind, subject_id, year, period, turn, body, origin_ref "
            "FROM textual_facts "
            "WHERE subject_kind = ? AND subject_id = ? "
            "ORDER BY year ASC, period ASC, id ASC",
            (kind, target),
        ).fetchall()
        return tuple(_row_to_fact(row) for row in rows)

    def pointing_at(
        self,
        origin_refs: Iterable[str],
        *,
        subject_kind: str | None = None,
    ) -> tuple[TextualFact, ...]:
        refs = [str(ref).strip() for ref in origin_refs if str(ref).strip()]
        if not refs:
            return ()
        placeholders = ",".join("?" for _ in refs)
        sql = (
            "SELECT id, subject_kind, subject_id, year, period, turn, body, origin_ref "
            "FROM textual_facts WHERE origin_ref IN (" + placeholders + ")"
        )
        params: list[object] = list(refs)
        if subject_kind is not None:
            kind = str(subject_kind or "").strip()
            if kind not in TEXTUAL_FACT_SUBJECT_KINDS:
                raise ValueError(
                    f"textual fact subject_kind must be one of {sorted(TEXTUAL_FACT_SUBJECT_KINDS)}"
                )
            sql += " AND subject_kind = ?"
            params.append(kind)
        sql += " ORDER BY year ASC, period ASC, id ASC"
        return tuple(_row_to_fact(row) for row in self._conn.execute(sql, params).fetchall())


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
    )


def _parse_subject(subject_kind: object, subject_id: object) -> tuple[str, str]:
    kind = str(subject_kind or "").strip()
    if kind not in TEXTUAL_FACT_SUBJECT_KINDS:
        raise ValueError(
            f"textual fact subject_kind must be one of {sorted(TEXTUAL_FACT_SUBJECT_KINDS)}"
        )
    target = str(subject_id or "").strip()
    if not target:
        raise ValueError("textual fact subject_id cannot be empty")
    return kind, target
