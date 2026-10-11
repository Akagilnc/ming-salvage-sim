"""Class rows and the population-transfer ledger.

#1889: one write port. Satisfaction clamps and transfer amounts stay with the caller.
The package is named ``social_class`` because ``class`` is a Python keyword.
"""

from __future__ import annotations

from typing import Any


class ClassStore:
    """Single write port for a class row and a population transfer."""

    def field_row(self, field: str, name: str, region_id: str) -> Any:
        """Read a schema field already validated by the gate consumer."""
        return self._conn.execute(
            f"SELECT {field} FROM classes WHERE name=? AND region_id=?", (name, region_id),
        ).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def has_any(self) -> bool:
        return self._conn.execute("SELECT 1 FROM classes LIMIT 1").fetchone() is not None

    def insert(
        self,
        *,
        name: str,
        region_id: str,
        population: object,
        satisfaction: object,
        leverage: object,
        agenda: object,
    ) -> None:
        self._conn.execute(
            "INSERT INTO classes "
            "(name, region_id, population, satisfaction, leverage, agenda) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, region_id, population, satisfaction, leverage, agenda),
        )

    def read_surcharge_population_pool_members(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name FROM classes WHERE region_id=? AND name IN ('农民', '流民')", params).fetchall()

    def read_class_rows(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, region_id, population, satisfaction, leverage, agenda FROM classes WHERE region_id = ? ORDER BY name', params).fetchall()

    def read_names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT DISTINCT name FROM classes', params)
