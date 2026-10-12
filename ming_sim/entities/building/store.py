"""Building rows and the building change log.

#1889: one write port. Clamps and field legality stay with the caller.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ming_sim.entities.column_write import checked_columns


BUILDING_COLUMNS = frozenset({
    "id", "region_id", "name", "category", "level", "condition", "maintenance",
    "risk", "output_metric", "output_amount", "status", "origin", "created_turn",
})

_MUTABLE_COLUMNS = BUILDING_COLUMNS - {"id"}

_LOG_COLUMNS = (
    "turn", "year", "period", "building_id", "field", "old_value", "new_value",
    "delta", "reason", "event_id", "edict_id", "actor", "origin_ref",
)




class BuildingStore:
    """Single write port for a building and its change log."""

    def field_row(self, field: str, building_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM buildings WHERE id=?", (building_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def has_any(self) -> bool:
        return self._conn.execute("SELECT 1 FROM buildings LIMIT 1").fetchone() is not None

    def get(self, building_id: str) -> Any:
        return self._conn.execute(
            "SELECT * FROM buildings WHERE id = ?", (building_id,),
        ).fetchone()

    def insert(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("buildings insert needs id")
        columns = checked_columns(row, BUILDING_COLUMNS, what="buildings")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO buildings ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def insert_new(self, row: Mapping[str, object]) -> str:
        """Allocate a free regional identity and insert the validated building."""
        region_id = row["region_id"]
        base = re.sub(r"[^a-z0-9]+", "", (region_id or "rgn").lower()) or "rgn"
        seq = int(self._conn.execute(
            "SELECT COUNT(*) FROM buildings WHERE region_id = ?", (region_id,),
        ).fetchone()[0])
        building_id = f"{base}_b{seq + 1}"
        while self.get(building_id) is not None:
            seq += 1
            building_id = f"{base}_b{seq + 1}"
        self.insert({**row, "id": building_id})
        return building_id

    def update(self, building_id: str, values: Mapping[str, object]) -> int:
        columns = checked_columns(values, _MUTABLE_COLUMNS, what="buildings")
        if not columns:
            raise ValueError("buildings update needs fields")
        assignments = ", ".join(f"{column}=?" for column in columns)
        cursor = self._conn.execute(
            f"UPDATE buildings SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [values[column] for column in columns] + [building_id],
        )
        return int(cursor.rowcount or 0)

    def delete(self, building_id: str) -> int:
        cursor = self._conn.execute("DELETE FROM buildings WHERE id=?", (building_id,))
        return int(cursor.rowcount or 0)

    def append_log(self, row: Mapping[str, object]) -> None:
        checked_columns(row, set(_LOG_COLUMNS), what="building_logs")
        self._conn.execute(
            "INSERT INTO building_logs "
            "(turn, year, period, building_id, field, old_value, new_value, delta, "
            "reason, event_id, edict_id, actor, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row.get(column) for column in _LOG_COLUMNS),
        )

    def region_rows(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT * FROM buildings WHERE region_id = ? ORDER BY category, name",
            params,
        ).fetchall()

    def rows(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT * FROM buildings ORDER BY region_id, category, name", params
        ).fetchall()
