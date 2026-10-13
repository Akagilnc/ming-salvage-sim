"""Building rows and the building change log.

#1889: one write port. Clamps and field legality stay with the caller.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ming_sim.entities.column_write import RowStore


class BuildingStore(RowStore):
    """Single write port for a building and its change log."""

    TABLE = "buildings"
    PK = "id"
    TABLES = {}
    TOUCH = True
    REQUIRE_INSERT_PK = True
    LOG_SQL = """INSERT INTO building_logs (turn, year, period, building_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor, origin_ref)
        VALUES (:turn, :year, :period, :building_id, :field, :old_value, :new_value, :delta, :reason, :event_id, :edict_id, :actor, :origin_ref)"""

    def insert_new(self, row: Mapping[str, object]) -> str:
        """Allocate a free regional identity and insert the validated building."""
        region_id = row["region_id"]
        base = re.sub(r"[^a-z0-9]+", "", (region_id or "rgn").lower()) or "rgn"
        seq = int(self._conn.execute(
            "SELECT COUNT(*) FROM buildings WHERE region_id = ?", (region_id,),
        ).fetchone()[0])
        building_id = f"{base}_b{seq + 1}"
        while self.row(building_id) is not None:
            seq += 1
            building_id = f"{base}_b{seq + 1}"
        self.insert({**row, "id": building_id})
        return building_id

    def region_rows(self, region_id: object) -> Any:
        return self._conn.execute(
            "SELECT * FROM buildings WHERE region_id = ? ORDER BY category, name",
            (region_id,),
        ).fetchall()

    def rows(self) -> Any:
        return self._conn.execute(
            "SELECT * FROM buildings ORDER BY region_id, category, name", ()
        ).fetchall()
