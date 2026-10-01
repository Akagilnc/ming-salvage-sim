"""Save-slot persistence: the reign header and the balance metrics.

#1889: 存读档的持久读写从 ``db.py`` 大块按职责拆出。The ``game_state`` row is the
reign header (which year/month/turn, and whether the game is over); the
``metrics`` table is the single source of truth for the 国库/内库 balances —
``economy_accounts`` is a read-time view derived from it, never a second copy.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from ming_sim.entities.column_write import checked_columns, upsert_by_pk


_LEDGER_ORDER = (
    "turn", "year", "period", "account", "delta", "balance_after", "category",
    "reason", "event_id", "edict_id", "actor", "purpose", "target_kind",
    "target_id", "dossier_id", "origin_ref", "beyond_intent",
)
_LEDGER_COLUMNS = frozenset(_LEDGER_ORDER)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS game_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    turn_phase TEXT NOT NULL DEFAULT 'summoning',
    ended INTEGER NOT NULL DEFAULT 0,
    ending_status TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS metrics (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


class ReignStateStore:
    """Single write port for the reign header and the balance metrics."""

    @staticmethod
    def _ledger_exclusions(prefix: str, dossier_ids: Iterable[int]) -> tuple[str, tuple]:
        clause = " AND origin_ref NOT LIKE ?" if prefix else ""
        params = (prefix + "%",) if prefix else ()
        ids = tuple(dossier_ids)
        if ids:
            marks = ','.join('?' for _ in ids)
            clause += (
                " AND NOT (origin_ref LIKE 'dossier:%' AND "
                f"CAST(substr(origin_ref,9) AS INTEGER) IN ({marks}))"
            )
        return clause, (*params, *ids)

    def ledger_totals(self, turn: int, exclude_origin_prefix: str = "", exclude_dossier_ids: Iterable[int] = ()) -> Any:
        clause, params = self._ledger_exclusions(exclude_origin_prefix, exclude_dossier_ids)
        return self._conn.execute(
            "SELECT account,SUM(CASE WHEN delta>0 THEN delta ELSE 0 END) AS income,"
            "SUM(CASE WHEN delta<0 THEN -delta ELSE 0 END) AS expense "
            f"FROM economy_ledger WHERE turn=?{clause} "
            "GROUP BY account ORDER BY account DESC", (turn, *params),
        ).fetchall()

    def recent_ledger(self, prefix: str = "", dossier_ids: Iterable[int] = (), limit: Optional[int] = None) -> Any:
        clause, params = self._ledger_exclusions(prefix, dossier_ids)
        sql = (
            "SELECT year, period, account, delta, category, reason, actor "
            f"FROM economy_ledger WHERE 1=1{clause} ORDER BY id DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params = (*params, limit)
        return self._conn.execute(sql, params).fetchall()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    def header_rows(self) -> Any:
        return self._conn.execute("SELECT * FROM game_state ORDER BY id").fetchall()

    def metric_rows(self) -> Any:
        return self._conn.execute("SELECT * FROM metrics ORDER BY key").fetchall()

    def header_row(self, row_id: object) -> Any:
        return self._conn.execute("SELECT * FROM game_state WHERE id=?", (row_id,)).fetchone()

    def metric_row(self, key: str) -> Any:
        return self._conn.execute("SELECT * FROM metrics WHERE key=?", (key,)).fetchone()

    def exists(self) -> bool:
        return self._conn.execute("SELECT 1 FROM game_state WHERE id = 1").fetchone() is not None

    def save(
        self,
        *,
        year: int,
        period: int,
        turn: int,
        turn_phase: str,
        ended: bool,
        ending_status: str,
        metrics: Mapping[str, object],
        commit: bool = True,
    ) -> None:
        """Write the reign header and every balance metric."""
        self._conn.execute(
            "INSERT INTO game_state (id, year, period, turn, turn_phase, ended, ending_status) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET year = excluded.year, period = excluded.period, "
            "turn = excluded.turn, turn_phase = excluded.turn_phase, "
            "ended = excluded.ended, ending_status = excluded.ending_status",
            (
                int(year), int(period), int(turn), str(turn_phase),
                1 if ended else 0, str(ending_status),
            ),
        )
        self._conn.executemany(
            "INSERT INTO metrics (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(str(key), int(value)) for key, value in metrics.items()],
        )
        # Commit whenever asked: the writes above open an implicit transaction of
        # their own, and this is the save-slot write port — callers that own a
        # transaction pass commit=False (or hold the suspension flag, which
        # neutralises conn.commit).
        if commit:
            self._conn.commit()

    def read(self) -> Optional[Dict[str, object]]:
        """The reign header, or None when this save has never been initialized."""
        row = self._conn.execute(
            "SELECT year, period, turn, turn_phase, ended, ending_status "
            "FROM game_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        keys = row.keys()
        return {
            "year": int(row["year"]),
            "period": int(row["period"]),
            "turn": int(row["turn"]),
            "turn_phase": str(row["turn_phase"] or "summoning"),
            "ended": bool(row["ended"]) if "ended" in keys else False,
            "ending_status": str(row["ending_status"] or "") if "ending_status" in keys else "",
        }

    def read_metrics(self) -> Dict[str, int]:
        """Every stored balance metric, keyed by name."""
        return {
            str(row["key"]): int(row["value"])
            for row in self._conn.execute("SELECT key, value FROM metrics").fetchall()
        }

    def upsert_metric(self, key: str, value: int) -> None:
        """Write one balance. Does not commit; the caller owns the transaction."""
        self._conn.execute(
            "INSERT INTO metrics (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(key), int(value)),
        )

    def delete_metric(self, key: str) -> int:
        cursor = self._conn.execute("DELETE FROM metrics WHERE key=?", (key,))
        return int(cursor.rowcount or 0)

    def upsert_header(self, row: Mapping[str, object]) -> None:
        """Debug replace of the reign header. Caller commits."""
        upsert_by_pk(
            self._conn, "game_state", row, pk="id",
            allowed=frozenset({
                "id", "year", "period", "turn", "turn_phase", "ended", "ending_status",
            }),
            what="game_state",
        )

    def delete_header(self, row_id: object) -> int:
        cursor = self._conn.execute("DELETE FROM game_state WHERE id=?", (row_id,))
        return int(cursor.rowcount or 0)

    def insert_ledger(self, row: Mapping[str, object]) -> None:
        """Append one economy_ledger row. Optional columns default in the table."""
        checked_columns(row, _LEDGER_COLUMNS, what="economy_ledger")
        columns = [column for column in _LEDGER_ORDER if column in row]
        if not columns:
            raise ValueError("economy_ledger insert needs fields")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO economy_ledger ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def read_clear_gated_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, name, clear_gate, narrative_hint FROM legacies WHERE status='active' AND clear_gate != '' AND clear_gate != '{}'", params).fetchall()

    def write_clear_gated_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("UPDATE legacies SET status='cleared' WHERE id=?", params)

    def write_sync_opening_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("UPDATE legacies\n                   SET name=?, modifiers=?, narrative_hint=?, clear_gate=?\n                   WHERE legacy_key=? AND status='active'", params)

    def read_sync_opening_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id FROM legacies WHERE legacy_key=? AND status='active'", params).fetchone()

    def write_sync_opening_legacies_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("UPDATE legacies SET status='cleared' WHERE legacy_key=? AND status='active'", params)

    def read_apply_recovery_driven_transfers(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT COALESCE(SUM(-delta), 0) FROM economy_ledger WHERE origin_ref=? AND turn=? AND delta<0', params).fetchone()

    def write_insert_legacy(self, params: Any = ()) -> Any:
        return self._conn.execute("INSERT INTO legacies\n               (name, source_issue_id, modifiers, narrative_hint,\n                start_month, duration_months, status, clear_gate, legacy_key)\n               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)", params)

    def read_current_settle_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn FROM game_state WHERE id = 1', params).fetchone()

    def read_record_claim_flow_logs(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn, year, period FROM game_state WHERE id = 1', params).fetchone()

    def read_has_meta_flag(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT value FROM metrics WHERE key=?', params).fetchone()

    def read_treasury_hub_result(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT COALESCE(SUM(-delta), 0) AS amount\n            FROM economy_ledger\n            WHERE turn = ? AND account = '国库' AND category = '边饷hub'\n            ", params).fetchone()

    def read_turn_economy_summary(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT account,\n                   SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS income,\n                   SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS expense,\n                   SUM(delta) AS net\n            FROM economy_ledger\n            WHERE turn = ? AND category <> '期初'\n            GROUP BY account\n            ORDER BY account DESC\n            ", params).fetchall()

    def read_treasury_ledger(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT turn, year, period, delta, balance_after, category, reason, actor\n            FROM economy_ledger\n            WHERE account = ? AND category <> '期初'\n            ORDER BY id DESC\n            LIMIT ?\n            ", params).fetchall()

    def read_record_dossier_decision(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn FROM game_state WHERE id=1', params).fetchone()

    def read_list_active_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM legacies WHERE status='active' ORDER BY id", params).fetchall()

    def read_expire_legacies(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, start_month, duration_months FROM legacies WHERE status='active'", params).fetchall()

    def read_legacy_modifiers(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT modifiers FROM legacies WHERE status='active' ORDER BY id", params).fetchall()

    def read_list_economy_moves_for_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM economy_ledger WHERE origin_ref=? ORDER BY id', params).fetchall()

    def read_ensure_opening_ledger(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM economy_ledger WHERE account = ? LIMIT 1', params).fetchone()

    def read_build_fiscal_fact_brief(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, delta, category, target_kind, target_id, origin_ref FROM economy_ledger WHERE turn = ? AND purpose = '补饷' AND delta < 0 ORDER BY id", params).fetchall()

    def read_spent_amount_and_fiscal_count(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT delta FROM economy_ledger WHERE origin_ref=? AND delta<0', params).fetchall()

    def read_ledger_paid_this_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT delta FROM economy_ledger WHERE origin_ref=? AND turn=? AND delta<0', params).fetchall()

    def read_scan_misappropriation(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                SELECT id, origin_ref, reason, purpose, delta FROM economy_ledger\n                WHERE turn=? AND account=? AND delta<0\n                ', params).fetchall()

    def read_had_prior_funding(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT COUNT(*) AS c FROM economy_ledger WHERE origin_ref=? AND delta<0 AND turn<=?', params).fetchone()

    def read_pay_order_grounding_facts(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn, year, period FROM game_state WHERE id=1', params).fetchone()

    def read_month_ledger(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT account, delta, category, reason, origin_ref FROM economy_ledger WHERE turn=? ORDER BY id', params)

    def read_household_ledger(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT e.year,e.period,e.delta,e.balance_after,e.category,e.reason,\n                      e.origin_ref,e.dossier_id\n               FROM economy_ledger e\n               WHERE e.account='国库' ORDER BY e.id DESC", params).fetchall()

    def read_treasury_report(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT account, balance FROM economy_accounts ORDER BY account DESC', params).fetchall()

    def read_household_ledger_balance(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT balance FROM economy_accounts WHERE account='国库'", params).fetchone()

    def write_save_ending_summary(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            INSERT INTO ending_summary (turn, year, period, ending_status, summary, timeline)\n            VALUES (?, ?, ?, ?, ?, ?)\n            ON CONFLICT(turn) DO UPDATE SET\n                year = excluded.year, period = excluded.period,\n                ending_status = excluded.ending_status,\n                summary = excluded.summary, timeline = excluded.timeline\n            ', params)

    def write_expire_legacies(self, params: Any = ()) -> Any:
        return self._conn.executemany("UPDATE legacies SET status='expired' WHERE id=?", params)

    def read_get_ending_summary(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn, year, period, ending_status, summary, timeline FROM ending_summary ORDER BY turn DESC LIMIT 1', params).fetchone()

    def read_is_pending_source_round_owned(self, params: Any) -> Any:
        return self._conn.execute("SELECT 1 FROM chat_turns t JOIN game_state g ON g.id=1 WHERE t.id=? AND t.night_id=? AND t.status='active' AND t.minister_message_id>0 AND t.extract_status='pending' AND g.turn=?", params)
