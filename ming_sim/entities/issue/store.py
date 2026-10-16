"""Issue rows and issue advances.

#1889: one write port. Phase, status and bar arithmetic stay with the caller.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ming_sim.applier import atomic, load_stored_json, load_stored_list, load_stored_object
from ming_sim.entities.column_write import RowStore


def _decision_json_fields(row: Any) -> Tuple[list, object, list]:
    """pending_decisions：名单列须为 JSON；choice 的空白标记表示未选。"""
    options = load_stored_list(row["options_json"], label="options_json")
    prior = load_stored_list(row["prior_options_json"], label="prior_options_json")
    raw_choice = row["choice_json"]
    # schema 的 DEFAULT '' 及票拟重置写口以空白标记未选，不是 JSON 文档。
    choice = load_stored_json(
        None if isinstance(raw_choice, str) and not raw_choice.strip() else raw_choice,
        label="choice_json", blank=None,
    )
    return options, choice, prior


class IssueStore(RowStore):
    """Single write port for an issue and its advances."""

    TABLE = "issues"
    PK = "id"
    # issues 亦入召对前像：夜内直写（如大臣自诺）须可随 undo 逆转（ADR 0038）。
    TABLES = {"issues": "id", "turn_directives": "id"}
    TOUCH = True

    def active_rows(self, kind: str | None = None) -> Any:
        sql = "SELECT * FROM issues WHERE status='active'"
        args: list[object] = []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        return self._conn.execute(sql + " ORDER BY severity DESC,id ASC", args).fetchall()

    def active_by_origin(self, origin_kind: object, origin_ref: object) -> Any:
        return self._conn.execute(
            "SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? AND status='active' LIMIT 1",
            (origin_kind, origin_ref),
        ).fetchone()

    def by_origin(self, origin_kind: object, origin_ref: object) -> Any:
        return self._conn.execute(
            "SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? LIMIT 1",
            (origin_kind, origin_ref),
        ).fetchone()

    def active_commitments(self) -> Any:
        return self._conn.execute(
            "\n        SELECT * FROM issues\n        WHERE status='active'\n          AND kind='initiative'\n          AND commitment_kind != ''\n        ORDER BY id\n        ",
            (),
        ).fetchall()

    def insert_directive(
        self,
        turn: object,
        year: object,
        period: object,
        event_id: object,
        actor: object,
        text: object,
        source: object,
        status: object,
        notes: object,
        dossier_payload_json: object,
        source_pending_action_id: object,
    ) -> Any:
        return self._conn.execute(
            "INSERT INTO turn_directives "
            "(turn, year, period, event_id, actor, text, source, status, notes, "
            "dossier_payload_json, source_pending_action_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn,
                year,
                period,
                event_id,
                actor,
                text,
                source,
                status,
                notes,
                dossier_payload_json,
                source_pending_action_id,
            ),
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
                int(turn),
                int(year),
                int(period),
                event_id,
                actor or None,
                text,
                source,
                status,
                notes,
                json.dumps(dossier_payload or {}, ensure_ascii=False),
                0,
            )
            return int(cursor.lastrowid)

    @staticmethod
    def decode_directive_dossier_payload(
        raw: object, *, directive_id: int | None = None,
    ) -> Dict[str, object]:
        """Strict durable decode of turn_directives.dossier_payload_json."""
        label = f"旨稿#{directive_id}" if directive_id is not None else "既有旨稿"
        return load_stored_object(raw, label=f"{label} 结构化载荷")

    def directive_dossier_payload(self, row: object) -> Dict[str, object]:
        """Strictly decode a durable turn_directives payload at the issue read seam."""
        return self.decode_directive_dossier_payload(
            row["dossier_payload_json"], directive_id=int(row["id"]),
        )

    def record_event_terminal(
        self, event_id: str, *, turn: int, year: int, period: int,
        source: str, terminal_state: str, terminal_reason: str,
    ) -> None:
        self._conn.execute(
            f"""
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                {self._event_terminal_upgrade_assignments(fill_triggered_reason=terminal_state == 'triggered')}
            """,
            (event_id, turn, year, period, source, terminal_state, terminal_reason),
        )

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
    def save_pending_decisions(
        self, turn: int, decisions: List[Dict[str, object]],
    ) -> None:
        """Append new decisions without changing existing keys, answers or rescript drafts.

        Independent continuations may add questions while siblings remain open.
        Both kinds share (turn, idx), so allocate after every existing desk row.
        """
        turn = int(turn)
        existing = {r["event_id"] for r in self.list_pending_decisions(turn)}
        next_idx = self._conn.execute(
            "SELECT COALESCE(MAX(idx), -1) + 1 FROM pending_decisions WHERE turn=?", (turn,),
        ).fetchone()[0]
        for d in decisions:
            if str(d.get("event_id") or "") in existing:
                continue
            self.insert_pending_decision(
                turn,
                next_idx,
                str(d.get("event_id") or ""),
                str(d.get("title") or ""),
                str(d.get("context") or ""),
                str(d.get("rejection_reason") or ""),
                str(d.get("opposition") or ""),
                json.dumps(d.get("options") or [], ensure_ascii=False),
                "",
                "pending",
                "decision",
                "",
                "",
                "",
                0,
            )
            next_idx += 1
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
            "SELECT * "
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
            "answered_turn": int(r["answered_turn"] or 0),
            "answer_order": int(r["answer_order"] or 0),
            })
        return out

    def list_rescript_drafts(self, *, status: str | None = None) -> List[Dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM pending_decisions WHERE kind='rescript_draft' "
            "AND (? IS NULL OR status=?) ORDER BY presentation_order,turn,idx", (status, status),
        ).fetchall()
        return [self._project_rescript_desk_row(row) for row in rows]

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
            "answered_turn": int(r["answered_turn"] or 0),
            "answer_order": int(r["answer_order"] or 0),
        }

    def list_rescript_desk(self, turn: int) -> List[Dict[str, object]]:
        """#657 批红案头唯一合并读出口。"""
        turn = int(turn)
        rows = self._conn.execute(
            """
            SELECT *
            FROM pending_decisions
            WHERE status = 'pending'
              AND (
                    kind = 'rescript_draft'
                    OR (kind = 'decision' AND turn = ?)
                  )
            ORDER BY
              CASE kind WHEN 'rescript_draft' THEN 0 ELSE 1 END,
              presentation_order, turn, idx
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
                SELECT *
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

    def list_directives_by_turn(self, turn: int) -> list[dict[str, object]]:
        """读某回合已颁诏（issued）草案，按 id 升序。"""
        rows = self._conn.execute(
            "\n            SELECT d.id, d.turn, d.year, d.period, d.event_id, d.actor,\n                   d.text, d.source, d.status, d.notes,\n                   d.created_at, d.updated_at,\n                   e.title AS event_title\n            FROM turn_directives d\n            LEFT JOIN events e ON e.id = d.event_id\n            WHERE d.turn = ? AND d.status = 'issued'\n            ORDER BY d.id\n            ",
            (int(turn),),
        ).fetchall()
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
        rows = self._conn.execute(
            "\n            SELECT d.id, d.turn, d.year, d.period, d.event_id, d.actor,\n                   d.text, d.source, d.status, d.notes,\n                   d.created_at, d.updated_at,\n                   e.title AS event_title\n            FROM turn_directives d\n            LEFT JOIN events e ON e.id = d.event_id\n            WHERE d.status = 'issued'\n            ORDER BY d.turn, d.id\n            ",
            (),
        ).fetchall()
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
        return self._conn.execute(
            f"\n            SELECT d.*, e.title AS event_title\n            FROM turn_directives d\n            LEFT JOIN events e ON e.id = d.event_id\n            WHERE (d.turn = ? OR (d.turn < ? AND d.status = 'draft'))\n              AND d.status IN ({placeholders})\n            ORDER BY d.id\n            ",
            (int(turn), int(turn), *statuses),
        ).fetchall()

    def count_pending_directives_for_turn(self, turn: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM turn_directives WHERE turn=? AND status='pending'",
            (int(turn),),
        ).fetchone()
        return int(row["n"]) if row else 0

    def event_terminal_state(self, event_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=? LIMIT 1",
            (event_id,),
        ).fetchone()
        return row["terminal_state"] if row is not None else None

    def has_event_terminal_state(self, event_id: str, terminal_state: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state=? LIMIT 1",
            (event_id, terminal_state),
        ).fetchone()
        return row is not None

    def list_event_petition_records(self) -> list[dict[str, object]]:
        """三饷请旨的「已呈／原批语」持久读口（#1892 供料侧）。"""
        from ming_sim.exceptions import SettlementAbort

        out: list[dict[str, object]] = []
        for r in self._conn.execute(
            "SELECT rowid, event_id, turn, year, period, terminal_state, terminal_reason, choice_json FROM event_triggers",
            (),
        ).fetchall():
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

    def list_dossiered_draft_directives(self, turn: int) -> List[Dict[str, object]]:
        """Settlement projection: drafts whose dossier creation succeeded."""
        rows = self._conn.execute(
            """SELECT td.* FROM turn_directives td
               WHERE td.turn<=? AND td.status='draft'
                 AND EXISTS (SELECT 1 FROM decree_dossiers d WHERE d.directive_id=td.id)
               ORDER BY td.id""",
            (int(turn),),
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_advance(
        self,
        issue_id: object,
        turn: object,
        trigger_kind: object,
        trigger_ref: object,
        delta_bar: object,
        from_value: object,
        to_value: object,
        from_stage_text: object,
        to_stage_text: object,
        narrative: object,
        metric_delta: object,
    ) -> Any:
        return self._conn.execute(
            "INSERT INTO issue_advances "
            "(issue_id, turn, trigger_kind, trigger_ref, delta_bar, from_value, to_value, "
            "from_stage_text, to_stage_text, narrative, metric_delta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                issue_id,
                turn,
                trigger_kind,
                trigger_ref,
                delta_bar,
                from_value,
                to_value,
                from_stage_text,
                to_stage_text,
                narrative,
                metric_delta,
            ),
        )

    def insert_pending_decision(
        self,
        turn: object,
        idx: object,
        event_id: object,
        title: object,
        context: object,
        rejection_reason: object,
        opposition: object,
        options_json: object,
        choice_json: object,
        status: object,
        kind: object,
        actor_name: object,
        actor_office: object,
        actor_faction: object,
        presentation_order: object,
    ) -> Any:
        return self._conn.execute(
            """INSERT INTO pending_decisions
                       (turn, idx, event_id, title, context, rejection_reason, opposition,
                        options_json, choice_json,
                        status, kind, actor_name, actor_office, actor_faction, presentation_order)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                turn,
                idx,
                event_id,
                title,
                context,
                rejection_reason,
                opposition,
                options_json,
                choice_json,
                status,
                kind,
                actor_name,
                actor_office,
                actor_faction,
                presentation_order,
            ),
        )

    def record_rescript_answer(
        self, choice_json: str, answered_turn: int, source_turn: int, idx: int, kind: str,
    ) -> None:
        """Persist one answer in the next durable order of the answering turn."""
        self._conn.execute(
            "UPDATE pending_decisions SET choice_json=?, status='decided', answered_turn=?, "
            "answer_order=(SELECT COALESCE(MAX(answer_order),0)+1 "
            "FROM pending_decisions WHERE answered_turn=?) "
            "WHERE turn=? AND idx=? AND kind=? AND status='pending'",
            (choice_json, answered_turn, answered_turn, source_turn, idx, kind),
        )

    def directive_ids_for_pending_actions(
        self, pending_action_ids: list[int]
    ) -> list[int]:
        if not pending_action_ids:
            return []
        placeholders = ",".join("?" for _ in pending_action_ids)
        rows = self._conn.execute(
            "SELECT id FROM turn_directives "
            f"WHERE source_pending_action_id IN ({placeholders}) ORDER BY id",
            tuple(int(i) for i in pending_action_ids),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def append_rescript_drafts(
        self, turn: int, drafts: List[Dict[str, object]], *,
        revisions: Sequence[Dict[str, object]] = (),
    ) -> None:
        """收存模型顺序；修订保留原身份，与月链相位同事务。"""
        order = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(presentation_order), 0) FROM pending_decisions"
            ).fetchone()[0]
        )
        for item in revisions:
            order += 1
            self._conn.execute(
                "UPDATE pending_decisions SET title=?, context=?, options_json=?, choice_json='', "
                "status='pending', revision_round=revision_round+1, prior_options_json=options_json, "
                "actor_name=?, actor_office=?, actor_faction=?, presentation_order=? "
                "WHERE turn=? AND idx=? AND kind='rescript_draft'",
                (
                    item["title"], item["context"],
                    json.dumps(item["options"], ensure_ascii=False),
                    item["actor_name"], item["actor_office"], item["actor_faction"],
                    order, item["turn"], item["idx"],
                ),
            )
        row = self._conn.execute(
            "SELECT COALESCE(MAX(idx) + 1, 0) FROM pending_decisions WHERE turn = ?",
            (int(turn),),
        ).fetchone()
        idx = int(row[0] or 0)
        for d in drafts:
            order += 1
            actor_name = str(d.get("actor_name") or "")
            actor_office = str(d.get("actor_office") or "")
            actor_faction = str(d.get("actor_faction") or "")
            event_id = str(d.get("event_id") or "").strip()
            if not event_id:
                event_id = f"urgent:{int(turn)}:{idx}"
            self.insert_pending_decision(
                int(turn),
                idx,
                event_id,
                str(d.get("title") or ""),
                str(d.get("context") or ""),
                "",
                "",
                json.dumps(d.get("options") or [], ensure_ascii=False),
                "",
                "pending",
                "rescript_draft",
                actor_name,
                actor_office,
                actor_faction,
                order,
            )
            idx += 1

    def confirm_directive(self, directive_id: int) -> None:
        """大臣拟旨经皇帝核定：pending → draft（进入颁诏候选池）。

        #1769：只翻状态。成案/补交/耗尽唯一批缝 =
        ensure_dossiers_for_draft_directives + _resubmit_draft_admission_failures；
        禁止在 confirm 内 ensure、标 rejected 或另建重试。产物错 pending 入 draft
        后走 B 路；真代码故障仍由批缝 SettlementAbort（0005/0008）。
        """
        with atomic(SimpleNamespace(conn=self._conn)):
            self._conn.execute(
                "UPDATE turn_directives SET status='draft', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='pending'",
                (int(directive_id),),
            )
            row = self.row(int(directive_id), fields="id", table="turn_directives")
            if row is None:
                raise KeyError(f"旨稿不存在：{directive_id}")
