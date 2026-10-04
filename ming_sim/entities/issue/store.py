"""Issue rows and issue advances.

#1889: one write port. Phase, status and bar arithmetic stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.entities.column_write import bind_affair_once, checked_columns


ISSUE_COLUMNS = frozenset({
    "kind", "title", "origin_kind", "origin_ref", "origin_turn",
    "bar_value", "bar_good_meaning", "bar_bad_meaning", "inertia",
    "phase", "stage_text", "status", "severity", "region_hint", "faction_hint",
    "tags", "participants", "participant_roster", "target_roster",
    "ongoing_effects", "cancellable", "cancel_cost",
    "effect_on_resolve", "effect_on_fail", "resolve_condition", "fail_condition",
    "end_turn", "stop_condition", "commitment_kind", "stages_json",
    "resolution_summary", "last_advance_turn", "closed_turn", "affair_id",
})

TURN_DIRECTIVE_COLUMNS = frozenset({
    "id", "turn", "year", "period", "event_id", "actor", "text", "source",
    "status", "notes", "dossier_payload_json", "created_at", "updated_at",
})

_ADVANCE_COLUMNS = (
    "issue_id", "turn", "trigger_kind", "trigger_ref", "delta_bar",
    "from_value", "to_value", "from_stage_text", "to_stage_text",
    "narrative", "metric_delta",
)


def _checked(values: Mapping[str, object]) -> list[str]:
    return checked_columns(values, ISSUE_COLUMNS, what="issues")


class IssueStore:
    """Single write port for an issue and its advances."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert(self, row: Mapping[str, object]) -> int:
        columns = _checked(row)
        if not columns:
            raise ValueError("issues insert needs fields")
        placeholders = ", ".join("?" for _ in columns)
        cursor = self._conn.execute(
            f"INSERT INTO issues ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )
        return int(cursor.lastrowid)

    def update(self, issue_id: int, values: Mapping[str, object]) -> int:
        columns = _checked(values)
        if not columns:
            raise ValueError("issues update needs fields")
        assignments = ", ".join(f"{column}=?" for column in columns)
        cursor = self._conn.execute(
            f"UPDATE issues SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [values[column] for column in columns] + [int(issue_id)],
        )
        return int(cursor.rowcount or 0)

    def append_advance(self, row: Mapping[str, object]) -> None:
        checked_columns(row, set(_ADVANCE_COLUMNS), what="issue_advances")
        columns = [column for column in _ADVANCE_COLUMNS if column in row]
        if "issue_id" not in columns or "turn" not in columns or "trigger_kind" not in columns:
            raise ValueError("issue_advances needs issue_id, turn, trigger_kind")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO issue_advances ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def has_active_for_affair(self, affair_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM issues WHERE affair_id=? AND status='active' LIMIT 1",
            (int(affair_id),),
        ).fetchone() is not None

    def affair_id_of(self, issue_id: int) -> int:
        row = self._conn.execute(
            "SELECT affair_id FROM issues WHERE id=?", (int(issue_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"局势不存在：{issue_id}")
        return int(row["affair_id"] or 0)

    def active_rows(self, kind: str | None = None) -> Any:
        sql = "SELECT * FROM issues WHERE status='active'"
        args: list[object] = []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        return self._conn.execute(sql + " ORDER BY severity DESC,id ASC", args).fetchall()

    def set_affair_id_if_unbound(self, issue_id: int, affair_id: int) -> int:
        return bind_affair_once(self._conn, "issues", int(issue_id), affair_id)

    def read_assert_commission_grant_target_exists(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM issues WHERE id=?', params).fetchone()

    def read_dispatch_rushes(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, status, stages_json FROM issues WHERE id=?', params).fetchone()

    def read_ack_due_commitment_issue(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM issues WHERE id=?', params).fetchone()

    def read_event_issue_refs(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT origin_ref FROM issues WHERE origin_kind='event_pool'", params).fetchall()

    def read_apply_issue_tracker_output(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status FROM issues WHERE id=?', params).fetchone()

    def read_apply_score_extraction_body(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT ongoing_effects FROM issues WHERE id=?', params).fetchone()

    def read_gather_impeachment_surge_candidates(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT 1 FROM issues WHERE origin_kind='impeachment_surge' AND origin_ref=? AND faction_hint=? LIMIT 1", params).fetchone()

    def read_list_commitments_for_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM issues WHERE origin_ref=? ORDER BY id', params).fetchall()

    def read_list_closed_issues_at(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM issues WHERE closed_turn = ? AND status IN ('resolved','failed','dropped') ORDER BY id", params).fetchall()

    def read_count_active_initiatives(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT COUNT(*) AS n FROM issues WHERE kind='initiative' AND status='active'", params).fetchone()

    def read_find_active_issue_by_origin(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? AND status='active' LIMIT 1", params).fetchone()

    def read_find_any_issue_by_origin(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? LIMIT 1', params).fetchone()

    def read_trigger_commitment_backlashes(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, title, closed_turn, commitment_kind, origin_ref FROM issues WHERE id=?', params).fetchone()

    def read_trigger_commitment_backlashes_title(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT title FROM issues WHERE id=?', params).fetchone()

    def read_apply_revoke_decree_verdict_effect(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT kind, status, origin_ref FROM issues WHERE id=?', params).fetchone()

    def read_apply_punishment_verdict_effect(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status,origin_kind,faction_hint,target_roster FROM issues WHERE id=?', params).fetchone()

    def read_build_translation_target_grounding(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, title, stages_json FROM issues WHERE status='active' ORDER BY id", params).fetchall()

    def read_apply_imperial_deliberation_push(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, status FROM issues WHERE origin_ref=? AND status='active' LIMIT 1", params).fetchone()

    def read_apply_deliberate(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM issues WHERE origin_ref=? LIMIT 1', params).fetchone()

    def read_list_due_stages_for_scan(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT id, title, stages_json, origin_ref, origin_turn, stage_text\n        FROM issues\n        WHERE status='active'\n          AND commitment_kind != ''\n          AND stages_json IS NOT NULL\n          AND stages_json != ''\n          AND stages_json != '[]'\n        ORDER BY id\n        ", params).fetchall()

    def read_list_active_commitments(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT * FROM issues\n        WHERE status='active'\n          AND kind='initiative'\n          AND commitment_kind != ''\n        ORDER BY id\n        ", params).fetchall()

    def read_stop_origin_commitment_ticks(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id FROM issues WHERE origin_ref=? AND status='active'", params).fetchall()

    def read_try_defer_revoke_to_breach_plea(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT id FROM issues\n            WHERE origin_ref=? AND status='active' AND commitment_kind != ''\n            ", params).fetchall()

    def read_try_defer_revoke_to_breach_plea_id_status_commitment_kind(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, status, commitment_kind FROM issues WHERE id=?', params).fetchone()

    def read_issue_exists(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM issues WHERE id=?', params).fetchone()

    def read_rush_staged_commitment_stage(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, stages_json, status, commitment_kind FROM issues WHERE id=?', params).fetchone()

    def read_rush_staged_commitment_stage_origin_ref(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT origin_ref FROM issues WHERE id=?', params).fetchone()

    def read_resolve_host_character(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT participants, participant_roster FROM issues WHERE id=?', params).fetchone()

    def read_issue_for_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM issues WHERE origin_ref=? ORDER BY id LIMIT 1', params).fetchone()

    def read_list_due_commitments(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT * FROM issues\n        WHERE status='active'\n          AND commitment_kind != ''\n          AND end_turn > 0\n          AND end_turn <= ?\n        ORDER BY id\n        ", params).fetchall()

    def read_issue_meta(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, title, origin_ref, stages_json, stage_text FROM issues WHERE id=?', params).fetchone()

    def read_stalled_deliberation_push_facts(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, title FROM issues WHERE origin_ref=? AND status='active' LIMIT 1", params).fetchone()

    def read_commitment_ids_for_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id FROM issues WHERE origin_ref=?', params).fetchall()

    def read_stage_punishment_candidate(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT origin_kind,status,target_roster FROM issues WHERE id=?', params).fetchone()

    def write_canonicalize_existing_fiscal_levy_terminal_reason(self, params: Any = ()) -> Any:
        return self._conn.execute('UPDATE event_triggers SET terminal_reason=? WHERE event_id=?', params)

    def read_latest_commitment_paid_total(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id DESC', params).fetchall()

    def read_event_terminal_states(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT event_id, terminal_state FROM event_triggers', params).fetchall()

    def read_event_terminal_records(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT event_id, terminal_state, terminal_reason FROM event_triggers', params).fetchall()

    def read_event_pending_choice_records(self, params: Any = ()) -> Any:
        return self._conn.execute("\n        SELECT event_id, terminal_state, terminal_reason, source\n        FROM event_triggers\n        WHERE COALESCE(terminal_state, '') = ''\n          AND COALESCE(terminal_reason, '') != ''\n        ", params).fetchall()

    def write_ensure_event_parent(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            INSERT OR IGNORE INTO events\n            (id, title, kind, summary, urgency, severity, credibility, interests, audiences)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n            ', params)

    def write_record_event_decision_choice(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            INSERT INTO event_triggers\n                (event_id, turn, year, period, source, terminal_state, terminal_reason, choice_json)\n            VALUES (?, ?, ?, ?, ?, '', ?, ?)\n            ON CONFLICT(event_id) DO UPDATE SET\n                -- 终态账不可逆（codex correctness）：HITL 选择只暂存 choice_json；新行不抢先\n                -- 写 triggered，待 phase2 的 event_pool 正常立局势后再由 mark_event_triggered 补终态。\n                -- 冲突时**保留**已有 terminal_state——\n                -- HITL 选择只补 choice_json，绝不把已有的 expired/avoided/obsolete 翻成\n                -- triggered。source 同理：只有空终态暂存行或已是 triggered 的行才更新成\n                -- hitl_decision，expired/avoided/obsolete 不被误标。\n                source = CASE\n                    WHEN COALESCE(event_triggers.terminal_state, '') IN ('', 'triggered')\n                    THEN excluded.source\n                    ELSE event_triggers.source\n                END,\n                terminal_state = event_triggers.terminal_state,\n                terminal_reason = CASE\n                    WHEN COALESCE(event_triggers.terminal_state, '') = ''\n                    THEN excluded.terminal_reason\n                    WHEN COALESCE(event_triggers.terminal_reason, '') = ''\n                    THEN excluded.terminal_reason\n                    ELSE event_triggers.terminal_reason\n                END,\n                choice_json = excluded.choice_json\n            ", params)

    def read_has_event_triggered(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered' LIMIT 1", params).fetchone()

    def read_event_terminal_state(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT terminal_state FROM event_triggers WHERE event_id=? LIMIT 1', params).fetchone()

    def read_has_event_terminal_state(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state=? LIMIT 1', params).fetchone()

    def read_list_recent_issue_advances(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM issue_advances WHERE issue_id=? ORDER BY id DESC LIMIT ?', params).fetchall()

    def read_ensure_event_parent(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM events WHERE id=?', params).fetchone()

    def read_issue_audience_names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT audiences FROM events WHERE id=?', params).fetchone()

    def read_eval_gate_key_str_owned(self, params: Any, fragment_1: str) -> Any:
        return self._conn.execute(f'SELECT {fragment_1} FROM event_triggers WHERE event_id=?', params)

    def write_mark_event_triggered_owned(self, params: Any) -> Any:
        return self._conn.execute(f"\n            INSERT INTO event_triggers\n                (event_id, turn, year, period, source, terminal_state, terminal_reason)\n            VALUES (?, ?, ?, ?, ?, 'triggered', ?)\n            ON CONFLICT(event_id) DO UPDATE SET\n                {self._event_terminal_upgrade_assignments(fill_triggered_reason=True)}\n            ", params)

    def write_mark_event_avoided_owned(self, params: Any) -> Any:
        return self._conn.execute(f"\n            INSERT INTO event_triggers\n                (event_id, turn, year, period, source, terminal_state, terminal_reason)\n            VALUES (?, ?, ?, ?, ?, 'avoided', ?)\n            ON CONFLICT(event_id) DO UPDATE SET\n                {self._event_terminal_upgrade_assignments()}\n            ", params)

    def write_mark_event_obsolete_owned(self, params: Any) -> Any:
        return self._conn.execute(f"\n            INSERT INTO event_triggers\n                (event_id, turn, year, period, source, terminal_state, terminal_reason)\n            VALUES (?, ?, ?, ?, ?, 'obsolete', ?)\n            ON CONFLICT(event_id) DO UPDATE SET\n                {self._event_terminal_upgrade_assignments()}\n            ", params)

    def write_mark_event_expired_owned(self, params: Any) -> Any:
        return self._conn.execute(f"\n            INSERT INTO event_triggers\n                (event_id, turn, year, period, source, terminal_state, terminal_reason)\n            VALUES (?, ?, ?, ?, 'window_expired', 'expired', '过最晚触发时点仍未达成触发门')\n            ON CONFLICT(event_id) DO UPDATE SET\n                {self._event_terminal_upgrade_assignments()}\n            ", params)

    def insert_directive(self, params: Any) -> Any:
        return self._conn.execute(
            "INSERT INTO turn_directives "
            "(turn, year, period, event_id, actor, text, source, status, notes, dossier_payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", params,
        )

    def snapshot_directive_rows(self) -> Any:
        return self._conn.execute("SELECT * FROM turn_directives").fetchall()

    def restore_directive_row(self, row: Mapping[str, object]) -> None:
        from ming_sim.entities.column_write import upsert_by_pk
        upsert_by_pk(
            self._conn, "turn_directives", row, pk="id",
            allowed=TURN_DIRECTIVE_COLUMNS, what="turn_directives",
        )

    def delete_directive_row(self, directive_id: object) -> None:
        self._conn.execute("DELETE FROM turn_directives WHERE id=?", (directive_id,))

    def directive(self, directive_id: int) -> Any:
        return self._conn.execute(
            "SELECT id, text, status, turn, dossier_payload_json FROM turn_directives WHERE id=?",
            (directive_id,),
        ).fetchone()

    def set_directive_status(self, directive_id: int, status: str, *, expected: str | None = None) -> Any:
        sql = "UPDATE turn_directives SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?"
        params = [status, directive_id]
        if expected is not None:
            sql += " AND status=?"
            params.append(expected)
        return self._conn.execute(sql, params)

    def count_pending_directives(self, turn: int) -> Any:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM turn_directives WHERE turn=? AND status='pending'", (turn,),
        ).fetchone()

    def update_directive_text(self, params: Any) -> Any:
        return self._conn.execute(
            "UPDATE turn_directives SET text=?, dossier_payload_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            params,
        )

    def mark_directives_issued(self, ids: Any) -> None:
        placeholders = ','.join('?' for _ in ids)
        self._conn.execute(
            f"UPDATE turn_directives SET status='issued', updated_at=CURRENT_TIMESTAMP "
            f"WHERE id IN ({placeholders}) AND status='draft'", ids,
        )

    def delete_draft_directive(self, directive_id: int) -> None:
        self._conn.execute("DELETE FROM turn_directives WHERE id=? AND status='draft'", (directive_id,))

    def directives_by_ids(self, ids: Any) -> Any:
        placeholders = ','.join('?' for _ in ids)
        return self._conn.execute(
            "SELECT td.id AS directive_id, td.turn, td.year, td.period, td.actor, td.text, td.status "
            f"FROM turn_directives td WHERE td.id IN ({placeholders}) ORDER BY td.id", ids,
        ).fetchall()

    def directive_archive_months(self) -> Any:
        return self._conn.execute("SELECT turn, year, period FROM turn_directives WHERE status='issued'").fetchall()

    def read_list_directives_by_turn_owned(self, params: Any) -> Any:
        return self._conn.execute("\n            SELECT d.id, d.turn, d.year, d.period, d.event_id, d.actor,\n                   d.text, d.source, d.status, d.notes,\n                   d.created_at, d.updated_at,\n                   e.title AS event_title\n            FROM turn_directives d\n            LEFT JOIN events e ON e.id = d.event_id\n            WHERE d.turn = ? AND d.status = 'issued'\n            ORDER BY d.id\n            ", params)

    def read_list_issued_directives_owned(self, params: Any) -> Any:
        return self._conn.execute("\n            SELECT d.id, d.turn, d.year, d.period, d.event_id, d.actor,\n                   d.text, d.source, d.status, d.notes,\n                   d.created_at, d.updated_at,\n                   e.title AS event_title\n            FROM turn_directives d\n            LEFT JOIN events e ON e.id = d.event_id\n            WHERE d.status = 'issued'\n            ORDER BY d.turn, d.id\n            ", params)

    def read_list_directives_owned(self, params: Any, fragment_1: str) -> Any:
        return self._conn.execute(f"\n            SELECT d.*, e.title AS event_title\n            FROM turn_directives d\n            LEFT JOIN events e ON e.id = d.event_id\n            WHERE (d.turn = ? OR (d.turn < ? AND d.status = 'draft'))\n              AND d.status IN ({fragment_1})\n            ORDER BY d.id\n            ", params)

    def _event_terminal_upgrade_assignments(self, *, fill_triggered_reason: bool = False) -> str:
        reason_fill = ""
        pending_reason_expr = "COALESCE(NULLIF(event_triggers.terminal_reason, ''), excluded.terminal_reason)"
        if fill_triggered_reason:
            pending_reason_expr = "COALESCE(NULLIF(excluded.terminal_reason, ''), event_triggers.terminal_reason)"
            reason_fill = """
                    WHEN event_triggers.terminal_state = 'triggered'
                      AND COALESCE(event_triggers.terminal_reason, '') = ''
                      AND excluded.terminal_reason <> ''
                    THEN excluded.terminal_reason
            """
        return f"""
                turn = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.turn
                    ELSE event_triggers.turn
                END,
                year = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.year
                    ELSE event_triggers.year
                END,
                period = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.period
                    ELSE event_triggers.period
                END,
                source = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.source
                    ELSE event_triggers.source
                END,
                terminal_state = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.terminal_state
                    ELSE event_triggers.terminal_state
                END,
                terminal_reason = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN {pending_reason_expr}
{reason_fill}                    ELSE event_triggers.terminal_reason
                END
        """
