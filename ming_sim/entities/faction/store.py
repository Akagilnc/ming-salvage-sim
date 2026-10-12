"""Faction rows.

#1889: one write port. Leverage formulas and clamps stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.entities.column_write import upsert_by_pk

FACTION_COLUMNS = frozenset(
    {
        "name",
        "satisfaction",
        "leverage",
        "agenda",
        "edict_overdraw",
        "leverage_offset",
    }
)


class FactionStore:
    """Single write port for factions."""

    def has_any(self) -> bool:
        return self._conn.execute("SELECT 1 FROM factions LIMIT 1").fetchone() is not None

    def field_row(self, field: str, name: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM factions WHERE name=?", (name,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert(
        self, *, name: str, satisfaction: object, leverage: object, agenda: object,
    ) -> None:
        self._conn.execute(
            "INSERT INTO factions (name, satisfaction, leverage, agenda) "
            "VALUES (?, ?, ?, ?)",
            (name, satisfaction, leverage, agenda),
        )

    def restore_row(self, row: Mapping[str, object]) -> None:
        upsert_by_pk(
            self._conn, "factions", row,
            pk="name", allowed=FACTION_COLUMNS, what="factions",
        )

    def delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM factions WHERE name=?", (name,))

    def faction_satisfaction(self, faction: str) -> int:
        row = self.field_row('satisfaction', faction)
        return int(row["satisfaction"]) if row else 50

    def faction_leverage(self, faction: str) -> int:
        row = self.field_row('leverage', faction)
        return int(row["leverage"]) if row else 50

    def names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM factions', params).fetchall()

    def get_faction_stance_summaries(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM faction_stance_summaries ORDER BY faction", ()
        ).fetchall()
        return [dict(row) for row in rows]

    def snapshot_rows(self) -> Any:
        return self._conn.execute("SELECT * FROM factions").fetchall()
