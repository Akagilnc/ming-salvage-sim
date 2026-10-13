"""Person rows and the office archive.

#1889: one write port for ``characters``, ``character_offices`` and
``office_change_records``. Whether a title is a real office (and therefore
whether the archive is kept) is decided by the caller; this module only
persists the columns it is given.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ming_sim.entities.column_write import RowStore


class CharacterStore(RowStore):
    """Single write port for a person and that person's office archive."""

    TABLE = "characters"
    PK = "name"
    TABLES = {"characters": "name", "character_offices": "character_name"}
    REQUIRE_INSERT_PK = True
    AFFAIR_FIELDS = "name"

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

    def names(self) -> Any:
        return self._conn.execute("SELECT name FROM characters", ()).fetchall()

    def office_region(self, character_name: object) -> str:
        """Jurisdiction of the character's current appointment (一次任职)."""
        name = str(character_name or "").strip()
        if not name:
            return ""
        # Required table: empty name / no row stay business-empty; schema faults surface.
        row = self.row(name, fields="region_id", table="character_offices")
        return str(row["region_id"] or "").strip() if row is not None else ""

    def get_authority(self, authority_id: int) -> Optional[Dict[str, object]]:
        row = self.row(int(authority_id), table="authority_records", pk="id")
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
        row = self.row(name, fields="status, status_reason")
        if row is None:
            return ("active", "")
        return (row["status"], row["status_reason"] or "")

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
