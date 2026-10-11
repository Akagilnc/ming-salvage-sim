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


    def value(self, key: str) -> float:
        """Scalar container read: missing row → 0.0."""
        row = self._conn.execute(
            "SELECT value FROM fiscal_containers WHERE key = ?", (str(key),)
        ).fetchone()
        return float(row["value"] or 0.0) if row is not None else 0.0

    def values_when_complete(self, keys: tuple[str, ...]) -> dict[str, float] | None:
        """All-or-nothing multi-key scalar map; incomplete key set → None."""
        rows = self.values_for(keys)
        if len(rows) != len(keys):
            return None
        values = {key: 0.0 for key in keys}
        values.update({str(row["key"]): float(row["value"] or 0.0) for row in rows})
        return values

    def read_treasury_hub_result(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "\n            SELECT key, value FROM fiscal_containers\n            WHERE key IN ('hub_京运实拨', 'hub_中央军饷实拨', 'hub_京运损耗')\n            ",
            params,
        ).fetchall()

    def write_reconcile_central_army_pay_arrears_container(
        self, params: Any = ()
    ) -> Any:
        return self._conn.execute(
            """
                INSERT INTO fiscal_containers (key, value, note)
                VALUES (?, ?, '中央军饷欠账容器：Σ非自养明军 central_pay_arrears')
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  note = excluded.note,
                  updated_at = CURRENT_TIMESTAMP
                """,
            params,
        )
