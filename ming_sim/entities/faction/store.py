"""Faction rows.

#1889: one write port. Leverage formulas and clamps stay with the caller.
"""

from __future__ import annotations

from typing import Any

from ming_sim.entities.column_write import RowStore


class FactionStore(RowStore):
    """Single write port for factions."""

    TABLE = "factions"
    PK = "name"
    TABLES = {"factions": "name"}

    def faction_satisfaction(self, faction: str) -> int:
        row = self.row(faction, fields="satisfaction")
        return int(row["satisfaction"]) if row else 50

    def faction_leverage(self, faction: str) -> int:
        row = self.row(faction, fields="leverage")
        return int(row["leverage"]) if row else 50

    def names(self) -> Any:
        return self._conn.execute("SELECT name FROM factions", ()).fetchall()

    def get_faction_stance_summaries(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM faction_stance_summaries ORDER BY faction", ()
        ).fetchall()
        return [dict(row) for row in rows]
