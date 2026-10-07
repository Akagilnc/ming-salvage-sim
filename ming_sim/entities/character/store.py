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

OFFICE_COLUMNS = frozenset({
    "character_name", "office_title", "source", "dossier_id",
    "appointment_tenure", "region_id", "updated_at",
})


def _checked(values: Mapping[str, object], *, allowed: frozenset[str]) -> list[str]:
    return checked_columns(values, allowed, what="characters")


class CharacterStore:
    """Single write port for a person and that person's office archive."""

    def row(self, name: str) -> Any:
        return self._conn.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()

    def field_row(self, field: str, name: str) -> Any:
        """Read a schema field already validated by the gate/subject consumer."""
        return self._conn.execute(f"SELECT {field} FROM characters WHERE name=?", (name,)).fetchone()

    def snapshot_rows(self, table: str) -> Any:
        sql = {"characters": "SELECT * FROM characters", "character_offices": "SELECT * FROM character_offices"}[table]
        return self._conn.execute(sql).fetchall()

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

    def named_status_rows(self, names: Iterable[str]) -> Any:
        names = tuple(names)
        placeholders = ','.join('?' for _ in names)
        return self._conn.execute(
            f"SELECT name,faction,status FROM characters WHERE name IN ({placeholders})", names,
        ).fetchall()

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

    def affair_id_of(self, name: str) -> int:
        row = self._conn.execute(
            "SELECT affair_id FROM characters WHERE name=?", (str(name),),
        ).fetchone()
        if row is None:
            raise KeyError(f"人物不存在：{name}")
        return int(row["affair_id"] or 0)

    def set_affair_id_if_unbound(self, name: str, affair_id: int) -> int:
        return bind_affair_once(self._conn, "characters", str(name), affair_id, pk="name")

    def read_commission_fallback_actor(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 1", params).fetchone()

    def read_commission_fallback_actor_name(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM characters WHERE name=? LIMIT 1', params).fetchone()

    def read_dispatch_inquiries(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office FROM characters WHERE name=?', params).fetchone()

    def read_assert_characters_exist(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM characters WHERE name=?', params).fetchone()

    def read_load_pending_gate_shadow_rows(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, status, status_reason, reason_code, location, transit_to, power_id, office, office_type FROM characters', params).fetchall()

    def read_displace_duplicate_offices(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office FROM characters WHERE status='active' AND power_id='ming' AND name!=?", params).fetchall()

    def read_names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM characters', params).fetchall()

    def read_dead_person_core_subjects(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status FROM characters WHERE name = ?', params).fetchone()

    def read_displace_duplicate_offices_office_type(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office_type FROM characters WHERE name=?', params).fetchone()

    def read_displace_duplicate_offices_faction(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT faction FROM characters WHERE name=?', params).fetchone()

    def read_character_row(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, status, office, office_type, power_id, status_reason, status_changed_turn, reason_code, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn FROM characters WHERE name=?', params).fetchone()

    def read_strategic_event_result_preflight_error(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, location, transit_to FROM characters WHERE name = ?', params).fetchone()

    def read_snapshot_person_write_state(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, status, office, office_type, status_reason, status_changed_turn, reason_code, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn FROM characters', params).fetchall()

    def read_snapshot_person_write_state_character_name_office_title_source_dossier_id_appointment_tenure_(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT character_name, office_title, source, dossier_id, appointment_tenure, region_id, updated_at FROM character_offices', params).fetchall()

    def read_snapshot_person_write_state_id_character_name_office_title_office_type_source_dossier_id_appo(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, character_name, office_title, office_type, source, dossier_id, appointment_tenure, created_at FROM office_change_records', params).fetchall()

    def read_apply_person_changes(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, loyalty FROM characters WHERE name=?', params).fetchone()

    def read_apply_person_changes_name_style(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, style FROM characters WHERE name=?', params).fetchone()

    def read_apply_person_changes_name(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM characters WHERE name=?', params).fetchone()

    def read_apply_person_changes_status_location_transit_to_transit_distance_remaining_transit_spe(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, location, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn FROM characters WHERE name=?', params).fetchone()

    def read_amnesty_conflict_power_ids(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, power_id, reason_code FROM characters WHERE name=?', params).fetchone()

    def read_strategic_event_result_preflight_error_c_office_c_office_type_COALESCE_co_appointment_tenure_真除_AS_appoi(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT c.office, c.office_type, COALESCE(co.appointment_tenure, '真除') AS appointment_tenure FROM characters c LEFT JOIN character_offices co ON co.character_name = c.name WHERE c.name = ?", params).fetchone()

    def read_faction_office_weight_sum(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT office_type, office FROM characters WHERE faction=? AND status='active' AND power_id='ming'", params).fetchall()

    def read_get_character_status(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, status_reason FROM characters WHERE name=?', params).fetchone()

    def read_resolve_power_id(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT power_id FROM characters WHERE name=?', params).fetchone()

    def read_apply_historical_deaths(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office, faction, historical_death_year, historical_death_month\n               FROM characters\n               WHERE status = 'active' AND historical_death_year > 0", params).fetchall()

    def read_apply_historical_debuts(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office, faction, debut_year, debut_month\n               FROM characters\n               WHERE status = 'offstage' AND debut_year > 0", params).fetchall()

    def read_next_pool_portrait_id(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT portrait_id FROM characters WHERE portrait_id LIKE ?', params).fetchall()

    def read_knowledge_items_for_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, office, office_type FROM characters', params).fetchall()

    def read_find_pacification_target(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, power_id FROM characters WHERE name=?', params).fetchone()

    def read_build_faction_denunciation_facts(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT name, faction, integrity, identity, status\n            FROM characters\n            WHERE status='active' AND COALESCE(faction,'') <> ''\n            ORDER BY name\n            ", params).fetchall()

    def read_character_office_region(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT region_id FROM character_offices WHERE character_name=?', params).fetchone()

    def office_region(self, character_name: object) -> str:
        """Jurisdiction of the character's current appointment (一次任职)."""
        name = str(character_name or "").strip()
        if not name:
            return ""
        # Required table: empty name / no row stay business-empty; schema faults surface.
        row = self.read_character_office_region((name,))
        return str(row["region_id"] or "").strip() if row is not None else ""

    def read_list_referenceable_dossiers(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office,office_type,location FROM characters WHERE name=?', params).fetchone()


    def read_apply_character_power_changes(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT power_id, faction FROM characters WHERE name=?', params).fetchone()

    def read_accept_faction_denunciations(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, faction, status FROM characters WHERE name=?', params).fetchone()

    def read_require_local_office_region(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office_title, region_id FROM character_offices WHERE character_name=?', params).fetchone()

    def read_set_character_office(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT office_type FROM characters WHERE name=? AND power_id='ming'", params).fetchone()

    def read_build_faction_denunciation_facts_identity(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT identity FROM characters WHERE name=?', params).fetchone()

    def read_breach_decree_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT faction,status FROM characters WHERE name=?', params).fetchone()

    def read_list_office_effects_for_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM office_change_records WHERE dossier_id=? ORDER BY id', params).fetchall()

    def read_build_translation_target_grounding(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office FROM characters WHERE status='active' ORDER BY name", params).fetchall()

    def read_sponsor_transferred(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, office FROM characters WHERE name=?', params).fetchone()

    def read_sponsor_transferred_office_title(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office_title FROM character_offices WHERE character_name=?', params).fetchone()

    def read_sponsor_transferred_office_title_by_character_name(self, params: Any = ()) -> Any:
        return self._conn.execute('\n        SELECT office_title FROM office_change_records\n        WHERE character_name=? ORDER BY id DESC LIMIT 1\n        ', params).fetchone()

    def read_sponsor_transferred_1(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                        SELECT 1 FROM office_change_records\n                        WHERE character_name=? AND dossier_id IS NOT NULL\n                          AND dossier_id != ?\n                        ORDER BY id DESC LIMIT 1\n                        ', params).fetchone()

    def read_resolve_executor_appointment_tenure(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT appointment_tenure FROM character_offices WHERE character_name=?', params).fetchone()

    def read_tick_transit_arrivals(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn FROM characters WHERE status='active' AND COALESCE(transit_to, '') != '' AND transit_distance_remaining IS NOT NULL AND transit_speed_factor IS NOT NULL ORDER BY name", params).fetchall()

    def read_build_promulgation_judge_context(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name,office,office_type,faction,courage,integrity FROM characters WHERE status='active' AND power_id='ming' AND (office LIKE '%首辅%' OR office LIKE '%掌印%' OR office LIKE '%给事中%' OR office_type='六科') ORDER BY office_type,office,name", params).fetchall()

    def read_resolve_present_character(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            SELECT name, office, office_type, faction, aliases, personal_skills,\n                   loyalty, ability, integrity, courage, style, identity,\n                   summary, power_id\n            FROM characters WHERE name=?\n            ', params).fetchone()

    def read_world_roster_names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name FROM characters ORDER BY name', params).fetchall()

    def read_register_unlisted_person_record(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT portrait_id FROM characters WHERE name=?', params).fetchone()

    def read_sync_offices_from_db_impl(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT c.name, c.office, c.office_type, c.faction, c.aliases, c.personal_skills,\n               c.loyalty, c.ability, c.integrity, c.courage, c.style, c.identity, c.intrigue, c.seed_guilt,\n               c.birth_year, c.historical_death_year, c.historical_death_month,\n               c.debut_year, c.debut_month, c.status, c.status_reason, c.reason_code,\n               c.portrait_id, c.power_id, c.location, c.transit_to,\n               c.transit_distance_remaining, c.transit_speed_factor, c.transit_start_turn,\n               c.summary,\n               COALESCE(co.region_id, '') AS office_region\n        FROM characters c\n        LEFT JOIN character_offices co ON co.character_name = c.name\n        ", params).fetchall()

    def read_select_triage_actor(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name,office,faction FROM characters WHERE status='active' AND power_id='ming' AND office LIKE ? ORDER BY office_type,office,name LIMIT 1", params).fetchone()

    def read_resolve_host_character(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT integrity, courage FROM characters WHERE name=?', params).fetchone()

    def read_project_character_factions(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, faction FROM characters', params).fetchall()

    def read_minister_eligible_for_monthly_covert(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT 1 FROM characters WHERE name=? AND status='active'", params).fetchone()

    def read_live_investigation_fact_keys(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT seed_guilt FROM characters WHERE name=?', params).fetchone()

    def read_character_faction_integrity(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT faction, integrity FROM characters WHERE name=?', params).fetchone()

    def read_resolve_standing_roster(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office, office_type, status FROM characters WHERE status = 'active' ORDER BY name", params).fetchall()

    def read_project_unsettled_summon_kind(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT location, transit_to, status FROM characters WHERE name=?', params).fetchone()

    def read_list_waiting_audience_summons(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT location FROM characters WHERE name=?', params).fetchone()

    def read_role_roster(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office FROM characters\n           WHERE office_type = ? AND status = 'active' AND power_id = 'ming'\n             AND (debut_year = 0 OR debut_year < ?\n                  OR (debut_year = ? AND debut_month <= ?))\n           ORDER BY name", params).fetchall()

    def read_knowledge_row_visible_to(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT name, office, office_type FROM characters WHERE name=?', params).fetchone()

    def read_current_character_office(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office, office_type FROM characters WHERE name = ?', params).fetchone()

    def read_appointment_break_rank(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT office,office_type,status,reason_code FROM characters WHERE name=?', params).fetchone()

    def read_appointment_break_rank_o_office_title_SELECT_c_office_type(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                SELECT o.office_title,\n                       (\n                         SELECT c.office_type FROM office_change_records c\n                         WHERE c.character_name=o.character_name\n                           AND c.office_title=o.office_title\n                         ORDER BY c.id DESC LIMIT 1\n                       ) AS office_type\n                FROM character_offices o\n                WHERE o.character_name=?\n                ', params).fetchone()

    def read_admit_audience(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT location, transit_to FROM characters WHERE name=?', params).fetchone()

    def write_apply_authority_change_item(self, params: Any = ()) -> Any:
        return self._conn.execute('UPDATE authority_records SET revoked=1,revoked_turn=? WHERE id=? AND revoked=0', params)

    def write_apply_authority_change_item_authority_records(self, params: Any = ()) -> Any:
        return self._conn.execute('INSERT INTO authority_records (holder_id,privilege,scope,effective_turn,expires_turn,dossier_id) VALUES (?,?,?,?,?,?)', params)

    def read_get_authority(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM authority_records WHERE id=?', params).fetchone()

    def get_authority(self, authority_id: int) -> Optional[Dict[str, object]]:
        row = self.read_get_authority((int(authority_id),))
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
        rows = self.read_list_active_authorities_owned(params, holder_sql).fetchall()
        return [{**dict(row), "revoked": False} for row in rows]

    def find_authority_by_origin(
        self, dossier_id: int, *, holder_id: str, privilege: str, scope: str,
    ) -> Optional[Dict[str, object]]:
        """Return the stable row for an exact grant origin, regardless of status."""
        row = self.read_find_authority_by_origin((
            int(dossier_id), str(holder_id).strip(), str(privilege).strip(),
            str(scope).strip(),
        ))
        if row is None:
            return None
        result = dict(row)
        result["revoked"] = bool(result["revoked"])
        return result

    def get_character_status(self, name: str) -> tuple[str, str]:
        row = self.read_get_character_status((name,))
        if row is None:
            return ("active", "")
        return (row["status"], row["status_reason"] or "")

    def list_office_effects_for_dossier(
        self, dossier_id: int,
    ) -> List[Dict[str, object]]:
        return [
            dict(row) for row in self.read_list_office_effects_for_dossier((int(dossier_id),))
        ]


    def read_find_authority_by_origin(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM authority_records WHERE dossier_id=? AND holder_id=? AND privilege=? AND scope=? ORDER BY id LIMIT 1', params).fetchone()

    def read_reclaim_bundled_authorities(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM authority_records WHERE dossier_id=? AND revoked=0 ORDER BY id', params).fetchall()

    def write_ensure_office_type_parent(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            INSERT OR IGNORE INTO offices\n            (office_type, power, responsibility, corruption_risk)\n            VALUES (?, ?, ?, ?)\n            ', params)

    def read_ensure_office_type_parent(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM offices WHERE office_type=?', params).fetchone()

    def write_record_recommendation(self, params: Any = ()) -> Any:
        return self._conn.execute("INSERT INTO recommendation_events\n           (turn,year,period,recommender,candidate,candidate_kind,target_office,basis,reason,status)\n           VALUES (?,?,?,?,?,?,?,?,?,'adopted')", params)

    def recommendation_events(self, turn: int, recommender: str | None = None) -> Any:
        sql = 'SELECT * FROM recommendation_events WHERE turn <= ?'
        params = [turn]
        if recommender:
            sql += ' AND recommender=?'
            params.append(recommender)
        return self._conn.execute(sql + ' ORDER BY turn, id', params).fetchall()

    def read_list_recommendation_candidates(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT name, office, office_type, faction, status, reason_code, status_reason FROM characters WHERE name != ? AND power_id='ming' AND faction != '流寇' AND office_type NOT IN ('后宫','宗藩','未仕') AND status IN ('active','offstage','retired','dismissed') AND NOT (debut_year > 0 AND (debut_year > ? OR (debut_year = ? AND debut_month > ?))) ORDER BY name", params).fetchall()

    def read_resolve_target_faction_identity(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT faction, identity FROM characters WHERE name = ?', params).fetchall()

    def write_seed_opening_world(self, params: Any = ()) -> Any:
        return self._conn.executemany('\n            INSERT INTO office_slots\n                (office_title, office_type, region_id, jurisdiction, sort_order)\n            VALUES (?, ?, ?, ?, ?)\n            ', params)

    def write_ensure_office_type_parents_owned(self, params: Any, fragment_1: str) -> Any:
        return self._conn.execute(f'DELETE FROM offices WHERE office_type IN ({fragment_1})', params)

    def read_list_active_authorities_owned(self, params: Any, fragment_1: str) -> Any:
        return self._conn.execute(f'SELECT * FROM authority_records WHERE revoked=0 AND effective_turn<=? AND (expires_turn IS NULL OR expires_turn>=?){fragment_1} ORDER BY id', params)
