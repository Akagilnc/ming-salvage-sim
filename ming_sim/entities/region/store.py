"""Region rows and the region change log.

#1889: one write port. Field choice and the numbers written stay with the caller.
"""

from __future__ import annotations

from typing import Any

from ming_sim.entities.column_write import RowStore


class RegionStore(RowStore):
    """Single write port for a region and its change log."""

    TABLE = "regions"
    PK = "id"
    TABLES = {}
    TOUCH = True
    TOUCH_EMPTY = True
    REQUIRE_INSERT_PK = True
    LOG_SQL = """INSERT INTO region_logs (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor, origin_ref)
        VALUES (:turn, :year, :period, :region_id, :field, :old_value, :new_value, :delta, :reason, :event_id, :edict_id, :actor, :origin_ref)"""

    def rows(self, *, limit: int | None = None, danger_order: bool = False) -> list[Any]:
        """Region sheet. Danger order is the materials view; name order is the roster."""
        order = (
            "(unrest + military_pressure + gentry_resistance + (100 - public_support)) "
            "DESC, name"
            if danger_order
            else "kind DESC, name"
        )
        sql = f"SELECT * FROM regions ORDER BY {order}"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self._conn.execute(sql, params).fetchall()

    def ordered_ming_fiscal_rows(self) -> Any:
        return self._conn.execute(
            "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id",
            (),
        ).fetchall()

    def ming_fiscal_rows(self) -> Any:
        return self._conn.execute(
            "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'", ()
        ).fetchall()
