"""Person event log: the append-only record of what a person did, and when.

#1889: 人物公私经历的持久写读从 ``db.py`` 大块按职责拆出。This module owns the
``person_logs`` table — its schema, its single write port, and its reads. The
month it happened is part of the fact (a log line without its month cannot be
placed in the reign), so year/period are recorded here rather than inferred by
callers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS person_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn INTEGER NOT NULL,
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    person_name TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_summary TEXT NOT NULL DEFAULT '',
    derived_from TEXT NOT NULL DEFAULT '',
    normalized TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    origin_ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(person_name) REFERENCES characters(name)
);
CREATE INDEX IF NOT EXISTS idx_person_logs_person
    ON person_logs(person_name, turn, id);
CREATE INDEX IF NOT EXISTS idx_person_logs_turn
    ON person_logs(turn, person_name);
CREATE INDEX IF NOT EXISTS idx_person_logs_origin
    ON person_logs(origin_ref, id);
"""


def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


def _clip(value: object, limit: int) -> str:
    return str(value or "")[:limit]


class PersonLogStore:
    """Single write port for ``person_logs``; reads return plain dicts."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    def append(
        self,
        *,
        turn: int,
        year: int,
        period: int,
        person_name: str,
        action: str,
        payload_summary: str = "",
        derived_from: str = "",
        normalized: "str | Mapping[str, object]" = "",
        source: str = "",
        origin_ref: str = "",
        commit: bool = True,
    ) -> int:
        """Record one person event, dated by the month it happened."""
        name = str(person_name or "").strip()
        if not name:
            raise ValueError("person log requires person_name")
        act = str(action or "").strip()
        if not act:
            raise ValueError("person log requires action")
        if isinstance(normalized, Mapping):
            # Sorted keys so an identical event re-records byte-identically.
            normalized_text = json.dumps(dict(normalized), ensure_ascii=False, sort_keys=True)
        else:
            normalized_text = str(normalized or "")
        cur = self._conn.execute(
            "INSERT INTO person_logs "
            "(turn, year, period, person_name, action, payload_summary, "
            " derived_from, normalized, source, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(turn), int(year), int(period),
                name, act,
                _clip(payload_summary, 200),
                _clip(derived_from, 120),
                # Full value: normalized is structured audit JSON, and any
                # truncation would cut it into something unparseable.
                normalized_text,
                _clip(source, 80),
                str(origin_ref or ""),
            ),
        )
        if commit:
            self._conn.commit()
        return int(cur.lastrowid or 0)

    def for_person(self, person_name: str, *, limit: int | None = None) -> List[Dict[str, object]]:
        """One person's log, oldest first."""
        sql = (
            "SELECT * FROM person_logs WHERE person_name=? ORDER BY turn, id"
        )
        params: list[object] = [str(person_name or "")]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def by_origin(self, origin_ref: str) -> List[Dict[str, object]]:
        """Every log line derived from one causal origin, oldest first."""
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM person_logs WHERE origin_ref=? ORDER BY turn, id",
                (str(origin_ref or ""),),
            ).fetchall()
        ]

    def count_by_origin(
        self, origin_ref: str, *, turn: int, action: str = "",
    ) -> int:
        """How many log lines this origin produced in one turn (optionally one action).

        Counted in SQL so the origin/turn index applies — the caller asks "how
        much of this origin landed", not "show me the rows".
        """
        sql = "SELECT COUNT(*) FROM person_logs WHERE origin_ref=? AND turn=?"
        params: list[object] = [str(origin_ref or ""), int(turn)]
        act = str(action or "").strip()
        if act:
            sql += " AND action=?"
            params.append(act)
        row = self._conn.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0
