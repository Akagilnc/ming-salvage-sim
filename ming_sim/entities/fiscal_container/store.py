"""Named fiscal containers.

#1889: one write port. What the number means stays with the caller.
"""

from __future__ import annotations

from typing import Any


class FiscalContainerStore:
    """Single write port for ``fiscal_containers``."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def replace(self, key: str, value: float, note: str) -> None:
        self._conn.execute(
            """
            INSERT INTO fiscal_containers (key, value, note)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              note = excluded.note,
              updated_at = CURRENT_TIMESTAMP
            """,
            (key, float(value), note),
        )

    def add(self, key: str, delta: float, note: str) -> None:
        self._conn.execute(
            """
            INSERT INTO fiscal_containers (key, value, note)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = fiscal_containers.value + excluded.value,
              note = excluded.note,
              updated_at = CURRENT_TIMESTAMP
            """,
            (key, float(delta), note),
        )
