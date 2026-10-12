"""Army rows and the army change log.

#1889: one write port. Pay formulas and the integers they produce stay with the
caller; this module does not compute a shortfall month.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ming_sim.entities.column_write import checked_columns


ARMY_COLUMNS = frozenset({
    "id", "name", "station", "station_region", "theater", "commander",
    "controller", "troop_type", "manpower", "supply", "morale", "training",
    "equipment", "province_pay_arrears", "central_pay_arrears",
    "consecutive_pay_shortfall_months", "pay_source_region",
    "province_pay_share", "central_pay_share", "is_tusi", "self_funded_pay",
    "mutiny_status", "is_mutinied", "mutiny_count", "mutiny_probation",
    "full_pay_streak", "redemption_count", "mobility", "loyalty",
    "firearm_equipment", "cannon_equipment", "salary_rate", "status",
    "owner_power",
})

_MUTABLE_COLUMNS = ARMY_COLUMNS - {"id"}

_LOG_COLUMNS = (
    "turn", "year", "period", "army_id", "field", "old_value", "new_value",
    "delta", "reason", "event_id", "edict_id", "actor", "origin_ref",
)




class ArmyStore:
    """Single write port for an army and its change log."""

    def field_row(self, field: str, army_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM armies WHERE id=?", (army_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(
        self, army_id: str, values: Mapping[str, object], *, touch: bool = True,
    ) -> int:
        columns = checked_columns(values, _MUTABLE_COLUMNS, what="armies")
        if not columns and not touch:
            raise ValueError("armies update needs fields")
        parts = [f"{column}=?" for column in columns]
        params: list[object] = [values[column] for column in columns]
        if touch:
            parts.append("updated_at=CURRENT_TIMESTAMP")
        cursor = self._conn.execute(
            f"UPDATE armies SET {', '.join(parts)} WHERE id=?",
            [*params, army_id],
        )
        return int(cursor.rowcount or 0)

    def insert(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("armies insert needs id")
        columns = checked_columns(row, ARMY_COLUMNS, what="armies")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO armies ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def append_log(self, row: Mapping[str, object]) -> None:
        self.append_logs((row,))

    def append_logs(self, rows: Sequence[Mapping[str, object]]) -> None:
        payload = []
        for row in rows:
            checked_columns(row, set(_LOG_COLUMNS), what="army_logs")
            payload.append(tuple(
                "" if column == "origin_ref" and column not in row else row.get(column)
                for column in _LOG_COLUMNS
            ))
        if not payload:
            return
        self._conn.executemany(
            "INSERT INTO army_logs "
            "(turn, year, period, army_id, field, old_value, new_value, delta, "
            "reason, event_id, edict_id, actor, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            payload,
        )

    def has_any(self) -> bool:
        return self._conn.execute("SELECT 1 FROM armies LIMIT 1").fetchone() is not None

    def row(self, army_id: str) -> Any:
        return self._conn.execute('SELECT * FROM armies WHERE id = ?', (army_id,)).fetchone()

    def rows(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM armies", params).fetchall()

    def presence(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT 1 FROM armies WHERE id=?", params).fetchone()

    def cannon_mutiny_row(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT cannon_equipment, is_mutinied FROM armies WHERE id=?", params
        ).fetchone()

    def ordered_rows(self, *, limit: int | None = None) -> Any:
        sql = "SELECT * FROM armies ORDER BY theater, name"
        params = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self._conn.execute(sql, params).fetchall()
