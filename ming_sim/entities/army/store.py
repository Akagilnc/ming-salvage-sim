"""Army rows and the army change log.

#1889: one write port. Pay formulas and the integers they produce stay with the
caller; this module does not compute a shortfall month.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


ARMY_COLUMNS = frozenset({
    "id", "name", "station", "station_region", "theater", "commander",
    "controller", "troop_type", "manpower", "supply", "morale", "training",
    "equipment", "arrears", "province_pay_arrears", "central_pay_arrears",
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


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"armies 列非法：{sorted(unknown)}")
    return [column for column in sorted(values)]


class ArmyStore:
    """Single write port for an army and its change log."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(
        self, army_id: str, values: Mapping[str, object], *, touch: bool = True,
    ) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
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
        columns = _checked(row, allowed=ARMY_COLUMNS)
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
            unknown = set(row) - set(_LOG_COLUMNS)
            if unknown:
                raise ValueError(f"army_logs 列非法：{sorted(unknown)}")
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

    def upsert(self, row: Mapping[str, object]) -> None:
        """Debug replace of one army. Caller commits."""
        allowed = ARMY_COLUMNS | {"updated_at"}
        if "id" not in row or row["id"] in (None, ""):
            raise ValueError("缺主键 id")
        columns = _checked(row, allowed=allowed)
        assignments = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != "id"
        )
        action = f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO armies ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) {action}",
            [row[column] for column in columns],
        )

    def delete(self, army_id: str) -> int:
        cursor = self._conn.execute("DELETE FROM armies WHERE id=?", (army_id,))
        return int(cursor.rowcount or 0)
