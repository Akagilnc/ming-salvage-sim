"""Power rows and the two power logs.

#1889: one write port. Field clamps and per-item rejection stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.entities.column_write import checked_columns


POWER_COLUMNS = frozenset({
    "id", "name", "kind", "leader", "stance", "leverage", "satisfaction",
    "military_strength", "cohesion", "supply", "agenda", "status",
    "last_action", "aliases",
})

_MUTABLE_COLUMNS = POWER_COLUMNS - {"id"}

_LOG_COLUMNS = (
    "turn", "year", "period", "power_id", "field", "old_value", "new_value",
    "delta", "reason", "origin_ref",
)

_NAME_LOG_COLUMNS = (
    "turn", "year", "period", "power_id", "old_name", "new_name",
    "old_aliases", "new_aliases", "reason",
)


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="powers")


class PowerStore:
    """Single write port for a power and its logs."""

    def rows(self, exclude_self: bool = False) -> Any:
        where = "WHERE id != 'ming'" if exclude_self else ""
        return self._conn.execute(
            f"SELECT * FROM powers {where} ORDER BY CASE id "
            "WHEN 'ming' THEN 0 WHEN 'houjin' THEN 1 WHEN 'mongol' THEN 2 "
            "WHEN 'korea' THEN 3 WHEN 'japan' THEN 4 WHEN 'dutch' THEN 5 "
            "WHEN 'bandits' THEN 6 ELSE 9 END, name",
        ).fetchall()

    def field_row(self, field: str, power_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM powers WHERE id=?", (power_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert_ignore(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("powers insert needs id")
        columns = _checked(row, allowed=POWER_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT OR IGNORE INTO powers ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def update(self, power_id: str, values: Mapping[str, object]) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
        if not columns:
            raise ValueError("powers update needs fields")
        assignments = ", ".join(f"{column}=?" for column in columns)
        cursor = self._conn.execute(
            f"UPDATE powers SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [values[column] for column in columns] + [power_id],
        )
        return int(cursor.rowcount or 0)

    def append_log(self, row: Mapping[str, object]) -> None:
        checked_columns(row, set(_LOG_COLUMNS), what="power_logs")
        self._conn.execute(
            "INSERT INTO power_logs "
            "(turn, year, period, power_id, field, old_value, new_value, delta, "
            "reason, origin_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row.get(column) for column in _LOG_COLUMNS),
        )

    def append_name_log(self, row: Mapping[str, object]) -> None:
        checked_columns(row, set(_NAME_LOG_COLUMNS), what="power_name_logs")
        self._conn.execute(
            "INSERT INTO power_name_logs "
            "(turn, year, period, power_id, old_name, new_name, old_aliases, "
            "new_aliases, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row.get(column) for column in _NAME_LOG_COLUMNS),
        )

    def read_load_pending_gate_power_shadow_rows(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, leverage, military_strength, supply FROM powers', params).fetchall()

    def read_apply_bandit_absorptions(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM powers WHERE id=?', params).fetchone()

    def read_apply_issue_entities(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM powers WHERE id=?', params).fetchone()

    def read_strategic_event_result_preflight_error(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM powers WHERE id = ? LIMIT 1', params).fetchone()

    def read_apply_power_rename(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM powers WHERE id = ?', params).fetchone()

    def read_power_display_name(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM powers WHERE id = ?', params).fetchone()

    def read_find_pacification_target(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT kind, leader, stance FROM powers WHERE id=?', params).fetchone()

    def read_apply_character_power_changes(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM powers', params).fetchall()
