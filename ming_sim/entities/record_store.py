"""Write ports for chat messages, turn reports, resolve context, month-open snapshot.

#1889: these tables are persistence only. Domain projection stays with the caller;
the SQL that inserts, updates, or deletes the row lives here.
"""

from __future__ import annotations

from typing import Any, Iterable


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
