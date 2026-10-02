"""Army rows and the army change log.

#1889: one write port. Pay formulas and the integers they produce stay with the
caller; this module does not compute a shortfall month.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ming_sim.entities.column_write import checked_columns, upsert_by_pk


ARMY_COLUMNS = frozenset({
    "id", "name", "station", "station_region", "theater", "commander",
    "controller", "troop_type", "manpower", "supply", "morale", "training",
    "equipment", "province_pay_arrears", "central_pay_arrears",
    "consecutive_pay_shortfall_months", "pay_source_region",
    "province_pay_share", "central_pay_share", "is_tusi", "self_funded_pay",
    "mutiny_status", "is_mutinied", "mutiny_count", "mutiny_probation",
    "full_pay_streak", "redemption_count", "mobility", "loyalty",
    "firearm_equipment", "cannon_equipment", "salary_rate", "status",
    "owner_power",
})

_MUTABLE_COLUMNS = ARMY_COLUMNS - {"id"}

_LOG_COLUMNS = (
    "turn", "year", "period", "army_id", "field", "old_value", "new_value",
    "delta", "reason", "event_id", "edict_id", "actor", "origin_ref",
)


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="armies")


class ArmyStore:
    """Single write port for an army and its change log."""

    def ordered_ids(self) -> list[str]:
        return [str(row["id"]) for row in self._conn.execute("SELECT id FROM armies ORDER BY id").fetchall()]

    def field_row(self, field: str, army_id: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM armies WHERE id=?", (army_id,)).fetchone()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(
        self, army_id: str, values: Mapping[str, object], *, touch: bool = True,
    ) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
        if not columns and not touch:
            raise ValueError("armies update needs fields")
        parts = [f"{column}=?" for column in columns]
        params: list[object] = [values[column] for column in columns]
        if touch:
            parts.append("updated_at=CURRENT_TIMESTAMP")
        cursor = self._conn.execute(
            f"UPDATE armies SET {', '.join(parts)} WHERE id=?",
            [*params, army_id],
        )
        return int(cursor.rowcount or 0)

    def insert(self, row: Mapping[str, object]) -> None:
        if "id" not in row:
            raise ValueError("armies insert needs id")
        columns = _checked(row, allowed=ARMY_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO armies ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def append_log(self, row: Mapping[str, object]) -> None:
        self.append_logs((row,))

    def append_logs(self, rows: Sequence[Mapping[str, object]]) -> None:
        payload = []
        for row in rows:
            checked_columns(row, set(_LOG_COLUMNS), what="army_logs")
            payload.append(tuple(
                "" if column == "origin_ref" and column not in row else row.get(column)
                for column in _LOG_COLUMNS
            ))
        if not payload:
            return
        self._conn.executemany(
            "INSERT INTO army_logs "
            "(turn, year, period, army_id, field, old_value, new_value, delta, "
            "reason, event_id, edict_id, actor, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            payload,
        )

    def upsert(self, row: Mapping[str, object]) -> None:
        """Debug replace of one army. Caller commits."""
        upsert_by_pk(
            self._conn, "armies", row,
            pk="id", allowed=ARMY_COLUMNS | {"updated_at"}, what="armies",
        )

    def delete(self, army_id: str) -> int:
        cursor = self._conn.execute("DELETE FROM armies WHERE id=?", (army_id,))
        return int(cursor.rowcount or 0)

    def read_assert_commission_grant_target_exists(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM armies WHERE id=?', params).fetchone()

    def read_apply_extracted_army_delta(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT cannon_equipment, is_mutinied FROM armies WHERE id=?', params).fetchone()

    def row(self, army_id: str) -> Any:
        return self._conn.execute('SELECT * FROM armies WHERE id = ?', (army_id,)).fetchone()

    def read_initialize_army_pay_source_spine(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            SELECT id, owner_power, arrears, pay_source_region,\n                   province_pay_share, central_pay_share, is_tusi, self_funded_pay\n            FROM armies\n            ORDER BY id\n            ', params).fetchall()

    def read_has_complete_province_pay_containers(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT DISTINCT pay_source_region\n            FROM armies\n            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n              AND pay_source_region != ''\n              AND (province_pay_share > 0 OR province_pay_arrears > 0)\n            ", params).fetchall()

    def read_assert_army_pay_source_container_conservation(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT id, province_pay_share, central_pay_share,\n                   province_pay_arrears, central_pay_arrears, arrears\n            FROM armies\n            WHERE (owner_power != 'ming' OR is_tusi != 0 OR self_funded_pay != 0)\n              AND (\n                ABS(COALESCE(province_pay_share, 0)) > 1e-9 OR\n                ABS(COALESCE(central_pay_share, 0)) > 1e-9 OR\n                ABS(COALESCE(province_pay_arrears, 0)) > 1e-9 OR\n                ABS(COALESCE(central_pay_arrears, 0)) > 1e-9 OR\n                ABS(COALESCE(arrears, 0)) > 1e-9\n              )\n            ORDER BY id\n            LIMIT 1\n            ", params).fetchone()

    def read_assert_army_pay_source_container_conservation_id_pay_source_region(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT id, pay_source_region\n            FROM armies\n            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n              AND (\n                ABS(COALESCE(province_pay_share, 0)) > 1e-9 OR\n                ABS(COALESCE(province_pay_arrears, 0)) > 1e-9\n              )\n            ORDER BY id\n            ", params).fetchall()

    def read_assert_army_pay_source_container_conservation_COALESCE_SUM_province_pay_arrears_0_AS_province_total_COALESCE_SU(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT\n              COALESCE(SUM(province_pay_arrears), 0) AS province_total,\n              COALESCE(SUM(central_pay_arrears), 0) AS central_total,\n              COALESCE(SUM(arrears), 0) AS army_total\n            FROM armies\n            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n            ", params).fetchone()

    def read_army_pay_source_rows_for_region(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT id, name, manpower, salary_rate, owner_power, pay_source_region, morale,\n                   province_pay_share, central_pay_share, province_pay_arrears,\n                   central_pay_arrears, is_tusi, self_funded_pay\n            FROM armies\n            WHERE pay_source_region = ? AND owner_power = 'ming'\n              AND is_tusi = 0 AND self_funded_pay = 0\n              AND province_pay_share > 0\n            ORDER BY id\n            ", params).fetchall()

    def read_army_report(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT SUM(manpower) AS total FROM armies', params).fetchone()

    def read_army_detail(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM armies WHERE id = ? OR name = ?', params).fetchone()

    def read_army_roster(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM armies ORDER BY owner_power='ming' DESC, theater, name", params).fetchall()

    def read_turn_army_summary(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            SELECT al.*, a.name AS army_name\n            FROM army_logs al\n            JOIN armies a ON a.id = al.army_id\n            WHERE al.turn = ?\n            ORDER BY CASE\n                       WHEN al.delta IS NULL THEN 0\n                       WHEN al.delta != 0 THEN 0\n                       ELSE 1\n                     END, al.id\n            LIMIT ?\n            ', params).fetchall()

    def read_apply_military_order_station_effect(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM armies WHERE id = ?', params).fetchone()

    def read_reconcile_central_army_pay_arrears_container(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT COALESCE(SUM(central_pay_arrears), 0) AS total\n            FROM armies\n            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n            ", params).fetchone()

    def read_apply_region_army_pay_tick(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT consecutive_pay_shortfall_months FROM armies WHERE id = ?', params).fetchone()

    def read_reconcile_region_army_pay_container(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT COALESCE(SUM(province_pay_arrears), 0) AS total\n            FROM armies\n            WHERE pay_source_region = ? AND owner_power = 'ming'\n              AND is_tusi = 0 AND self_funded_pay = 0\n            ", params).fetchone()

    def ordered_rows(self, *, limit: int | None = None) -> Any:
        sql = "SELECT * FROM armies ORDER BY theater, name"
        params = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self._conn.execute(sql, params).fetchall()

    def read_army_rows(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM armies', params).fetchall()

    def read_create_armies_from_extraction(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, name FROM armies WHERE id = ? OR name = ?', params).fetchone()

    def read_apply_dossier_promulgation(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT arrears FROM armies WHERE id=?', params).fetchone()

    def read_build_translation_target_grounding(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, name FROM armies ORDER BY id', params).fetchall()

    def read_due_order_displacement_entries(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT COALESCE(SUM(CASE WHEN CAST(new_value AS REAL)>CAST(old_value AS REAL) THEN CAST(new_value AS REAL)-CAST(old_value AS REAL) ELSE 0 END),0) AS v FROM army_logs WHERE turn=? AND field='province_pay_arrears' AND army_id IN (SELECT id FROM armies WHERE pay_source_region=?)", params).fetchone()

    def read_arrears_order_displacement_entries(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT COALESCE(SUM(CASE WHEN CAST(old_value AS REAL)>CAST(new_value AS REAL) THEN CAST(old_value AS REAL)-CAST(new_value AS REAL) ELSE 0 END),0) AS v FROM army_logs WHERE turn=? AND field='province_pay_arrears' AND army_id IN (SELECT id FROM armies WHERE pay_source_region=?)", params).fetchone()

    def read_build_fiscal_fact_brief(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, name, owner_power, manpower, salary_rate, pay_source_region, station_region, central_pay_share, province_pay_share, province_pay_arrears, central_pay_arrears FROM armies ORDER BY rowid', params).fetchall()

    def read_build_fiscal_fact_brief_id_army_id_old_value_new_value(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, army_id, old_value, new_value FROM army_logs WHERE turn = ? AND field = 'province_pay_arrears' ORDER BY id", params).fetchall()

    def read_compute_budget_lines(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT id, manpower, salary_rate, owner_power, central_pay_share,\n               pay_source_region\n        FROM armies\n        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n          AND central_pay_share > 0\n        ", params).fetchall()

    def read_auto_pay_arrears_by_priority(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM armies WHERE owner_power='ming' AND arrears>0", params).fetchall()

    def read_apply_fixed_period_flows(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT id, name, manpower, salary_rate, owner_power, arrears, morale, loyalty,\n               pay_source_region, province_pay_share, central_pay_share,\n               province_pay_arrears, central_pay_arrears, is_tusi, self_funded_pay\n        FROM armies\n        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n          AND central_pay_share > 0\n        ", params).fetchall()

    def read_apply_fixed_period_flows_id_manpower_salary_rate_owner_power_is_mutinied_mutiny_count(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, manpower, salary_rate, owner_power, is_mutinied, mutiny_count FROM armies', params).fetchall()

    def read_apply_fixed_period_flows_id_name_manpower_salary_rate_owner_power_arrears_province_pay_arr(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT id, name, manpower, salary_rate, owner_power,\n                   arrears, province_pay_arrears, central_pay_arrears,\n                   loyalty, is_tusi, self_funded_pay, is_mutinied,\n                   mutiny_count, mutiny_probation, full_pay_streak, redemption_count\n            FROM armies\n            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0\n            ", params).fetchall()

    def read_army_register(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name,manpower FROM armies WHERE owner_power='ming' ORDER BY name", params).fetchall()

    def read_world(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id,name FROM armies WHERE commander=? OR controller=? ORDER BY name', params).fetchall()

    def read_revision_rows(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, name, station FROM armies WHERE owner_power='ming' ORDER BY name", params)
