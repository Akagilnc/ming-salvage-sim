"""Building rows and the building change log.

#1889: one write port. Id generation, clamps and field legality stay with the caller.
"""

from __future__ import annotations

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


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="buildings")


class BuildingStore:
    """Single write port for a building and its change log."""

    def field_row(self, field: str, building_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM buildings WHERE id=?", (building_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def count_in_region(self, region_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM buildings WHERE region_id = ?", (region_id,),
        ).fetchone()
        return int(row[0])

    def has_any(self) -> bool:
        return self._conn.execute("SELECT 1 FROM buildings LIMIT 1").fetchone() is not None

    def exists(self, building_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM buildings WHERE id = ?", (building_id,),
        ).fetchone() is not None

    def get(self, building_id: str) -> Any:
        return self._conn.execute(
            "SELECT * FROM buildings WHERE id = ?", (building_id,),
        ).fetchone()

    def insert(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("buildings insert needs id")
        columns = _checked(row, allowed=BUILDING_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO buildings ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def update(self, building_id: str, values: Mapping[str, object]) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
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
