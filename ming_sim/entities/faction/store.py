"""Faction rows.

#1889: one write port. Leverage formulas and clamps stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ming_sim.entities.column_write import upsert_by_pk

FACTION_COLUMNS = frozenset({
    "name", "satisfaction", "leverage", "agenda", "edict_overdraw", "leverage_offset",
})


class FactionStore:
    """Single write port for factions."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert(
        self, *, name: str, satisfaction: object, leverage: object, agenda: object,
    ) -> None:
        self._conn.execute(
            "INSERT INTO factions (name, satisfaction, leverage, agenda) "
            "VALUES (?, ?, ?, ?)",
            (name, satisfaction, leverage, agenda),
        )

    def set_leverage(self, name: str, leverage: object) -> None:
        self._conn.execute(
            "UPDATE factions SET leverage=? WHERE name=?", (leverage, name),
        )

    def set_leverage_offset(self, name: str, offset: object) -> None:
        self._conn.execute(
            "UPDATE factions SET leverage_offset=? WHERE name=?", (offset, name),
        )

    def set_satisfaction_and_leverage(
        self, name: str, satisfaction: object, leverage: object,
    ) -> None:
        self._conn.execute(
            "UPDATE factions SET satisfaction = ?, leverage = ? WHERE name = ?",
            (satisfaction, leverage, name),
        )

    def add_leverage_offset(
        self, name: str, satisfaction: object, offset_delta: object,
    ) -> None:
        self._conn.execute(
            "UPDATE factions SET satisfaction = ?, leverage_offset = leverage_offset + ? "
            "WHERE name = ?",
            (satisfaction, offset_delta, name),
        )

    def restore_row(self, row: Mapping[str, object]) -> None:
        upsert_by_pk(
            self._conn, "factions", row,
            pk="name", allowed=FACTION_COLUMNS, what="factions",
        )

    def delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM factions WHERE name=?", (name,))

    def restore_leverage(self, rows: Sequence[Mapping[str, object]]) -> None:
        self._conn.executemany(
            "UPDATE factions SET leverage=?, leverage_offset=? WHERE name=?",
            [(row["leverage"], row["leverage_offset"], row["name"]) for row in rows],
        )

    def reset_edict_overdraw(self) -> None:
        self._conn.execute("UPDATE factions SET edict_overdraw = 0")

    def set_edict_overdraw(self, name: str, value: object) -> None:
        self._conn.execute(
            "UPDATE factions SET edict_overdraw = ? WHERE name = ?",
            (value, name),
        )

    def add_edict_overdraw(self, name: str, delta: object) -> None:
        self._conn.execute(
            "UPDATE factions SET edict_overdraw = edict_overdraw + ? WHERE name = ?",
            (delta, name),
        )
