"""Fiscal catalogue and its append-only provenance; domain validation stays with GameDB."""

from typing import Any, Mapping

from ming_sim.entities.column_write import checked_columns

_COLUMNS = frozenset({
    "key", "value", "kind", "note", "budget_role", "account", "direction",
    "display", "sort_order", "origin_ref",
})
_HISTORY = {
    "create": ("fiscal_config_creations", frozenset({"turn", "key", "value", "kind", "origin_ref", "reason", "beyond_intent"})),
    "change": ("fiscal_config_changes", frozenset({"turn", "key", "old_value", "new_value", "delta", "origin_ref", "reason", "beyond_intent"})),
    "remove": ("fiscal_config_tombstones", frozenset({"removed_turn", "key", "value", "kind", "origin_ref", "reason", "beyond_intent"})),
}


class FiscalConfigStore:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def row(self, key: str) -> Any:
        return self._conn.execute("SELECT * FROM fiscal_config WHERE key=?", (key,)).fetchone()

    def has_any(self, keys: tuple[str, ...]) -> bool:
        placeholders = ",".join("?" for _ in keys)
        return self._conn.execute(
            f"SELECT 1 FROM fiscal_config WHERE key IN ({placeholders})", keys,
        ).fetchone() is not None

    def values(self) -> dict[str, int]:
        return {str(r["key"]): int(r["value"]) for r in self._conn.execute(
            "SELECT key, value FROM fiscal_config WHERE key NOT LIKE '\\_\\_%' ESCAPE '\\'",
        ).fetchall()}

    def budget_items(self) -> list[dict[str, object]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT key, account, direction, display, note, sort_order, origin_ref FROM fiscal_config "
            "WHERE budget_role='fixed' AND kind='base' AND key LIKE '%\\_base' ESCAPE '\\' "
            "ORDER BY sort_order, key",
        ).fetchall()]

    def next_sort_order(self) -> int:
        return int(self._conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 10 FROM fiscal_config",
        ).fetchone()[0])

    def insert(self, row: Mapping[str, object]) -> None:
        columns = checked_columns(row, _COLUMNS, what="fiscal_config")
        self._conn.execute(
            f"INSERT INTO fiscal_config ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [row[c] for c in columns],
        )

    def set_values(self, values: Mapping[str, int]) -> None:
        self._conn.executemany(
            "UPDATE fiscal_config SET value=? WHERE key=?",
            [(value, key) for key, value in values.items()],
        )

    def set_origin(self, key: str, origin: str) -> None:
        self._conn.execute("UPDATE fiscal_config SET origin_ref=? WHERE key=?", (origin, key))

    def override(self, key: str, value: int, note: str, origin: str) -> None:
        self._conn.execute(
            "INSERT INTO fiscal_config (key,value,kind,note,origin_ref) VALUES (?,?,'override',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, origin_ref=excluded.origin_ref",
            (key, value, note, origin),
        )

    def override_rows_for_origin(self, origin: str) -> list[Any]:
        return list(self._conn.execute(
            "SELECT key,value FROM fiscal_config WHERE origin_ref=? AND kind='override'",
            (str(origin),),
        ).fetchall())


    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM fiscal_config WHERE key=?", (key,))

    def append_history(self, kind: str, row: Mapping[str, object]) -> None:
        table, allowed = _HISTORY[kind]
        columns = checked_columns(row, allowed, what=table)
        self._conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [row[c] for c in columns],
        )

    def remove_items(self, keys: tuple[str, ...], *, turn: int, origin: str, reason: str, beyond: int) -> None:
        placeholders = ",".join("?" for _ in keys)
        self._conn.execute(
            "INSERT INTO fiscal_config_tombstones "
            "(removed_turn,key,value,kind,origin_ref,reason,beyond_intent) "
            f"SELECT ?,key,value,kind,?,?,? FROM fiscal_config WHERE key IN ({placeholders})",
            (turn, origin, reason, beyond, *keys),
        )
        for key in keys:
            self.delete(key)

    def latest_origin(self, keys: tuple[str, ...]) -> str:
        placeholders = ",".join("?" for _ in keys)
        row = self._conn.execute(
            f"SELECT origin_ref FROM fiscal_config_changes WHERE key IN ({placeholders}) "
            "ORDER BY id DESC LIMIT 1", keys,
        ).fetchone()
        return str(row["origin_ref"] or "") if row is not None else ""

    def creation_count(self, origin: str) -> int:
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM fiscal_config_creations WHERE origin_ref=?", (origin,),
        ).fetchone()[0])

    def removed_at(self, origin: str, turn: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM fiscal_config_tombstones WHERE origin_ref=? AND removed_turn=? LIMIT 1",
            (origin, turn),
        ).fetchone() is not None

    def reduction_at(self, origin: str, turn: int) -> Any:
        return self._conn.execute(
            "SELECT old_value,new_value FROM fiscal_config_changes "
            "WHERE origin_ref=? AND turn=? AND new_value<old_value LIMIT 1", (origin, turn),
        ).fetchone()

    def neutralization_recorded(self, origin: str, key: str, base_key: str, rate_key: str, reason: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM fiscal_config_changes WHERE origin_ref=? AND key=? AND reason=? "
            "UNION ALL SELECT 1 FROM fiscal_config_tombstones "
            "WHERE origin_ref=? AND key IN (?,?) AND reason=? LIMIT 1",
            (origin, key, reason, origin, base_key, rate_key, reason),
        ).fetchone() is not None

    def latest_lifecycle(self, kind: str, key: str) -> Any:
        table, _ = _HISTORY[kind]
        turn = "removed_turn" if kind == "remove" else "turn"
        return self._conn.execute(
            f"SELECT *,{turn} AS turn FROM {table} WHERE key=? ORDER BY {turn} DESC,id DESC LIMIT 1",
            (key,),
        ).fetchone()

    def changes_for(self, key: str, origin: str) -> list[Any]:
        return self._conn.execute(
            "SELECT id,turn,delta,beyond_intent FROM fiscal_config_changes "
            "WHERE key=? AND origin_ref=? ORDER BY turn,id", (key, origin),
        ).fetchall()

    def effects(self, origin: str) -> list[dict[str, object]]:
        return [
            {**dict(row), "effect_kind": kind}
            for kind, (table, _columns) in _HISTORY.items()
            for row in self._conn.execute(
                f"SELECT * FROM {table} WHERE origin_ref=? ORDER BY id", (origin,),
            ).fetchall()
        ]
