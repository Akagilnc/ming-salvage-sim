"""Region rows and the region change log.

#1889: one write port. Field choice and the numbers written stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ming_sim.entities.column_write import checked_columns


REGION_COLUMNS = frozenset({
    "id", "name", "kind", "population", "public_support", "unrest",
    "natural_disaster", "human_disaster", "registered_land", "hidden_land",
    "tax_per_turn", "grain_security", "gentry_resistance", "military_pressure",
    "status", "controlled_by", "city_level", "cannon", "fiscal",
})

_MUTABLE_COLUMNS = REGION_COLUMNS - {"id"}

_LOG_COLUMNS = (
    "turn", "year", "period", "region_id", "field", "old_value", "new_value",
    "delta", "reason", "event_id", "edict_id", "actor", "origin_ref",
)


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="regions")


class RegionStore:
    """Single write port for a region and its change log."""

    def field_row(self, field: str, region_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM regions WHERE id=?", (region_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(
        self, region_id: str, values: Mapping[str, object], *, touch: bool = True,
    ) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
        if not columns and not touch:
            raise ValueError("regions update needs fields")
        parts = [f"{column}=?" for column in columns]
        params: list[object] = [values[column] for column in columns]
        if touch:
            parts.append("updated_at=CURRENT_TIMESTAMP")
        cursor = self._conn.execute(
            f"UPDATE regions SET {', '.join(parts)} WHERE id=?",
            [*params, region_id],
        )
        return int(cursor.rowcount or 0)

    def insert_ignore(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("regions insert needs id")
        columns = _checked(row, allowed=REGION_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT OR IGNORE INTO regions ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def append_log(self, row: Mapping[str, object]) -> None:
        self.append_logs((row,))

    def append_logs(self, rows: Sequence[Mapping[str, object]]) -> None:
        payload = []
        for row in rows:
            checked_columns(row, set(_LOG_COLUMNS), what="region_logs")
            payload.append(tuple(row.get(column) for column in _LOG_COLUMNS))
        if not payload:
            return
        self._conn.executemany(
            "INSERT INTO region_logs "
            "(turn, year, period, region_id, field, old_value, new_value, delta, "
            "reason, event_id, edict_id, actor, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            payload,
        )

    def rows(self, *, limit: int | None = None, danger_order: bool = False) -> list[Any]:
        """Region sheet. Danger order is the materials view; name order is the roster."""
        order = (
            "(unrest + military_pressure + gentry_resistance + (100 - public_support)) "
            "DESC, name"
            if danger_order
            else "kind DESC, name"
        )
        sql = f"SELECT * FROM regions ORDER BY {order}"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self._conn.execute(sql, params).fetchall()


    def delete(self, region_id: str) -> int:
        cursor = self._conn.execute("DELETE FROM regions WHERE id=?", (region_id,))
        return int(cursor.rowcount or 0)

    def row(self, region_id: str) -> Any:
        return self._conn.execute('SELECT * FROM regions WHERE id = ?', (region_id,)).fetchone()
