"""Army rows and the army change log.

#1889: one write port. Pay formulas and the integers they produce stay with the
caller; this module does not compute a shortfall month.
"""

from __future__ import annotations

from typing import Any

from ming_sim.entities.column_write import RowStore


class ArmyStore(RowStore):
    """Single write port for an army and its change log."""

    TABLE = "armies"
    PK = "id"
    TABLES = {}
    TOUCH = True
    TOUCH_EMPTY = True
    REQUIRE_INSERT_PK = True
    LOG_SQL = """INSERT INTO army_logs (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor, origin_ref)
        VALUES (:turn, :year, :period, :army_id, :field, :old_value, :new_value, :delta, :reason, :event_id, :edict_id, :actor, :origin_ref)"""
    LOG_DEFAULTS = {"origin_ref": ""}

    def rows(self) -> Any:
        return self._conn.execute("SELECT * FROM armies", ()).fetchall()

    def ordered_rows(self, *, limit: int | None = None) -> Any:
        sql = "SELECT * FROM armies ORDER BY theater, name"
        params = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self._conn.execute(sql, params).fetchall()
