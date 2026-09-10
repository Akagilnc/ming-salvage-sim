"""Append-only textual facts on world-record subjects (ADR 0156)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_textual_facts_subject
    ON textual_facts(subject_kind, subject_id, year, period, id);
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
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "INSERT INTO textual_facts (subject_kind, subject_id, year, period, turn, body) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kind, target, year_n, month, turn_n, stored),
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
        )

    def readable_materials(self, *, subject_kind: str, subject_id: str) -> tuple[TextualFact, ...]:
        """All textual facts on this object, oldest month first. No collapse, no expiry."""
        kind, target = _parse_subject(subject_kind, subject_id)
        rows = self._conn.execute(
            "SELECT id, subject_kind, subject_id, year, period, turn, body "
            "FROM textual_facts "
            "WHERE subject_kind = ? AND subject_id = ? "
            "ORDER BY year ASC, period ASC, id ASC",
            (kind, target),
        ).fetchall()
        return tuple(
            TextualFact(
                id=int(row["id"]),
                subject_kind=str(row["subject_kind"]),
                subject_id=str(row["subject_id"]),
                year=int(row["year"]),
                period=int(row["period"]),
                turn=int(row["turn"]),
                body=str(row["body"]),
            )
            for row in rows
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


