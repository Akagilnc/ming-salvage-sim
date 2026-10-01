"""Save-slot persistence: the reign header and the balance metrics.

#1889: 存读档的持久读写从 ``db.py`` 大块按职责拆出。The ``game_state`` row is the
reign header (which year/month/turn, and whether the game is over); the
``metrics`` table is the single source of truth for the 国库/内库 balances —
``economy_accounts`` is a read-time view derived from it, never a second copy.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


_LEDGER_ORDER = (
    "turn", "year", "period", "account", "delta", "balance_after", "category",
    "reason", "event_id", "edict_id", "actor", "purpose", "target_kind",
    "target_id", "dossier_id", "origin_ref", "beyond_intent",
)
_LEDGER_COLUMNS = frozenset(_LEDGER_ORDER)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS game_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    turn_phase TEXT NOT NULL DEFAULT 'summoning',
    ended INTEGER NOT NULL DEFAULT 0,
    ending_status TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS metrics (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


class ReignStateStore:
    """Single write port for the reign header and the balance metrics."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    def exists(self) -> bool:
        return self._conn.execute("SELECT 1 FROM game_state WHERE id = 1").fetchone() is not None

    def save(
        self,
        *,
        year: int,
        period: int,
        turn: int,
        turn_phase: str,
        ended: bool,
        ending_status: str,
        metrics: Mapping[str, object],
        commit: bool = True,
    ) -> None:
        """Write the reign header and every balance metric."""
        self._conn.execute(
            "INSERT INTO game_state (id, year, period, turn, turn_phase, ended, ending_status) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET year = excluded.year, period = excluded.period, "
            "turn = excluded.turn, turn_phase = excluded.turn_phase, "
            "ended = excluded.ended, ending_status = excluded.ending_status",
            (
                int(year), int(period), int(turn), str(turn_phase),
                1 if ended else 0, str(ending_status),
            ),
        )
        self._conn.executemany(
            "INSERT INTO metrics (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(str(key), int(value)) for key, value in metrics.items()],
        )
        # Commit whenever asked: the writes above open an implicit transaction of
        # their own, and this is the save-slot write port — callers that own a
        # transaction pass commit=False (or hold the suspension flag, which
        # neutralises conn.commit).
        if commit:
            self._conn.commit()

    def read(self) -> Optional[Dict[str, object]]:
        """The reign header, or None when this save has never been initialized."""
        row = self._conn.execute(
            "SELECT year, period, turn, turn_phase, ended, ending_status "
            "FROM game_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        keys = row.keys()
        return {
            "year": int(row["year"]),
            "period": int(row["period"]),
            "turn": int(row["turn"]),
            "turn_phase": str(row["turn_phase"] or "summoning"),
            "ended": bool(row["ended"]) if "ended" in keys else False,
            "ending_status": str(row["ending_status"] or "") if "ending_status" in keys else "",
        }

    def read_metrics(self) -> Dict[str, int]:
        """Every stored balance metric, keyed by name."""
        return {
            str(row["key"]): int(row["value"])
            for row in self._conn.execute("SELECT key, value FROM metrics").fetchall()
        }

    def upsert_metric(self, key: str, value: int) -> None:
        """Write one balance. Does not commit; the caller owns the transaction."""
        self._conn.execute(
            "INSERT INTO metrics (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(key), int(value)),
        )

    def insert_ledger(self, row: Mapping[str, object]) -> None:
        """Append one economy_ledger row. Optional columns default in the table."""
        unknown = set(row) - _LEDGER_COLUMNS
        if unknown:
            raise ValueError(f"economy_ledger 列非法：{sorted(unknown)}")
        columns = [column for column in _LEDGER_ORDER if column in row]
        if not columns:
            raise ValueError("economy_ledger insert needs fields")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO economy_ledger ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )
