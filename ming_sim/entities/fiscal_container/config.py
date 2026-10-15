"""Fiscal catalogue and its append-only provenance; domain validation stays with GameDB."""

from typing import Any, Mapping

from ming_sim.applier import coerce_beyond_intent_flag

from ming_sim.entities.column_write import RowStore

_HISTORY = {
    "create": "fiscal_config_creations",
    "change": "fiscal_config_changes",
    "remove": "fiscal_config_tombstones",
}


class FiscalConfigStore(RowStore):
    TABLE = "fiscal_config"
    PK = "key"
    # #1915：召对轮撤回须能逆转本轮新建的月费 live 科目及其创建史
    # （list_durable_effects_for_origin 读 creations；只撤 live 不够）。
    TABLES = {
        "fiscal_config": "key",
        "fiscal_config_creations": "id",
    }

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

    def set_values(self, values: Mapping[str, int]) -> None:
        self._conn.executemany(
            "UPDATE fiscal_config SET value=? WHERE key=?",
            [(value, key) for key, value in values.items()],
        )

    def set_origin(self, key: str, origin: str) -> None:
        self._conn.execute("UPDATE fiscal_config SET origin_ref=? WHERE key=?", (origin, key))

    def override_rows_for_origin(self, origin: str) -> list[Any]:
        return list(self._conn.execute(
            "SELECT key,value FROM fiscal_config WHERE origin_ref=? AND kind='override'",
            (str(origin),),
        ).fetchall())

    def append_history(self, kind: str, row: Mapping[str, object]) -> None:
        self.insert(row, table=_HISTORY[kind])

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

    def creation_count(self, origin: str) -> int:
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM fiscal_config_creations WHERE origin_ref=?", (origin,),
        ).fetchone()[0])

    def reduction_at(self, origin: str, turn: int) -> Any:
        return self._conn.execute(
            "SELECT old_value,new_value FROM fiscal_config_changes "
            "WHERE origin_ref=? AND turn=? AND new_value<old_value LIMIT 1", (origin, turn),
        ).fetchone()

    def changes_for(self, key: str, origin: str) -> list[Any]:
        return self._conn.execute(
            "SELECT id,turn,delta,beyond_intent FROM fiscal_config_changes "
            "WHERE key=? AND origin_ref=? ORDER BY turn,id", (key, origin),
        ).fetchall()

    def effects_for_origin(self, origin: str) -> list[dict[str, object]]:
        return [
            {
                **dict(row),
                "effect_kind": kind,
                "beyond_intent": bool(coerce_beyond_intent_flag(row["beyond_intent"])),
            }
            for kind, table in _HISTORY.items()
            for row in self._conn.execute(
                f"SELECT * FROM {table} WHERE origin_ref=? ORDER BY id",
                (origin,),
            ).fetchall()
        ]

    def record_change(
        self,
        *,
        turn: int,
        key: str,
        old_value: int,
        new_value: int,
        origin_ref: str,
        reason: str = "",
        beyond_intent: object = 0,
    ) -> None:
        """Append immutable provenance for a fiscal value change.

        Caller owns the surrounding transaction so history and live config
        never commit separately. beyond_intent uses sole durable coerce.
        """
        beyond_flag = coerce_beyond_intent_flag(beyond_intent)
        self.append_history(
            "change",
            {
                "turn": int(turn),
                "key": key,
                "old_value": int(old_value),
                "new_value": int(new_value),
                "delta": int(new_value) - int(old_value),
                "origin_ref": origin_ref,
                "reason": reason,
                "beyond_intent": beyond_flag,
            },
        )

    def item_presence(self, key: str, other_key: str) -> Any:
        return self._conn.execute(
            "SELECT 1 FROM fiscal_config WHERE key IN (?, ?)",
            (key, other_key),
        ).fetchone()

    def upsert_pay_override(self, key: str, value: int, note: str) -> Any:
        return self._conn.execute(
            "INSERT INTO fiscal_config (key, value, kind, note) VALUES (?, ?, 'override', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value, note),
        )
