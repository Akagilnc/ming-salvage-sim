"""Issue rows and issue advances.

#1889: one write port. Phase, status and bar arithmetic stay with the caller.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ming_sim.applier import atomic, load_stored_json, load_stored_list, load_stored_object
from ming_sim.entities.column_write import bind_affair_once, checked_columns


def _decision_json_fields(row: Any) -> Tuple[list, object, list]:
    """pending_decisions 三列 JSON。空白是空名单 / 未选；在场损坏即拒。"""
    options = load_stored_list(row["options_json"], label="options_json")
    prior = load_stored_list(row["prior_options_json"], label="prior_options_json")
    choice = load_stored_json(row["choice_json"], label="choice_json", blank=None)
    return options, choice, prior


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
    "source_pending_action_id",
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

    def row(self, issue_id: int):
        return self._conn.execute(
            "SELECT * FROM issues WHERE id=?", (int(issue_id),),
        ).fetchone()

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

    def read_find_active_issue_by_origin(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? AND status='active' LIMIT 1", params).fetchone()

    def read_find_any_issue_by_origin(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? LIMIT 1', params).fetchone()

    def read_trigger_commitment_backlashes(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, title, closed_turn, commitment_kind, origin_ref FROM issues WHERE id=?', params).fetchone()

    def read_trigger_commitment_backlashes_title(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT title FROM issues WHERE id=?', params).fetchone()

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
        return self._conn.execute("SELECT id FROM issues WHERE origin_ref=? AND status='active' AND kind='initiative'", params).fetchall()

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


    def write_ensure_event_parent(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            INSERT OR IGNORE INTO events\n            (id, title, kind, summary, urgency, severity, credibility, interests, audiences)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n            ', params)

    def write_record_event_decision_choice(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            INSERT INTO event_triggers\n                (event_id, turn, year, period, source, terminal_state, terminal_reason, choice_json)\n            VALUES (?, ?, ?, ?, ?, '', ?, ?)\n            ON CONFLICT(event_id) DO UPDATE SET\n                -- 终态账不可逆（codex correctness）：HITL 选择只暂存 choice_json；新行不抢先\n                -- 写 triggered，待 phase2 的 event_pool 正常立局势后再由 mark_event_triggered 补终态。\n                -- 冲突时**保留**已有 terminal_state——\n                -- HITL 选择只补 choice_json，绝不把已有的 expired/avoided/obsolete 翻成\n                -- triggered。source 同理：只有空终态暂存行或已是 triggered 的行才更新成\n                -- hitl_decision，expired/avoided/obsolete 不被误标。\n                source = CASE\n                    WHEN COALESCE(event_triggers.terminal_state, '') IN ('', 'triggered')\n                    THEN excluded.source\n                    ELSE event_triggers.source\n                END,\n                terminal_state = event_triggers.terminal_state,\n                terminal_reason = CASE\n                    WHEN COALESCE(event_triggers.terminal_state, '') = ''\n                    THEN excluded.terminal_reason\n                    WHEN COALESCE(event_triggers.terminal_reason, '') = ''\n                    THEN excluded.terminal_reason\n                    ELSE event_triggers.terminal_reason\n                END,\n                choice_json = excluded.choice_json\n            ", params)

    def write_record_event_petition_answer(self, params: Any = ()) -> Any:
        return self._conn.execute(
            """
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason, choice_json)
            VALUES (?, ?, ?, ?, 'petition', '', '', ?)
            ON CONFLICT(event_id) DO UPDATE SET
                choice_json = excluded.choice_json
            """,
            params,
        )

    def read_event_petition_trigger_rows(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "SELECT rowid, event_id, turn, year, period, terminal_state, "
            "terminal_reason, choice_json FROM event_triggers",
            params,
        ).fetchall()

    def read_has_event_triggered(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered' LIMIT 1", params).fetchone()

    def read_event_terminal_state(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT terminal_state FROM event_triggers WHERE event_id=? LIMIT 1', params).fetchone()

    def read_has_event_terminal_state(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state=? LIMIT 1', params).fetchone()

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
            "(turn, year, period, event_id, actor, text, source, status, notes, dossier_payload_json, source_pending_action_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", params,
        )

    def add_directive(
        self,
        turn: int,
        year: int,
        period: int,
        event_id: Optional[int],
        text: str,
        source: str,
        actor: str = "",
        notes: str = "",
        status: str = "draft",
        dossier_payload: Optional[Dict[str, object]] = None,
    ) -> int:
        """Insert one turn_directives row; encoding + atomic commit live here."""
        # status: 'draft'=已确认颁诏候选；'pending'=大臣拟旨待皇帝核定。
        with atomic(SimpleNamespace(conn=self._conn)):
            cursor = self.insert_directive(
                (
                    int(turn), int(year), int(period), event_id,
                    actor or None, text, source, status, notes,
                    json.dumps(dossier_payload or {}, ensure_ascii=False),
                    0,
                ),
            )
            return int(cursor.lastrowid)

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

    def directive_ids_for_pending_actions(self, pending_action_ids: list[int]) -> list[int]:
        if not pending_action_ids:
            return []
        placeholders = ",".join("?" for _ in pending_action_ids)
        rows = self._conn.execute(
            "SELECT id FROM turn_directives "
            f"WHERE source_pending_action_id IN ({placeholders}) ORDER BY id",
            tuple(int(i) for i in pending_action_ids),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def directive(self, directive_id: int) -> Any:
        return self._conn.execute(
            "SELECT id, text, status, turn, dossier_payload_json FROM turn_directives WHERE id=?",
            (directive_id,),
        ).fetchone()

    @staticmethod
    def decode_directive_dossier_payload(
        raw: object, *, directive_id: int | None = None,
    ) -> Dict[str, object]:
        """Strict durable decode of turn_directives.dossier_payload_json."""
        label = f"旨稿#{directive_id}" if directive_id is not None else "既有旨稿"
        return load_stored_object(raw, label=f"{label} 结构化载荷")

    def read_directive_dossier_payload(self, row: object) -> Dict[str, object]:
        """Strictly decode a durable turn_directives payload at the issue read seam."""
        return self.decode_directive_dossier_payload(
            row["dossier_payload_json"], directive_id=int(row["id"]),
        )

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

    # --- pending_decisions / rescript desk moved from GameDB (#1889 J1) ---
    def save_pending_decisions(self, turn: int, decisions: List[Dict[str, object]]) -> None:
        """覆写本回合待裁 decision 行（先清后插），idx 按列表顺序。choice 初始空（待皇帝选）。

        #656 A6/F2 不变式：只清只写 kind='decision'（与 clear_pending_decisions/
        save_rescript_drafts 同款按 kind 收窄）——'rescript_draft' 票拟行跨月留存，
        不被 decision 盘面覆写连带清除。
        """
        turn = int(turn)
        # 两种 kind 共用 (turn, idx) 主键。先把保留的 draft 搬到负数暂存区，
        # 删除旧 decisions 后再按新盘面长度接续重排；draft 的内容与 event_id
        # 均不改，decision 数量增减也不会与旧 draft idx 相撞。
        self._conn.execute(
            "UPDATE pending_decisions SET idx = -idx - 1 "
            "WHERE turn = ? AND kind = 'rescript_draft'",
            (turn,),
        )
        draft_rows = self._conn.execute(
            "SELECT idx FROM pending_decisions "
            "WHERE turn = ? AND kind = 'rescript_draft' ORDER BY idx DESC",
            (turn,),
        ).fetchall()
        self._delete_pending_decision_rows(turn)
        for idx, d in enumerate(decisions):
            self._conn.execute(
                """INSERT INTO pending_decisions
                   (turn, idx, event_id, title, context, rejection_reason, opposition,
                    options_json, choice_json, status, kind)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', 'pending', 'decision')""",
                (
                    turn, idx,
                    str(d.get("event_id") or ""),
                    str(d.get("title") or ""),
                    str(d.get("context") or ""),
                    str(d.get("rejection_reason") or ""),
                    str(d.get("opposition") or ""),
                    json.dumps(d.get("options") or [], ensure_ascii=False),
                ),
            )
        for offset, row in enumerate(draft_rows):
            self._conn.execute(
                "UPDATE pending_decisions SET idx = ? WHERE turn = ? AND idx = ?",
                (len(decisions) + offset, turn, int(row["idx"])),
            )
        self._conn.commit()

    def list_pending_decisions(self, turn: int) -> List[Dict[str, object]]:
        """读本回合决策点（按 idx）——HITL envelope 唯一读取缝。

        #656 A6：谓词收窄到 kind='decision'——persist-then-abort 后落库的
        rescript_draft 票拟行不再混进亲裁/刷新/all-decided/submit 消费面
        （急务只经 list_rescript_drafts 读，批红面归 #657）；调用方不再重复过滤。
        options 反序列化；choice 为已选则带出。
        #657：补 revision_round / prior_options_json 投影。
        """
        rows = self._conn.execute(
            "SELECT idx, event_id, title, context, rejection_reason, opposition, "
            "options_json, choice_json, status, kind, actor_name, actor_office, actor_faction, "
            "turn, revision_round, prior_options_json "
            "FROM pending_decisions WHERE turn = ? AND kind = 'decision' ORDER BY idx",
            (int(turn),),
        ).fetchall()
        out: List[Dict[str, object]] = []
        for r in rows:
            options, choice, prior = _decision_json_fields(r)
            source_turn = int(r["turn"])
            idx = int(r["idx"])
            kind = str(r["kind"] or "decision")
            out.append({
                "idx": idx,
                "decision_key": f"{kind}:{source_turn}:{idx}",
                "source_turn": source_turn,
                "turn": source_turn,
                "event_id": r["event_id"],
                "title": r["title"],
                "context": r["context"],
                "rejection_reason": r["rejection_reason"],
                "opposition": r["opposition"],
                "options": options,
                "choice": choice,
                "status": r["status"],
                "kind": kind,
                "actor_name": r["actor_name"],
                "actor_office": r["actor_office"],
                "actor_faction": r["actor_faction"],
                "revision_round": int(r["revision_round"] or 0),
                "prior_options_json": prior,
            })
        return out

    def _delete_pending_decision_rows(self, turn: int) -> None:
        """Single delete rule for kind='decision' rows (no commit)."""
        self._conn.execute(
            "DELETE FROM pending_decisions WHERE turn = ? AND kind = 'decision'",
            (int(turn),),
        )

    def list_rescript_drafts(self) -> List[Dict[str, object]]:
        """#656：全部急务票拟行（kind='rescript_draft'），跨月留存待 #657 批红面消费。

        #657：补 choice / revision_round / prior_options_json 投影（list 面保留）。
        """
        rows = self._conn.execute(
            "SELECT turn, idx, event_id, title, context, options_json, choice_json, status, "
            "actor_name, actor_office, actor_faction, revision_round, prior_options_json "
            "FROM pending_decisions WHERE kind = 'rescript_draft' ORDER BY turn, idx"
        ).fetchall()
        out: List[Dict[str, object]] = []
        for r in rows:
            options, choice, prior = _decision_json_fields(r)
            out.append({
                "turn": int(r["turn"]),
                "idx": int(r["idx"]),
                "event_id": r["event_id"],
                "title": r["title"],
                "context": r["context"],
                "options": options,
                "choice": choice,
                "status": r["status"],
                "actor_name": r["actor_name"],
                "actor_office": r["actor_office"],
                "actor_faction": r["actor_faction"],
                "revision_round": int(r["revision_round"] or 0),
                "prior_options_json": prior,
            })
        return out

    def _project_rescript_desk_row(self, r: Any) -> Dict[str, object]:
        """pending_decisions 行 → desk 投影（pending/decided 共用）。"""
        kind = str(r["kind"] or "decision")
        source_turn = int(r["turn"])
        idx = int(r["idx"])
        options, choice, prior = _decision_json_fields(r)
        return {
            "decision_key": f"{kind}:{source_turn}:{idx}",
            "kind": kind,
            "source_turn": source_turn,
            "turn": source_turn,
            "idx": idx,
            "event_id": r["event_id"],
            "title": r["title"],
            "context": r["context"],
            "rejection_reason": r["rejection_reason"] or "",
            "opposition": r["opposition"] or "",
            "options": options,
            "choice": choice,
            "status": r["status"],
            "actor_name": r["actor_name"],
            "actor_office": r["actor_office"],
            "actor_faction": r["actor_faction"],
            "revision_round": int(r["revision_round"] or 0),
            "prior_options_json": prior,
        }

    def list_rescript_desk(self, turn: int) -> List[Dict[str, object]]:
        """#657 批红案头唯一合并读出口。"""
        turn = int(turn)
        rows = self._conn.execute(
            """
            SELECT turn, idx, event_id, title, context, rejection_reason, opposition,
                   options_json, choice_json, status, kind,
                   actor_name, actor_office, actor_faction,
                   revision_round, prior_options_json
            FROM pending_decisions
            WHERE status = 'pending'
              AND (
                    kind = 'rescript_draft'
                    OR (kind = 'decision' AND turn = ?)
                  )
            ORDER BY
              CASE kind WHEN 'rescript_draft' THEN 0 ELSE 1 END,
              turn, idx
            """,
            (turn,),
        ).fetchall()
        return [self._project_rescript_desk_row(r) for r in rows]

    def get_rescript_desk_rows_by_keys(
        self, keys: Sequence[str],
    ) -> List[Dict[str, object]]:
        """按 decision_key 取 desk 行（含 decided）。"""
        out: List[Dict[str, object]] = []
        seen: set[str] = set()
        for raw in keys:
            key = str(raw or "").strip()
            if not key or key in seen:
                continue
            parts = key.split(":")
            if len(parts) != 3:
                continue
            kind, turn_s, idx_s = parts
            try:
                turn_i, idx_i = int(turn_s), int(idx_s)
            except (TypeError, ValueError):
                continue
            if kind not in {"rescript_draft", "decision"}:
                continue
            r = self._conn.execute(
                """
                SELECT turn, idx, event_id, title, context, rejection_reason, opposition,
                       options_json, choice_json, status, kind,
                       actor_name, actor_office, actor_faction,
                       revision_round, prior_options_json
                FROM pending_decisions
                WHERE turn = ? AND idx = ? AND kind = ?
                """,
                (turn_i, idx_i, kind),
            ).fetchone()
            if r is None:
                continue
            seen.add(key)
            out.append(self._project_rescript_desk_row(r))
        return out

    def cas_revise_pending_decision(
        self,
        *,
        revision_round: int,
        options_json: str,
        prior_options_json: str,
        choice_json: str,
        turn: int,
        idx: int,
        kind: str,
        expected_round: int,
    ) -> int:
        cur = self._conn.execute(
            "UPDATE pending_decisions SET revision_round = ?, options_json = ?, "
            "prior_options_json = ?, choice_json = ?, status = 'pending' "
            "WHERE turn = ? AND idx = ? AND kind = ? AND revision_round = ? "
            "AND status = 'pending'",
            (
                int(revision_round), options_json, prior_options_json, choice_json,
                int(turn), int(idx), kind, int(expected_round),
            ),
        )
        return int(cur.rowcount)

    def cas_decide_pending_decision(
        self, *, choice_json: str, turn: int, idx: int, kind: str,
    ) -> int:
        cur = self._conn.execute(
            "UPDATE pending_decisions SET choice_json = ?, status = 'decided' "
            "WHERE turn = ? AND idx = ? AND kind = ? AND status = 'pending'",
            (choice_json, int(turn), int(idx), kind),
        )
        return int(cur.rowcount)

    def clear_pending_choice_json(
        self, *, turn: int, idx: int, kind: str,
    ) -> None:
        self._conn.execute(
            "UPDATE pending_decisions SET choice_json = '{}' "
            "WHERE turn = ? AND idx = ? AND kind = ? AND status = 'pending'",
            (int(turn), int(idx), kind),
        )

    def list_pending_drafts_with_choice(self) -> Any:
        return self._conn.execute(
            "SELECT turn, idx, kind, status, choice_json, revision_round "
            "FROM pending_decisions "
            "WHERE status = 'pending' AND kind = 'rescript_draft' "
            "AND choice_json IS NOT NULL AND TRIM(choice_json) NOT IN ('', '{}')"
        ).fetchall()

    def list_directives_by_turn(self, turn: int) -> list[dict[str, object]]:
        """读某回合已颁诏（issued）草案，按 id 升序。"""
        rows = self.read_list_directives_by_turn_owned((int(turn),)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "event_id": r["event_id"] or "",
                "event_title": r["event_title"] or "",
                "actor": r["actor"] or "",
                "text": r["text"] or "",
                "source": r["source"] or "",
                "status": r["status"] or "",
                "notes": r["notes"] or "",
                "created_at": r["created_at"] or "",
                "updated_at": r["updated_at"] or "",
            }
            for r in rows
        ]

    def list_issued_directives(self) -> list[dict[str, object]]:
        """读出所有已颁明发旨意，供跨回合公开见闻投影使用。"""
        rows = self.read_list_issued_directives_owned(()).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "event_id": r["event_id"] or "",
                "event_title": r["event_title"] or "",
                "actor": r["actor"] or "",
                "text": r["text"] or "",
                "source": r["source"] or "",
                "status": r["status"] or "",
                "notes": r["notes"] or "",
            }
            for r in rows
        ]

    def list_directives(
        self, turn: int, statuses: tuple[str, ...] = ("draft",),
    ) -> list:
        placeholders = ",".join("?" for _ in statuses)
        return self.read_list_directives_owned(
            (int(turn), int(turn), *statuses), placeholders,
        ).fetchall()

    def count_pending_directives_for_turn(self, turn: int) -> int:
        row = self.count_pending_directives(int(turn))
        return int(row["n"]) if row else 0

    def list_commitments_for_dossier(self, dossier_id: int) -> list[dict[str, object]]:
        rows = self.read_list_commitments_for_dossier((f"dossier:{int(dossier_id)}",))
        return [dict(row) for row in rows]

    def has_event_triggered(self, event_id: str) -> bool:
        row = self.read_has_event_triggered((event_id,))
        return row is not None

    def event_terminal_state(self, event_id: str) -> str | None:
        row = self.read_event_terminal_state((event_id,))
        return row["terminal_state"] if row is not None else None

    def has_event_terminal_state(self, event_id: str, terminal_state: str) -> bool:
        row = self.read_has_event_terminal_state((event_id, terminal_state))
        return row is not None

    def list_event_petition_records(self) -> list[dict[str, object]]:
        """三饷请旨的「已呈／原批语」持久读口（#1892 供料侧）。"""
        from ming_sim.exceptions import SettlementAbort

        out: list[dict[str, object]] = []
        for r in self.read_event_petition_trigger_rows():
            raw = str(r["choice_json"] or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SettlementAbort(
                    "event_triggers.choice_json 解析失败 "
                    f"event_id={r['event_id']!r} rowid={r['rowid']}",
                    turn=int(r["turn"] or 0),
                    stage="petition_records",
                ) from exc
            if not isinstance(payload, dict):
                continue
            petition = payload.get("petition")
            if not isinstance(petition, dict):
                continue
            out.append({
                **{key: value for key, value in payload.items() if key != "petition"},
                "event_id": str(r["event_id"] or ""),
                "turn": int(r["turn"] or 0),
                "year": int(r["year"] or 0),
                "period": int(r["period"] or 0),
                "terminal_state": str(r["terminal_state"] or ""),
                "terminal_reason": str(r["terminal_reason"] or ""),
                "petition": dict(petition),
            })
        return out
