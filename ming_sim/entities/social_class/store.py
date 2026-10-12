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

    def names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT DISTINCT name FROM classes', params)

    def ordered_names(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT DISTINCT name FROM classes ORDER BY name", params
        ).fetchall()

    def population_row(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT population FROM classes WHERE name=? AND region_id=?", params
        ).fetchone()

    def subtract_population(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE classes SET population = population - ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE name=? AND region_id=?",
            params,
        )

    def record_population_transfer(
        self, source_class: str, source_region: str,
        target_class: str, target_region: str, amount: int,
        *, turn: int, source: str, target: str, reason: str, origin_ref: str,
    ) -> None:
        """Write both population stocks and their one transfer in the caller's transaction."""
        self.subtract_population((amount, source_class, source_region))
        self._conn.execute(
            "UPDATE classes SET population = population + ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE name=? AND region_id=?",
            (amount, target_class, target_region),
        )
        self._conn.execute(
            "INSERT INTO population_transfer_ledger "
            "(turn, source, target, amount, reason, origin_ref) VALUES (?, ?, ?, ?, ?, ?)",
            (turn, source, target, amount, reason, origin_ref),
        )
