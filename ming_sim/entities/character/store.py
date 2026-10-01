"""Person rows and the office archive.

#1889: one write port for ``characters``, ``character_offices`` and
``office_change_records``. Whether a title is a real office (and therefore
whether the archive is kept) is decided by the caller; this module only
persists the columns it is given.
"""

from __future__ import annotations

from typing import Any, Mapping


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


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"characters 列非法：{sorted(unknown)}")
    return [column for column in sorted(values)]


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
