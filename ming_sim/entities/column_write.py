"""Shared column check and primary-key upsert.

#1889 F10: the debug upsert and the unknown-column check were copied into each
entity store. This module is that one algorithm. It does not open connections,
invent schema, or validate business values.
"""

from __future__ import annotations

from typing import Any, Mapping


def checked_columns(
    values: Mapping[str, object], allowed: frozenset[str] | set[str], *, what: str,
) -> list[str]:
    """Sorted column names. Unknown keys raise; the message names the table."""
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"{what} 列非法：{sorted(unknown)}")
    return [column for column in sorted(values)]


def upsert_by_pk(
    conn: Any,
    table: str,
    row: Mapping[str, object],
    *,
    pk: str,
    allowed: frozenset[str],
    what: str,
) -> None:
    """INSERT … ON CONFLICT(pk) DO UPDATE of the supplied columns. Caller commits."""
    if pk not in row or row[pk] in (None, ""):
        raise ValueError(f"缺主键 {pk}")
    columns = checked_columns(row, allowed, what=what)
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
