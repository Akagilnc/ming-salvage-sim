"""Faction rows.

#1889: one write port. Leverage formulas and clamps stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.entities.column_write import upsert_by_pk

FACTION_COLUMNS = frozenset(
    {
        "name",
        "satisfaction",
        "leverage",
        "agenda",
        "edict_overdraw",
        "leverage_offset",
    }
)


class FactionStore:
    """Single write port for factions."""

    def has_any(self) -> bool:
        return self._conn.execute("SELECT 1 FROM factions LIMIT 1").fetchone() is not None

    def field_row(self, field: str, name: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM factions WHERE name=?", (name,)).fetchone()

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

    def restore_row(self, row: Mapping[str, object]) -> None:
        upsert_by_pk(
            self._conn, "factions", row,
            pk="name", allowed=FACTION_COLUMNS, what="factions",
        )

    def delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM factions WHERE name=?", (name,))


    def faction_satisfaction(self, faction: str) -> int:
        row = self._conn.execute(
            "SELECT satisfaction FROM factions WHERE name = ?", (faction,)
        ).fetchone()
        return int(row["satisfaction"]) if row else 50

    def faction_leverage(self, faction: str) -> int:
        row = self._conn.execute(
            "SELECT leverage FROM factions WHERE name = ?", (faction,)
        ).fetchone()
        return int(row["leverage"]) if row else 50


    def read_names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM factions', params).fetchall()

    def read_faction_context_with_db(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT agenda, satisfaction, leverage FROM factions WHERE name = ?', params).fetchone()

    def get_faction_stance_summaries(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM faction_stance_summaries ORDER BY faction", ()
        ).fetchall()
        return [dict(row) for row in rows]

    def write_apply_faction_brew_result(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "\n                INSERT INTO faction_stance_summaries\n                    (faction, stance_segment, last_event_id,\n                     last_brewed_turn, last_brewed_year, last_brewed_period)\n                VALUES (?, ?, ?, ?, ?, ?)\n                ON CONFLICT(faction) DO UPDATE SET\n                    stance_segment = excluded.stance_segment,\n                    last_event_id = excluded.last_event_id,\n                    last_brewed_turn = excluded.last_brewed_turn,\n                    last_brewed_year = excluded.last_brewed_year,\n                    last_brewed_period = excluded.last_brewed_period,\n                    updated_at = CURRENT_TIMESTAMP\n                ",
            params,
        )

    def read_recompute_faction_leverage(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT leverage_offset FROM factions WHERE name=?", params
        ).fetchone()

    def read_adjust_factions(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT satisfaction, leverage FROM factions WHERE name = ?", params
        ).fetchone()

    def read_build_faction_denunciation_facts(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT name FROM factions ORDER BY name", params
        ).fetchall()

    def read_build_promulgation_judge_context(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT name,leverage,agenda FROM factions ORDER BY name", params
        ).fetchall()

    def write_recompute_faction_leverage(self, params: Any = ()) -> Any:
        return self._conn.execute("UPDATE factions SET leverage=? WHERE name=?", params)

    def write_calibrate_faction_offsets(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE factions SET leverage_offset=? WHERE name=?", params
        )

    def write_adjust_factions(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE factions SET satisfaction = ?, leverage_offset = leverage_offset + ? "
            "WHERE name = ?",
            params,
        )

    def write_adjust_factions_factions(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE factions SET satisfaction = ?, leverage = ? WHERE name = ?", params
        )

    def read_calibrate_faction_offsets(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT 1 FROM factions WHERE name=?", params
        ).fetchone()

    def snapshot_rows(self) -> Any:
        return self._conn.execute("SELECT * FROM factions").fetchall()
