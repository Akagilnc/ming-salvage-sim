"""Class rows and the population-transfer ledger.

#1889: one write port. Satisfaction clamps and transfer amounts stay with the caller.
The package is named ``social_class`` because ``class`` is a Python keyword.
"""

from __future__ import annotations

from typing import Any


class ClassStore:
    """Single write port for a class row and a population transfer."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

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

    def set_satisfaction_leverage(
        self,
        *,
        name: str,
        region_id: str,
        satisfaction: object,
        leverage: object,
    ) -> None:
        self._conn.execute(
            "UPDATE classes SET satisfaction = ?, leverage = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE name = ? AND region_id = ?",
            (satisfaction, leverage, name, region_id),
        )

    def add_population(self, *, name: str, region_id: str, delta: object) -> None:
        """Apply a signed population delta. The caller has already capped it."""
        self._conn.execute(
            "UPDATE classes SET population = population + ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE name = ? AND region_id = ?",
            (delta, name, region_id),
        )

    def append_transfer(
        self,
        *,
        turn: int,
        source: str,
        target: str,
        amount: int,
        reason: str,
        origin_ref: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO population_transfer_ledger "
            "(turn, source, target, amount, reason, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(turn), source, target, int(amount), reason, origin_ref),
        )
