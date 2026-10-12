"""Person rows and the office archive.

#1889: one write port for ``characters``, ``character_offices`` and
``office_change_records``. Whether a title is a real office (and therefore
whether the archive is kept) is decided by the caller; this module only
persists the columns it is given.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from ming_sim.entities.column_write import bind_affair_once, checked_columns, upsert_by_pk


CHARACTER_COLUMNS = frozenset({
    "name", "office", "office_type", "faction", "personal_skills",
    "loyalty", "ability", "integrity", "courage", "style",
    "birth_year", "historical_death_year", "historical_death_month",
    "debut_year", "debut_month", "status", "status_reason", "reason_code",
    "status_changed_turn", "power_id", "location", "transit_to",
    "transit_distance_remaining", "transit_speed_factor", "transit_start_turn",
    "identity", "intrigue", "seed_guilt", "portrait_id", "court_role", "summary",
    "aliases", "affair_id",
})

_MUTABLE_COLUMNS = CHARACTER_COLUMNS - {"name"}



OFFICE_COLUMNS = frozenset(
    {
        "character_name",
        "office_title",
        "source",
        "dossier_id",
        "appointment_tenure",
        "region_id",
        "updated_at",
    }
)


class CharacterStore:
    """Single write port for a person and that person's office archive."""

    def row(self, name: str) -> Any:
        return self._conn.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()

    def field_row(self, field: str, name: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM characters WHERE name=?", (name,)).fetchone()

    def has_any(self, table: str) -> bool:
        if table not in ("characters", "character_offices", "office_slots"):
            raise ValueError(table)
        return self._conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None

    def current_court_rows(self, year: int, period: int, names: Iterable[str] | None = None) -> Any:
        wanted = [str(name).strip() for name in (names or []) if str(name).strip()]
        clauses = [
            "power_id='ming'", "status='active'",
            "office_type NOT IN ('后宫','宗藩','未仕')",
            "(debut_year=0 OR debut_year<? OR (debut_year=? AND debut_month<=?))",
        ]
        params: list[object] = [year, year, period]
        if wanted:
            clauses.append(f"name IN ({','.join('?' for _ in wanted)})")
            params.extend(wanted)
        return self._conn.execute(
            "SELECT name,office,office_type,faction,status,status_reason "
            f"FROM characters WHERE {' AND '.join(clauses)} ORDER BY name", params,
        ).fetchall()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def update(self, name: str, values: Mapping[str, object]) -> int:
        columns = checked_columns(values, _MUTABLE_COLUMNS, what="characters")
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
        columns = checked_columns(row, CHARACTER_COLUMNS, what="characters")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO characters ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM characters WHERE name=?", (name,))

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

    def restore_row(self, row: Mapping[str, object]) -> None:
        """Undo writes the before-image through this store."""
        upsert_by_pk(
            self._conn, "characters", row,
            pk="name", allowed=CHARACTER_COLUMNS, what="characters",
        )

    def affair_id_of(self, name: str) -> int:
        row = self.field_row('affair_id', str(name))
        if row is None:
            raise KeyError(f"人物不存在：{name}")
        return int(row["affair_id"] or 0)

    def set_affair_id_if_unbound(self, name: str, affair_id: int) -> int:
        return bind_affair_once(self._conn, "characters", str(name), affair_id, pk="name")

    def presence(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM characters WHERE name=?', params).fetchone()

    def names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM characters', params).fetchall()

    def office_region(self, character_name: object) -> str:
        """Jurisdiction of the character's current appointment (一次任职)."""
        name = str(character_name or "").strip()
        if not name:
            return ""
        # Required table: empty name / no row stay business-empty; schema faults surface.
        row = self._conn.execute(
            "SELECT region_id FROM character_offices WHERE character_name=?", (name,)
        ).fetchone()
        return str(row["region_id"] or "").strip() if row is not None else ""

    def location_status_row(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT location, transit_to, status FROM characters WHERE name=?', params).fetchone()

    def location_row(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT location, transit_to FROM characters WHERE name=?', params).fetchone()

    def get_authority(self, authority_id: int) -> Optional[Dict[str, object]]:
        row = self._conn.execute(
            "SELECT * FROM authority_records WHERE id=?", (int(authority_id),)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["revoked"] = bool(result["revoked"])
        return result

    def list_active_authorities(
        self, turn: int, *, holder_id: str = "",
    ) -> List[Dict[str, object]]:
        params: List[object] = [int(turn), int(turn)]
        holder_sql = ""
        if holder_id:
            holder_sql = " AND holder_id=?"
            params.append(str(holder_id))
        rows = self._conn.execute(
            f'SELECT * FROM authority_records WHERE revoked=0 AND effective_turn<=? AND (expires_turn IS NULL OR expires_turn>=?){holder_sql} ORDER BY id',
            params,
        ).fetchall()
        return [{**dict(row), "revoked": False} for row in rows]

    def find_active_authority(
        self, turn: int, *, holder_id: str, privilege: str, scope: str,
    ) -> dict[str, object] | None:
        """Exact in-hand grant identity, if any."""
        holder_id = str(holder_id or "").strip()
        privilege = str(privilege or "").strip()
        scope = str(scope or "").strip()
        for row in self.list_active_authorities(turn, holder_id=holder_id):
            if (
                str(row.get("privilege") or "") == privilege
                and str(row.get("scope") or "") == scope
            ):
                return row
        return None

    def find_authority_by_origin(
        self, dossier_id: int, *, holder_id: str, privilege: str, scope: str,
    ) -> Optional[Dict[str, object]]:
        """Return the stable row for an exact grant origin, regardless of status."""
        row = self._conn.execute(
            "SELECT * FROM authority_records WHERE dossier_id=? AND holder_id=? AND privilege=? AND scope=? ORDER BY id LIMIT 1",
            (
                int(dossier_id),
                str(holder_id).strip(),
                str(privilege).strip(),
                str(scope).strip(),
            ),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["revoked"] = bool(result["revoked"])
        return result

    def get_character_status(self, name: str) -> tuple[str, str]:
        row = self._conn.execute(
            "SELECT status, status_reason FROM characters WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return ("active", "")
        return (row["status"], row["status_reason"] or "")

    def status_office_row(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT status, office FROM characters WHERE name=?", params
        ).fetchone()

    def status_power_row(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT status, power_id FROM characters WHERE name=?", params
        ).fetchone()

    def office_location_row(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT office,office_type,location FROM characters WHERE name=?", params
        ).fetchone()

    def faction_status_row(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT faction,status FROM characters WHERE name=?", params
        ).fetchone()

    def snapshot_rows(self, table: str) -> Any:
        sql = {
            "characters": "SELECT * FROM characters",
            "character_offices": "SELECT * FROM character_offices",
        }[table]
        return self._conn.execute(sql).fetchall()

    def restore_office_row(self, row: Mapping[str, object]) -> None:
        upsert_by_pk(
            self._conn,
            "character_offices",
            row,
            pk="character_name",
            allowed=OFFICE_COLUMNS,
            what="character_offices",
        )

    def delete_office(self, name: str) -> None:
        self._conn.execute(
            "DELETE FROM character_offices WHERE character_name=?",
            (name,),
        )

    def named_status_rows(self, names: Iterable[str]) -> Any:
        names = tuple(names)
        placeholders = ",".join("?" for _ in names)
        return self._conn.execute(
            f"SELECT * FROM characters WHERE name IN ({placeholders})",
            names,
        ).fetchall()

    def gatekeeper_rows(
        self, office_titles: Iterable[str], *, include_six_offices: bool = False
    ) -> Any:
        offices = tuple(office_titles)
        placeholders = ",".join("?" for _ in offices)
        office_clause = f"office IN ({placeholders})"
        if include_six_offices:
            office_clause = f"({office_clause} OR office_type='六科')"
        order = "office_type,office,name" if include_six_offices else "name"
        return self._conn.execute(
            f"SELECT * FROM characters WHERE status='active' AND power_id='ming' "
            f"AND {office_clause} ORDER BY {order}",
            offices,
        ).fetchall()

    def rows_for_affair(self, affair_id: int) -> Any:
        return self._conn.execute(
            "SELECT name FROM characters WHERE affair_id=? ORDER BY name", (affair_id,)
        ).fetchall()
