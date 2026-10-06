"""Persistence for chat messages, turn reports, resolve context, month-open snapshot.

#1889: these tables are persistence only. Domain projection stays with the caller.
The SQL that reads or writes the row lives here.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


class ChatMessageStore:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        minister_name: str,
        turn: int,
        role: str,
        content: str,
        knowledge_status: str = "held",
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO chat_messages "
            "(minister_name, turn, role, content, knowledge_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (minister_name, int(turn), role, content, knowledge_status),
        )
        return int(cursor.lastrowid)

    def set_highlights_json(self, message_id: int, payload: str) -> None:
        self._conn.execute(
            "UPDATE chat_messages SET highlights_json = ? WHERE id = ?",
            (payload, int(message_id)),
        )

    def set_knowledge_status(self, message_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE chat_messages SET knowledge_status=? WHERE id=?",
            (status, int(message_id)),
        )

    def delete_ids(self, message_ids: Iterable[int]) -> None:
        ids = [int(message_id) for message_id in message_ids]
        if not ids:
            return
        self._conn.executemany(
            "DELETE FROM chat_messages WHERE id = ?",
            [(message_id,) for message_id in ids],
        )

    @staticmethod
    def parse_highlights(raw: object) -> List[str]:
        from ming_sim.applier import load_stored_json

        data = load_stored_json(raw, label="奏对高亮 highlights_json", blank=[])
        if not isinstance(data, list):
            raise ValueError("奏对高亮 highlights_json 必须为名单")
        out: List[str] = []
        for item in data:
            if not isinstance(item, str):
                raise ValueError("奏对高亮成员须为文字")
            if item.strip():
                out.append(item.strip())
        return out

    def highlights(self, message_id: int) -> List[str]:
        row = self._conn.execute(
            "SELECT highlights_json FROM chat_messages WHERE id = ?",
            (int(message_id),),
        ).fetchone()
        if row is None:
            return []
        return self.parse_highlights(row["highlights_json"])

    def content_of(self, message_id: int) -> Optional[str]:
        row = self._conn.execute(
            "SELECT content FROM chat_messages WHERE id=?",
            (int(message_id),),
        ).fetchone()
        if row is None:
            return None
        return str(row["content"] or "")

    def scroll_row(self, message_id: int) -> Optional[Dict[str, object]]:
        row = self._conn.execute(
            "SELECT content, created_at, highlights_json FROM chat_messages WHERE id=?",
            (int(message_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "content": row["content"],
            "created_at": row["created_at"],
            "highlights_json": row["highlights_json"],
        }

    def history_by_minister(self) -> Dict[str, List[Dict[str, str]]]:
        rows = self._conn.execute(
            "SELECT minister_name, role, content FROM chat_messages ORDER BY id"
        ).fetchall()
        history: Dict[str, List[Dict[str, str]]] = {}
        for row in rows:
            history.setdefault(row["minister_name"], []).append(
                {"role": row["role"], "content": row["content"]}
            )
        return history

    def rows_by_ids(self, message_ids: Iterable[int]) -> List[Dict[str, object]]:
        ids = [int(message_id) for message_id in message_ids]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            "SELECT id, role, content, highlights_json FROM chat_messages "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_held_user_id(
        self, minister_name: str, turn: Optional[int] = None,
    ) -> Optional[int]:
        if turn is not None:
            row = self._conn.execute(
                "SELECT id FROM chat_messages "
                "WHERE minister_name=? AND role='user' AND knowledge_status='held' "
                "AND turn=? ORDER BY id DESC LIMIT 1",
                (minister_name, int(turn)),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM chat_messages "
                "WHERE minister_name=? AND role='user' AND knowledge_status='held' "
                "ORDER BY id DESC LIMIT 1",
                (minister_name,),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    def existing_ids(self, message_ids: Iterable[int]) -> List[int]:
        ids = [int(message_id) for message_id in message_ids]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id FROM chat_messages WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def held_rows(
        self, minister_names: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, object]]:
        names = [str(name) for name in (minister_names or ())]
        if names:
            placeholders = ",".join("?" for _ in names)
            rows = self._conn.execute(
                "SELECT id, minister_name, turn, content FROM chat_messages "
                f"WHERE knowledge_status='held' AND minister_name IN ({placeholders}) "
                "ORDER BY id",
                tuple(sorted(names)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, minister_name, turn, content FROM chat_messages "
                "WHERE knowledge_status='held' ORDER BY id",
            ).fetchall()
        return [dict(row) for row in rows]


class TurnReportStore:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        turn: int,
        year: int,
        period: int,
        report: str,
        attendant_message: str,
        title: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO turn_reports (turn, year, period, report, attendant_message, title)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn) DO UPDATE SET
                year = excluded.year,
                period = excluded.period,
                report = excluded.report,
                attendant_message = excluded.attendant_message,
                title = CASE
                    WHEN excluded.title = '' THEN turn_reports.title
                    ELSE excluded.title
                END
            """,
            (int(turn), int(year), int(period), report, attendant_message, title),
        )

    def archive(self, turn: int) -> Optional[Dict[str, object]]:
        row = self._conn.execute(
            "SELECT year, period, report, attendant_message, title "
            "FROM turn_reports WHERE turn = ?",
            (int(turn),),
        ).fetchone()
        if row is None:
            return None
        return {
            "year": int(row["year"] or 0),
            "period": int(row["period"] or 0),
            "report": str(row["report"] or ""),
            "attendant_message": str(row["attendant_message"] or ""),
            "title": str(row["title"] or ""),
        }

    def report_text(self, turn: int) -> str:
        row = self.archive(turn)
        return str(row["report"] if row else "") or ""

    def attendant_message(self, turn: int) -> str:
        row = self.archive(turn)
        if row is None:
            return ""
        return str(row["attendant_message"] or "")

    def list_archives(self) -> List[Dict[str, object]]:
        rows = self._conn.execute(
            "SELECT turn, year, period, report, title FROM turn_reports "
            "ORDER BY turn, rowid"
        ).fetchall()
        return [
            {
                "turn": int(row["turn"]),
                "year": int(row["year"]),
                "period": int(row["period"]),
                "report": row["report"] or "",
                "title": str(row["title"] or ""),
            }
            for row in rows
        ]

    def presence_rows(self) -> List[Dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT turn, year, period,
                   CASE WHEN length(trim(COALESCE(report, ''), char(9)||char(10)||char(13)||' ')) > 0
                        THEN 1 ELSE 0 END AS has_report,
                   CASE WHEN length(trim(COALESCE(attendant_message, ''), char(9)||char(10)||char(13)||' ')) > 0
                        THEN 1 ELSE 0 END AS has_attendant
            FROM turn_reports
            """
        ).fetchall()
        return [dict(row) for row in rows]


class ResolveContextStore:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        turn: int,
        decree_text: str,
        simulator_payload_json: str,
        source: str,
        attendant_message: str,
    ) -> None:
        self._conn.execute(
            """INSERT INTO pending_resolve_context
               (turn, decree_text, simulator_payload_json, source, attendant_message)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(turn) DO UPDATE SET
                   decree_text = excluded.decree_text,
                   simulator_payload_json = excluded.simulator_payload_json,
                   source = excluded.source,
                   attendant_message = excluded.attendant_message""",
            (int(turn), decree_text, simulator_payload_json, source, attendant_message),
        )

    def delete(self, turn: int) -> None:
        self._conn.execute(
            "DELETE FROM pending_resolve_context WHERE turn = ?", (int(turn),),
        )

    def get(self, turn: int) -> Optional[Dict[str, object]]:
        row = self._conn.execute(
            "SELECT decree_text, simulator_payload_json, source, attendant_message "
            "FROM pending_resolve_context WHERE turn = ?",
            (int(turn),),
        ).fetchone()
        if row is None:
            return None

        def _load(text: str, label: str) -> object:
            from ming_sim.applier import StoredDocumentError, load_stored_object

            try:
                return load_stored_object(text, label=label)
            except StoredDocumentError as exc:
                raise StoredDocumentError(
                    f"过月上下文 {label} 损坏，本月无法恢复（turn={turn}）：{exc}"
                ) from exc

        return {
            "decree_text": row["decree_text"],
            "simulator_payload": _load(row["simulator_payload_json"], "simulator_payload"),
            "source": row["source"] or "system_simulation",
            "attendant_message": str(row["attendant_message"] or ""),
        }

    def turns(self) -> List[int]:
        rows = self._conn.execute(
            "SELECT turn FROM pending_resolve_context ORDER BY turn"
        ).fetchall()
        return [int(row["turn"]) for row in rows]


class MonthOpenSnapshotStore:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert_once(
        self,
        *,
        turn: int,
        treasury: int,
        inner_treasury: int,
        public_support: int,
        imperial_prestige: int,
    ) -> bool:
        cursor = self._conn.execute(
            """INSERT INTO month_open_snapshot
               (turn, treasury, inner_treasury, public_support, imperial_prestige)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(turn) DO NOTHING""",
            (int(turn), int(treasury), int(inner_treasury), int(public_support), int(imperial_prestige)),
        )
        return int(cursor.rowcount or 0) == 1

    def delete(self, turn: int) -> None:
        self._conn.execute(
            "DELETE FROM month_open_snapshot WHERE turn = ?", (int(turn),),
        )

    def get(self, turn: int) -> Optional[Dict[str, int]]:
        row = self._conn.execute(
            """SELECT treasury, inner_treasury, public_support, imperial_prestige
               FROM month_open_snapshot WHERE turn = ?""",
            (int(turn),),
        ).fetchone()
        if row is None:
            return None
        return {
            "国库": int(row["treasury"]),
            "内库": int(row["inner_treasury"]),
            "民心": int(row["public_support"]),
            "皇威": int(row["imperial_prestige"]),
        }
