"""Class rows and the population-transfer ledger.

#1889: one write port. Satisfaction clamps and transfer amounts stay with the caller.
The package is named ``social_class`` because ``class`` is a Python keyword.
"""

from __future__ import annotations

from typing import Any


from ming_sim.entities.column_write import RowStore


class ClassStore(RowStore):
    """Single write port for a class row and a population transfer."""

    TABLE = "classes"
    PK = ("name", "region_id")

    def names(self) -> Any:
        return self._conn.execute("SELECT DISTINCT name FROM classes")

    def ordered_names(self) -> Any:
        return self._conn.execute(
            "SELECT DISTINCT name FROM classes ORDER BY name",
        ).fetchall()

    def subtract_population(self, amount: int, name: str, region_id: str) -> Any:
        return self._conn.execute(
            "UPDATE classes SET population = population - ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE name=? AND region_id=?",
            (amount, name, region_id),
        )

    def record_population_transfer(
        self, source_class: str, source_region: str,
        target_class: str, target_region: str, amount: int,
        *, turn: int, source: str, target: str, reason: str, origin_ref: str,
    ) -> None:
        """Write both population stocks and their one transfer in the caller's transaction."""
        self.subtract_population(amount, source_class, source_region)
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
