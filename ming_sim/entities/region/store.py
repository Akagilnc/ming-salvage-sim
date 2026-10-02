"""Region rows and the region change log.

#1889: one write port. Field choice and the numbers written stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ming_sim.entities.column_write import checked_columns, upsert_by_pk


REGION_COLUMNS = frozenset({
    "id", "name", "kind", "population", "public_support", "unrest",
    "natural_disaster", "human_disaster", "registered_land", "hidden_land",
    "tax_per_turn", "grain_security", "gentry_resistance", "military_pressure",
    "status", "controlled_by", "city_level", "cannon", "fiscal",
})

_MUTABLE_COLUMNS = REGION_COLUMNS - {"id"}

_LOG_COLUMNS = (
    "turn", "year", "period", "region_id", "field", "old_value", "new_value",
    "delta", "reason", "event_id", "edict_id", "actor", "origin_ref",
)


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="regions")


class RegionStore:
    """Single write port for a region and its change log."""

    def ordered_ids(self) -> list[str]:
        return [str(row["id"]) for row in self._conn.execute("SELECT id FROM regions ORDER BY id").fetchall()]

    def field_row(self, field: str, region_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM regions WHERE id=?", (region_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(
        self, region_id: str, values: Mapping[str, object], *, touch: bool = True,
    ) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
        if not columns and not touch:
            raise ValueError("regions update needs fields")
        parts = [f"{column}=?" for column in columns]
        params: list[object] = [values[column] for column in columns]
        if touch:
            parts.append("updated_at=CURRENT_TIMESTAMP")
        cursor = self._conn.execute(
            f"UPDATE regions SET {', '.join(parts)} WHERE id=?",
            [*params, region_id],
        )
        return int(cursor.rowcount or 0)

    def insert_ignore(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("regions insert needs id")
        columns = _checked(row, allowed=REGION_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT OR IGNORE INTO regions ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def append_log(self, row: Mapping[str, object]) -> None:
        self.append_logs((row,))

    def append_logs(self, rows: Sequence[Mapping[str, object]]) -> None:
        payload = []
        for row in rows:
            checked_columns(row, set(_LOG_COLUMNS), what="region_logs")
            payload.append(tuple(row.get(column) for column in _LOG_COLUMNS))
        if not payload:
            return
        self._conn.executemany(
            "INSERT INTO region_logs "
            "(turn, year, period, region_id, field, old_value, new_value, delta, "
            "reason, event_id, edict_id, actor, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            payload,
        )

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

    def upsert(self, row: Mapping[str, object]) -> None:
        """Debug replace of one region. Caller commits."""
        upsert_by_pk(
            self._conn, "regions", row,
            pk="id", allowed=REGION_COLUMNS | {"updated_at"}, what="regions",
        )

    def delete(self, region_id: str) -> int:
        cursor = self._conn.execute("DELETE FROM regions WHERE id=?", (region_id,))
        return int(cursor.rowcount or 0)

    def read_assert_commission_grant_target_exists(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM regions WHERE id=?', params).fetchone()

    def read_apply_fiscal_levy_targets(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, fiscal FROM regions ORDER BY id', params).fetchall()

    def read_apply_levy_driven_transfers(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, fiscal, public_support FROM regions WHERE controlled_by='ming' ORDER BY id", params).fetchall()

    def read_apply_bandit_absorptions(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT controlled_by FROM regions WHERE id=?', params).fetchone()

    def read_load_pending_gate_valid_regions(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM regions', params).fetchall()

    def row(self, region_id: str) -> Any:
        return self._conn.execute('SELECT * FROM regions WHERE id = ?', (region_id,)).fetchone()

    def read_apply_surcharge_decrees(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT controlled_by, fiscal FROM regions WHERE id=?', params).fetchone()

    def read_apply_dynamic_fiscal_scale(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, fiscal FROM regions', params).fetchall()

    def read_settle_province_tick(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT fiscal FROM regions WHERE id = ?', params).fetchone()

    def read_settle_ming_province_substrate_ticks(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id", params).fetchall()

    def read_scale_tian_fu(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, tax_per_turn, fiscal FROM regions', params).fetchall()

    def read_apply_region_cannon(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT city_level, cannon FROM regions WHERE id=?', params).fetchone()

    def read_province_army_pay_container_total(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'", params).fetchall()

    def read_region_report(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT SUM(tax_per_turn) AS total FROM regions', params).fetchone()

    def read_turn_region_summary(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT rl.*, r.name AS region_name\n            FROM region_logs rl\n            JOIN regions r ON r.id = rl.region_id\n            WHERE rl.turn = ?\n              AND rl.field NOT LIKE 'settle_官俸欠_%'\n              AND rl.field NOT LIKE 'settle_宗禄欠_%'\n            ORDER BY rl.id\n            LIMIT ?\n            ", params).fetchall()

    def read_build_translation_target_grounding(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, name FROM regions ORDER BY id', params).fetchall()

    def read_due_order_displacement_entries(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT field, delta FROM region_logs WHERE turn=? AND region_id=? AND field IN ('settle_官俸欠_NewDebt','settle_宗禄欠_NewDebt')", params).fetchall()

    def read_arrears_order_displacement_entries(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT field, delta FROM region_logs WHERE turn=? AND region_id=? AND field IN ('settle_官俸欠_Repaid','settle_宗禄欠_Repaid')", params).fetchall()

    def read_build_fiscal_fact_brief(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, region_id, field, delta FROM region_logs WHERE turn = ? AND field IN ('settle_官俸欠_NewDebt', 'settle_官俸欠_Repaid',  'settle_宗禄欠_NewDebt', 'settle_宗禄欠_Repaid') ORDER BY id", params).fetchall()

    def read_victory_status(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM regions WHERE id = 'beizhili'", params).fetchone()

    def read_originated_quantity_this_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT region_id, field, new_value, delta FROM region_logs WHERE origin_ref=? AND turn=?', params).fetchall()

    def read_apply_population_transfers(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM regions WHERE id=?', params).fetchone()

    def read_resolve_single_region_id(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, kind, controlled_by FROM regions WHERE id=?', params).fetchone()

    def read_resolve_single_region_id_id_kind_controlled_by(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, kind, controlled_by FROM regions WHERE name=?', params).fetchall()
