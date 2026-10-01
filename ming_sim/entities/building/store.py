"""Building rows and the building change log.

#1889: one write port. Id generation, clamps and field legality stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping


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
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"buildings 列非法：{sorted(unknown)}")
    return [column for column in sorted(values)]


class BuildingStore:
    """Single write port for a building and its change log."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def count_in_region(self, region_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM buildings WHERE region_id = ?", (region_id,),
        ).fetchone()
        return int(row[0])

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
        unknown = set(row) - set(_LOG_COLUMNS)
        if unknown:
            raise ValueError(f"building_logs 列非法：{sorted(unknown)}")
        self._conn.execute(
            "INSERT INTO building_logs "
            "(turn, year, period, building_id, field, old_value, new_value, delta, "
            "reason, event_id, edict_id, actor, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row.get(column) for column in _LOG_COLUMNS),
        )

    def upsert(self, row: Mapping[str, object]) -> None:
        """Debug replace of one building. Caller commits."""
        allowed = BUILDING_COLUMNS | {"updated_at"}
        if "id" not in row or row["id"] in (None, ""):
            raise ValueError("缺主键 id")
        columns = _checked(row, allowed=allowed)
        assignments = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != "id"
        )
        action = f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO buildings ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) {action}",
            [row[column] for column in columns],
        )
