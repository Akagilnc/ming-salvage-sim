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
        kind, target = parse_subject(subject_kind, subject_id)
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
        """All textual facts on this object, oldest month first. No collapse, no expiry."""
        kind, target = parse_subject(subject_kind, subject_id)
        rows = self._conn.execute(
            "SELECT id, subject_kind, subject_id, year, period, turn, body, origin_ref, affair_id "
            "FROM textual_facts "
            "WHERE (subject_kind = ? AND subject_id = ?) OR (affair_id = ? AND affair_id > 0) "
            "ORDER BY year ASC, period ASC, id ASC",
            (kind, target, _affair_fk_id(target) if kind == "affair" else 0),
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


def _affair_fk_id(target: str) -> int:
    """Numeric affair subject → SQLite FK; non-integer / unstorable → 0 (match by text id)."""
    from ming_sim.strict_types import strict_sqlite_id

    try:
        return strict_sqlite_id(target)
    except (TypeError, ValueError):
        return 0


def _conversion_failed_as_int_text(raw: str) -> bool:
    """Disambiguate strict_sqlite_id ValueError: int-form vs prose historical key.

    Not a conversion authority — only classifies already-failed inputs. Decimal groups
    use str.isdecimal (Unicode Nd, same digit class Python int accepts); optional sign
    and single underscores mirror int() decimal strings. No character-table subset.
    """
    body = raw[1:] if raw[:1] in "+-" else raw
    if not body or body[0] == "_" or body[-1] == "_" or "__" in body:
        return False
    return all(part.isdecimal() and part for part in body.split("_"))


def parse_subject(subject_kind: object, subject_id: object) -> tuple[str, str]:
    """Kind + identity normalize for textual facts (sole numeric-id authority, #1915 S2).

    Affair/yamen ids go through strict_sqlite_id alone (full Python int contract:
    '02'/'+2'/'１'/'2' share one row; range and digit-limit failures reject). True
    non-integer affair keys stay as-is for historical materials; yamen must be integer.
    """
    kind = str(subject_kind or "").strip()
    if kind not in TEXTUAL_FACT_SUBJECT_KINDS:
        raise DeclarationDataError(
            f"textual fact subject_kind must be one of {sorted(TEXTUAL_FACT_SUBJECT_KINDS)}"
        )
    target = str(subject_id or "").strip()
    if not target:
        raise DeclarationDataError("textual fact subject_id cannot be empty")
    if kind in {"affair", "yamen"}:
        from ming_sim.strict_types import strict_sqlite_id

        try:
            target = str(strict_sqlite_id(target))
        except (TypeError, ValueError) as exc:
            # yamen always requires integer; affair int-form failures (range/digit-limit)
            # reject — only prose non-integers remain historical keys.
            if kind == "yamen" or _conversion_failed_as_int_text(target):
                raise DeclarationDataError(
                    f"textual fact {kind} subject_id must be an integer id"
                ) from exc
    return kind, target
