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

    def values_for(self, keys: tuple[str, ...]) -> Any:
        return self._conn.execute(
            f"SELECT key,value FROM fiscal_containers WHERE key IN ({','.join('?' for _ in keys)})", keys,
        ).fetchall()

    def read_get_central_army_pay_arrears_container(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT value FROM fiscal_containers WHERE key = ?', params).fetchone()

    def read_treasury_hub_result(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT key, value FROM fiscal_containers\n            WHERE key IN ('hub_京运实拨', 'hub_中央军饷实拨', 'hub_京运损耗')\n            ", params).fetchall()
