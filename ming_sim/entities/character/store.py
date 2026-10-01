"""Person rows and the office archive.

#1889: one write port for ``characters``, ``character_offices`` and
``office_change_records``. Whether a title is a real office (and therefore
whether the archive is kept) is decided by the caller; this module only
persists the columns it is given.
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.entities.column_write import checked_columns, upsert_by_pk


CHARACTER_COLUMNS = frozenset({
    "name", "office", "office_type", "faction", "personal_skills",
    "loyalty", "ability", "integrity", "courage", "style",
    "birth_year", "historical_death_year", "historical_death_month",
    "debut_year", "debut_month", "status", "status_reason", "reason_code",
    "status_changed_turn", "power_id", "location", "transit_to",
    "transit_distance_remaining", "transit_speed_factor", "transit_start_turn",
    "identity", "seed_guilt", "portrait_id", "court_role", "summary",
    "aliases", "affair_id",
})

_MUTABLE_COLUMNS = CHARACTER_COLUMNS - {"name"}

OFFICE_COLUMNS = frozenset({
    "character_name", "office_title", "source", "dossier_id",
    "appointment_tenure", "region_id", "updated_at",
})


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="characters")


class CharacterStore:
    """Single write port for a person and that person's office archive."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(self, name: str, values: Mapping[str, object]) -> int:
        columns = _checked(values, allowed=_MUTABLE_COLUMNS)
        if not columns:
            raise ValueError("characters update needs fields")
        assignments = ", ".join(f"{column}=?" for column in columns)
        cursor = self._conn.execute(
            f"UPDATE characters SET {assignments} WHERE name=?",
            [values[column] for column in columns] + [name],
        )
        return int(cursor.rowcount or 0)

    def insert(self, row: Mapping[str, object]) -> None:
        if "name" not in row:
            raise ValueError("characters insert needs name")
        columns = _checked(row, allowed=CHARACTER_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO characters ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM characters WHERE name=?", (name,))

    def delete_office(self, name: str) -> None:
        self._conn.execute(
            "DELETE FROM character_offices WHERE character_name=?", (name,),
        )

    def upsert_office(
        self,
        *,
        name: str,
        office_title: str,
        source: str,
        dossier_id: int | None,
        appointment_tenure: str,
        region_id: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO character_offices
                (character_name, office_title, source, dossier_id,
                 appointment_tenure, region_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_name) DO UPDATE SET
                office_title = excluded.office_title,
                source = excluded.source,
                dossier_id = excluded.dossier_id,
                appointment_tenure = excluded.appointment_tenure,
                region_id = excluded.region_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (name, office_title, source, dossier_id, appointment_tenure, region_id),
        )

    def insert_office_change(
        self,
        *,
        name: str,
        office_title: str,
        office_type: str,
        source: str,
        dossier_id: int,
        appointment_tenure: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO office_change_records
                (character_name, office_title, office_type, source, dossier_id,
                 appointment_tenure)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, office_title, office_type, source, dossier_id, appointment_tenure),
        )

    def clear_office_archive(self) -> None:
        """Drop every current-office row and every office-change row."""
        self._conn.execute("DELETE FROM character_offices")
        self._conn.execute("DELETE FROM office_change_records")

    def insert_office_snapshots(self, rows: list[Mapping[str, object]]) -> None:
        """Restore archive rows, including the stored ``updated_at``."""
        if not rows:
            return
        self._conn.executemany(
            "INSERT INTO character_offices "
            "(character_name, office_title, source, dossier_id, "
            "appointment_tenure, region_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["character_name"],
                    row["office_title"],
                    row["source"],
                    row.get("dossier_id"),
                    row["appointment_tenure"],
                    str(row.get("region_id") or ""),
                    row["updated_at"],
                )
                for row in rows
            ],
        )

    def insert_office_change_snapshots(self, rows: list[Mapping[str, object]]) -> None:
        """Restore change rows, including the stored id and ``created_at``."""
        if not rows:
            return
        self._conn.executemany(
            "INSERT INTO office_change_records "
            "(id, character_name, office_title, office_type, source, dossier_id, "
            "appointment_tenure, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["id"],
                    row["character_name"],
                    row["office_title"],
                    row["office_type"],
                    row["source"],
                    row.get("dossier_id"),
                    row["appointment_tenure"],
                    row["created_at"],
                )
                for row in rows
            ],
        )

    def upsert(self, row: Mapping[str, object]) -> None:
        """Debug replace of one person. Caller commits."""
        upsert_by_pk(
            self._conn, "characters", row,
            pk="name", allowed=CHARACTER_COLUMNS, what="characters",
        )

    def restore_row(self, row: Mapping[str, object]) -> None:
        """Undo writes the before-image through this store."""
        self.upsert(row)

    def restore_office_row(self, row: Mapping[str, object]) -> None:
        upsert_by_pk(
            self._conn, "character_offices", row,
            pk="character_name", allowed=OFFICE_COLUMNS, what="character_offices",
        )

    def delete_by_name(self, name: str) -> int:
        cursor = self._conn.execute("DELETE FROM characters WHERE name=?", (name,))
        return int(cursor.rowcount or 0)

    def affair_id_of(self, name: str) -> int:
        row = self._conn.execute(
            "SELECT affair_id FROM characters WHERE name=?", (str(name),),
        ).fetchone()
        if row is None:
            raise KeyError(f"人物不存在：{name}")
        return int(row["affair_id"] or 0)

    def set_affair_id_if_unbound(self, name: str, affair_id: int) -> int:
        """Bind once; same id is idempotent; a different id fails loud."""
        from ming_sim.applier import connection_owns_transaction

        want = int(affair_id)
        person = str(name)
        owns = connection_owns_transaction(self._conn)
        cursor = self._conn.execute(
            "UPDATE characters SET affair_id=? WHERE name=? AND affair_id=0",
            (want, person),
        )
        if int(cursor.rowcount or 0) == 1:
            if owns:
                self._conn.commit()
            return want
        current = self.affair_id_of(person)
        if current == want:
            if owns:
                self._conn.commit()
            return want
        if owns:
            self._conn.rollback()
        raise ValueError(f"人物已指向事务 {current}，不能改指 {want}")
