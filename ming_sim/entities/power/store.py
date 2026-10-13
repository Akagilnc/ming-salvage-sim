"""Power rows and the two power logs.

#1889: one write port. Field clamps and per-item rejection stay with the caller.
"""

from __future__ import annotations

from typing import Any

from ming_sim.entities.column_write import RowStore


class PowerStore(RowStore):
    """Single write port for a power and its logs."""

    TABLE = "powers"
    PK = "id"
    TABLES = {}
    TOUCH = True
    REQUIRE_INSERT_PK = True
    LOG_SQL = """INSERT INTO power_logs (turn, year, period, power_id, field, old_value, new_value, delta, reason, origin_ref)
        VALUES (:turn, :year, :period, :power_id, :field, :old_value, :new_value, :delta, :reason, :origin_ref)"""

    def rows(self, exclude_self: bool = False) -> Any:
        where = "WHERE id != 'ming'" if exclude_self else ""
        return self._conn.execute(
            f"SELECT * FROM powers {where} ORDER BY CASE id "
            "WHEN 'ming' THEN 0 WHEN 'houjin' THEN 1 WHEN 'mongol' THEN 2 "
            "WHEN 'korea' THEN 3 WHEN 'japan' THEN 4 WHEN 'dutch' THEN 5 "
            "WHEN 'bandits' THEN 6 ELSE 9 END, name",
        ).fetchall()

    def display_name(self, power_id: str) -> str:
        row = self.row(str(power_id), fields="name")
        return str(row["name"]) if row else str(power_id)

    def ids(self) -> Any:
        return self._conn.execute("SELECT id FROM powers", ()).fetchall()
