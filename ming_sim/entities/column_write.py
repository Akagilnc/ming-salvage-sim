"""Shared persistence algorithms; entity stores own table and primary-key names.

No schema mirror or column gate: SQLite checks the supplied columns. Business
validation and transaction ownership stay with the caller.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from typing import Any, Mapping

from ming_sim.applier import connection_owns_transaction


def upsert_by_pk(conn: Any, table: str, row: Mapping[str, object], *, pk: str) -> None:
    """Restore the supplied before-image without replacing the row. Caller commits."""
    if pk not in row or row[pk] in (None, ""):
        raise ValueError(f"缺主键 {pk}")
    columns = sorted(row)
    assignments = ", ".join(
        f"{column}=excluded.{column}" for column in columns if column != pk
    )
    action = f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) {action}",
        [row[column] for column in columns],
    )


class RowStore:
    """One implementation of the row operations used by entity stores.

    TABLE/PK identify the usual row; TABLES registers rollback tables owned by
    the entity. LOG_SQL is fixed SQL, not a second copy of the schema.
    """

    TABLE: str
    PK: str | tuple[str, ...] = "id"
    TABLES: Mapping[str, str] = {}
    TOUCH = False
    TOUCH_EMPTY = False
    REQUIRE_INSERT_PK = False
    LOG_SQL: str
    LOG_DEFAULTS: Mapping[str, object] = {}
    AFFAIR_FIELDS = "*"

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _key_where(
        self, key: object, table: str, pk: str | tuple[str, ...] | None = None
    ):
        pk = pk or self.TABLES.get(table, self.PK)
        columns = (pk,) if isinstance(pk, str) else pk
        keys = (key,) if isinstance(pk, str) else key
        return " AND ".join(f"{column}=?" for column in columns), keys

    def row(
        self,
        key: object,
        *,
        fields: str = "*",
        table: str | None = None,
        pk: str | tuple[str, ...] | None = None,
    ) -> Any:
        table = table or self.TABLE
        where, keys = self._key_where(key, table, pk)
        return self._conn.execute(
            f"SELECT {fields} FROM {table} WHERE {where}",
            keys,
        ).fetchone()

    def has_any(self, table: str | None = None) -> bool:
        return (
            self._conn.execute(
                f"SELECT 1 FROM {table or self.TABLE} LIMIT 1",
            ).fetchone()
            is not None
        )

    def insert(
        self,
        row: Mapping[str, object],
        *,
        ignore: bool = False,
        table: str | None = None,
    ) -> None:
        table = table or self.TABLE
        if table == self.TABLE and self.REQUIRE_INSERT_PK and self.PK not in row:
            raise ValueError(f"{self.TABLE} insert needs {self.PK}")
        columns = sorted(row)
        placeholders = ", ".join("?" for _ in columns)
        verb = "INSERT OR IGNORE" if ignore else "INSERT"
        self._conn.execute(
            f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def update(
        self,
        key: object,
        values: Mapping[str, object],
        *,
        touch: bool | None = None,
        table: str | None = None,
    ) -> int:
        table = table or self.TABLE
        where, keys = self._key_where(key, table)
        touch = self.TOUCH if touch is None else touch
        if not values and not (self.TOUCH_EMPTY and touch):
            raise ValueError(f"{self.TABLE} update needs fields")
        columns = sorted(values)
        parts = [f"{column}=?" for column in columns]
        if touch:
            parts.append("updated_at=CURRENT_TIMESTAMP")
        cursor = self._conn.execute(
            f"UPDATE {table} SET {', '.join(parts)} WHERE {where}",
            [values[column] for column in columns] + list(keys),
        )
        return int(cursor.rowcount or 0)

    def append_log(self, row: Mapping[str, object]) -> None:
        self.append_logs((row,))

    def append_logs(self, rows: Any) -> None:
        payload = [defaultdict(lambda: None, {**self.LOG_DEFAULTS, **row}) for row in rows]
        if payload:
            self._conn.executemany(self.LOG_SQL, payload)

    def set_affair_id_if_unbound(self, key: object, affair_id: int) -> int:
        """Once-only pointer write; caller-owned transactions stay caller-owned."""
        want = int(affair_id)
        conn = self._conn
        with conn if connection_owns_transaction(conn) else nullcontext():
            current = self.affair_id_of(key)
            if current == want:
                return want
            if current:
                raise ValueError(f"{self.TABLE} 已指向事务 {current}，不能改指 {want}")
            cursor = conn.execute(
                f"UPDATE {self.TABLE} SET affair_id=? WHERE {self.PK}=? AND affair_id=0",
                (want, key),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"{self.TABLE} 已指向其它事务，不能改指 {want}")
        return want

    def affair_id_of(self, key: object) -> int:
        row = self.row(key, fields="affair_id")
        if row is None:
            raise KeyError(f"{self.TABLE} 不存在：{key}")
        return int(row["affair_id"] or 0)

    def rows_for_affair(self, affair_id: int) -> Any:
        return self._conn.execute(
            f"SELECT {self.AFFAIR_FIELDS} FROM {self.TABLE} WHERE affair_id=? ORDER BY {self.PK}",
            (affair_id,),
        ).fetchall()

    def snapshot_rows(self, table: str) -> Any:
        return self._conn.execute(f"SELECT * FROM {table}").fetchall()

    def restore_snapshot(self, table: str, row: Mapping[str, object]) -> None:
        upsert_by_pk(self._conn, table, row, pk=self.TABLES[table])

    def delete(self, key: object, *, table: str | None = None) -> None:
        table = table or self.TABLE
        where, keys = self._key_where(key, table)
        self._conn.execute(f"DELETE FROM {table} WHERE {where}", keys)
