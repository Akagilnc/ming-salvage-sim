"""Save-slot persistence: the reign header and the balance metrics.

#1889: 存读档的持久读写从 ``db.py`` 大块按职责拆出。The ``game_state`` row is the
reign header (which year/month/turn, and whether the game is over); the
``metrics`` table is the single source of truth for the 国库/内库 balances —
``economy_accounts`` is a read-time view derived from it, never a second copy.
"""

from __future__ import annotations

import json

from typing import Any, Dict, Iterable, List, Optional

from ming_sim.applier import load_stored_json, load_stored_list

# Population unit constant (shared with GameDB read path; no durable marker).
from ming_sim.entities.column_write import RowStore

POPULATION_UNIT_PERSONS = "人"

_METRIC_UPSERT_SQL = (
    "INSERT INTO metrics (key, value) VALUES (?, ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS game_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    turn_phase TEXT NOT NULL DEFAULT 'summoning',
    ended INTEGER NOT NULL DEFAULT 0,
    ending_status TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS metrics (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


class ReignStateStore(RowStore):
    """Single write port for the reign header and the balance metrics."""

    TABLE = "chat_turns"
    PK = "id"
    TABLES = {"rejection_resolutions": "rejection_id", "rejection_reports": "id"}

    def save_game_state(self, state) -> None:
        """Write reign header and balances from a GameState-like object."""
        self._conn.execute(
            "INSERT INTO game_state (id, year, period, turn, turn_phase, ended, ending_status) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET year = excluded.year, period = excluded.period, "
            "turn = excluded.turn, turn_phase = excluded.turn_phase, "
            "ended = excluded.ended, ending_status = excluded.ending_status",
            (
                int(state.year), int(state.period), int(state.turn), str(state.turn_phase),
                1 if state.ended else 0, str(state.ending_status),
            ),
        )
        self._conn.executemany(
            _METRIC_UPSERT_SQL,
            [(str(key), int(value)) for key, value in state.metrics.items()],
        )
        # The writes above open an implicit transaction of
        # their own. The existing transaction suspension neutralises this commit
        # when the caller owns the larger transaction.
        self._conn.commit()

    def read(self) -> Optional[Dict[str, object]]:
        """The reign header, or None when this save has never been initialized."""
        row = self.row(
            1,
            fields="year, period, turn, turn_phase, ended, ending_status",
            table="game_state",
        )
        if row is None:
            return None
        return {
            "year": int(row["year"]),
            "period": int(row["period"]),
            "turn": int(row["turn"]),
            "turn_phase": str(row["turn_phase"] or "summoning"),
            "ended": bool(row["ended"]),
            "ending_status": str(row["ending_status"] or ""),
        }

    def read_metrics(self) -> Dict[str, int]:
        """Every stored balance metric, keyed by name."""
        return {
            str(row["key"]): int(row["value"])
            for row in self._conn.execute("SELECT key, value FROM metrics").fetchall()
        }

    def upsert_metric(self, key: str, value: int) -> None:
        """Write one balance. Does not commit; the caller owns the transaction."""
        self._conn.execute(
            _METRIC_UPSERT_SQL,
            (str(key), int(value)),
        )

    def save_ending_summary(
        self,
        state: Any,
        ending_status: str,
        summary: str,
        timeline: List[Dict[str, object]],
        *,
        commit: bool = True,
    ) -> None:
        """Persist one ending summary row (serialize timeline; upsert by turn)."""
        from ming_sim.applier import connection_owns_transaction

        owns = connection_owns_transaction(self._conn)
        self._conn.execute(
            """
            INSERT INTO ending_summary (turn, year, period, ending_status, summary, timeline)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn) DO UPDATE SET
                year = excluded.year, period = excluded.period,
                ending_status = excluded.ending_status,
                summary = excluded.summary, timeline = excluded.timeline
            """,
            (
                int(state.turn), int(state.year), int(state.period),
                str(ending_status or ""),
                str(summary or ""),
                json.dumps(timeline or [], ensure_ascii=False),
            ),
        )
        if commit and owns:
            self._conn.commit()

    def get_ending_summary(self) -> Optional[Dict[str, object]]:
        """取最近一条结局总结（单库一局，按 turn 取最大）。无则 None。"""
        row = self._conn.execute(
            "SELECT turn, year, period, ending_status, summary, timeline "
            "FROM ending_summary ORDER BY turn DESC LIMIT 1",
        ).fetchone()
        if row is None:
            return None
        timeline = load_stored_json(
            row["timeline"], label=f"结局 timeline turn={row['turn']}", blank=[],
        )
        if not isinstance(timeline, list):
            raise ValueError(f"结局 timeline 必须为名单（turn={row['turn']}）")
        return {
            "turn": int(row["turn"]),
            "year": int(row["year"]),
            "period": int(row["period"]),
            "ending_status": row["ending_status"],
            "summary": row["summary"] or "",
            "timeline": timeline,
        }

    def current_settle_turn(self, fallback: int = 0) -> int:
        """Current absolute turn from game_state; missing row uses fallback."""
        row = self.row(1, fields="turn", table="game_state")
        if row is None or row["turn"] is None:
            return int(fallback)
        return int(row["turn"])

    def has_meta_flag(self, key: str) -> bool:
        row = self.row(key, fields="value", table="metrics", pk="key")
        return row is not None and int(row["value"]) == 1

    def list_economy_moves_for_origin(self, origin: str) -> List[Dict[str, object]]:
        """Ledger rows for one origin; beyond_intent via sole coerce_beyond_intent_flag."""
        from ming_sim.applier import coerce_beyond_intent_flag

        rows: List[Dict[str, object]] = []
        for row in self._conn.execute(
            "SELECT * FROM economy_ledger WHERE origin_ref=? ORDER BY id", (origin,),
        ).fetchall():
            item = dict(row)
            item["beyond_intent"] = bool(
                coerce_beyond_intent_flag(item.get("beyond_intent"))
            )
            rows.append(item)
        return rows

    # --- chat/audience/kv persistence moved from GameDB (#1889 J1) ---
    def list_hall_chat_turns(self, night_id: int) -> List[Dict[str, Any]]:
        """本夜殿上轮（#1849 reopen：只按「殿上」取，不再拼升级前按朝臣存储）。"""
        rows = self._conn.execute(
            "SELECT id, minister_name, status, user_message_id, minister_message_id FROM chat_turns "
            "WHERE night_id=? AND minister_name=? ORDER BY id",
            (int(night_id), "殿上"),
        ).fetchall()
        return [dict(row) for row in rows]

    def allocate_night_seq(self, night_id: int) -> int:
        """夜内单调事件序：账本 seq 与 chat_turns.night_seq 共用（AC4 可合流对齐）。"""
        nid = int(night_id)
        if nid <= 0:
            return 0
        row = self.row(nid, fields="next_event_seq", table="audience_nights")
        if row is None:
            raise ValueError(f"audience night not found: {nid}")
        nxt = int(row["next_event_seq"] or 0) + 1
        self._conn.execute(
            "UPDATE audience_nights SET next_event_seq = ? WHERE id = ?",
            (nxt, nid),
        )
        return nxt

    def mark_post_reply_failure(self, chat_turn_id: int, phase: str, pack_path: str) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = ?, post_reply_error_pack_path = ? "
            "WHERE id = ? AND status = 'active' AND minister_message_id IS NOT NULL",
            (phase, pack_path, int(chat_turn_id)),
        )
        self._conn.commit()

    def clear_post_reply_failure(self, chat_turn_id: int) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = '', post_reply_error_pack_path = '' "
            "WHERE id = ? AND status = 'active'",
            (int(chat_turn_id),),
        )
        self._conn.commit()

    def claim_post_reply_recovery(self, chat_turn_id: int, phase: str) -> bool:
        """持运行时写闸调用；同一已落回话只允许一个尾随恢复者。"""
        cursor = self._conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = ? WHERE id = ? "
            "AND status = 'active' AND post_reply_recovery = ?",
            (f"recovering:{phase}", int(chat_turn_id), phase),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def release_post_reply_recovery(self, chat_turn_id: int, phase: str) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = ? WHERE id = ? "
            "AND post_reply_recovery = ?",
            (phase, int(chat_turn_id), f"recovering:{phase}"),
        )
        self._conn.commit()

    def reconcile_post_reply_recovery(self) -> None:
        """仅启动时释放崩溃遗留 claim，保留原错误包供重试。"""
        self._conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = substr(post_reply_recovery, 12) "
            "WHERE post_reply_recovery LIKE 'recovering:%'",
        )
        self._conn.commit()

    def reopen_interrupted_chat_turn_for_retry(self, chat_turn_id: int) -> bool:
        """重试起手：'interrupted' → 'generating'（重入生成态、与在飞守卫一致，回话落库后升 active）。
        仅当前确为 interrupted 才翻；返回是否翻动（防重复重试竞态）。"""
        cur = self._conn.execute(
            "UPDATE chat_turns SET status = 'generating' "
            "WHERE id = ? AND status = 'interrupted'",
            (int(chat_turn_id),),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_chat_turn_messages(
        self,
        chat_turn_id: int,
        user_message_id: Optional[int] = None,
        minister_message_id: Optional[int] = None,
    ) -> None:
        assignments: List[str] = []
        params: List[Any] = []
        if user_message_id is not None:
            assignments.append("user_message_id = ?")
            params.append(int(user_message_id))
        if minister_message_id is not None:
            assignments.append("minister_message_id = ?")
            params.append(int(minister_message_id))
            assignments.append("error_pack_path = ''")
            # 回话入档 = 轮完成：generating → active（#498 完成态）
            assignments.append("status = CASE WHEN status = 'generating' THEN 'active' ELSE status END")
        if not assignments:
            return
        params.append(int(chat_turn_id))
        self._conn.execute(
            f"UPDATE chat_turns SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def get_story_extract_status(self, chat_turn_id: int) -> str:
        row = self.row(int(chat_turn_id), fields="extract_status")
        return str(row["extract_status"] or "") if row is not None else ""

    def set_chat_turn_error_pack(self, chat_turn_id: int, path: str) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET error_pack_path = ? WHERE id = ? AND status NOT IN ('failed', 'undone')",
            (path, int(chat_turn_id)),
        )
        self._conn.commit()

    def mark_story_extraction_pending(self, chat_turn_id: int) -> None:
        """转译失败 → 待补（'' / 'pending' → 'pending'）；不覆盖已 'done'。"""
        self._conn.execute(
            "UPDATE chat_turns SET extract_status = 'pending' "
            "WHERE id = ? AND extract_status IN ('', 'pending')",
            (int(chat_turn_id),),
        )
        self._conn.commit()

    def is_global_last_active_chat_turn(self, chat_turn_id: int) -> bool:
        row = self._conn.execute(
            "SELECT id FROM chat_turns WHERE status IN ('active', 'interrupted') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return bool(row and int(row["id"]) == int(chat_turn_id))

    def kv_get(self, key: str) -> str | None:
        row = self.row(key, fields="value", table="kv_store", pk="key")
        return row[0] if row else None

    def kv_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv_store(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, value),
        )
        self._conn.commit()

    def open_or_closing_night(self) -> Any:
        return self._conn.execute(
            "SELECT * FROM audience_nights "
            "WHERE status IN ('open', 'closing') ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def latest_alive_protagonist_for_night(self, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT protagonist_name FROM chat_turns WHERE night_id=? "
            "AND status NOT IN ('undone','failed') AND protagonist_name != '' "
            "ORDER BY id DESC LIMIT 1",
            (int(night_id),),
        ).fetchone()

    def set_night_protagonist(self, night_id: int, name: str | None) -> None:
        self._conn.execute(
            "UPDATE audience_nights SET protagonist_name=? WHERE id=?",
            (name, int(night_id)),
        )

    MEMORIAL_READS_KV_KEY = "memorial_reads"

    def memorial_read_keys(self) -> set[str]:
        raw = self.kv_get(self.MEMORIAL_READS_KV_KEY)
        if raw is None:
            return set()
        data = load_stored_list(raw, label="memorial_reads")
        return {str(item) for item in data if str(item or "").strip()}

    def mark_memorials_read(self, keys) -> None:
        """标记奏报已读；键随存档（kv_store）持久化。"""
        incoming = {str(k).strip() for k in keys if str(k or "").strip()}
        if not incoming:
            return
        merged = sorted(self.memorial_read_keys() | incoming)
        self.kv_set(self.MEMORIAL_READS_KV_KEY, json.dumps(merged, ensure_ascii=False))

    def list_in_flight_chat_turns(
        self,
        *,
        night_id: Optional[int] = None,
        minister_name: Optional[str] = None,
        turn: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses = [
            "("
            "status = 'generating' OR "
            "(status = 'active' AND (minister_message_id IS NULL OR minister_message_id = 0))"
            ")"
        ]
        params: List[Any] = []
        if night_id is not None and int(night_id) > 0:
            clauses.append("night_id = ?")
            params.append(int(night_id))
        if minister_name is not None:
            clauses.append("minister_name = ?")
            params.append(str(minister_name))
        if turn is not None:
            clauses.append("turn = ?")
            params.append(int(turn))
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"SELECT * FROM chat_turns WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_active_chat_turn(
        self, minister_name: str, turn: int,
    ) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            """
            SELECT * FROM chat_turns
            WHERE minister_name = ? AND turn = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (minister_name, int(turn)),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_interrupted_reply_retries(
        self, minister_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """中断回话轮 DTO：轮行 + 问话原文；缺消息行跳过。"""
        from ming_sim.entities.record_store import ChatMessageStore

        clauses = ["status = 'interrupted'", "user_message_id IS NOT NULL"]
        params: List[Any] = []
        if minister_name is not None:
            clauses.append("minister_name = ?")
            params.append(str(minister_name))
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"SELECT id, minister_name, turn, error_pack_path, user_message_id "
            f"FROM chat_turns WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()
        messages = ChatMessageStore(self._conn)
        out: List[Dict[str, Any]] = []
        for row in rows:
            question = messages.content_of(int(row["user_message_id"]))
            if question is None:
                continue
            out.append({
                "chat_turn_id": int(row["id"]),
                "minister_name": str(row["minister_name"]),
                "turn": int(row["turn"]),
                "question": question,
                "error_pack_path": str(row["error_pack_path"] or ""),
            })
        return out

    def get_post_reply_retries(self, minister_name: str) -> List[Dict[str, Any]]:
        """已落回话尾随失败 DTO：轮行 + 问/答原文；缺消息行跳过。"""
        from ming_sim.entities.record_store import ChatMessageStore

        rows = self._conn.execute(
            """SELECT id, minister_name, turn, post_reply_recovery,
                      post_reply_error_pack_path, user_message_id, minister_message_id
               FROM chat_turns
               WHERE minister_name = ? AND status = 'active'
                 AND post_reply_recovery != ''
                 AND post_reply_recovery NOT LIKE 'recovering:%' ORDER BY id ASC""",
            (minister_name,),
        ).fetchall()
        messages = ChatMessageStore(self._conn)
        out: List[Dict[str, Any]] = []
        for row in rows:
            question = messages.content_of(int(row["user_message_id"]))
            answer = messages.content_of(int(row["minister_message_id"]))
            if question is None or answer is None:
                continue
            out.append({
                "chat_turn_id": int(row["id"]),
                "minister_name": str(row["minister_name"]),
                "turn": int(row["turn"]),
                "question": question,
                "answer": answer,
                "minister_message_id": int(row["minister_message_id"]),
                "recovery_phase": str(row["post_reply_recovery"]),
                "error_pack_path": str(row["post_reply_error_pack_path"] or ""),
            })
        return out

    def list_unextracted_replies(
        self, *, night_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """完整回话未抽取轮 DTO：轮行 + 回话原文；缺消息行跳过。"""
        from ming_sim.entities.record_store import ChatMessageStore

        clauses = [
            "night_id > 0",
            "status = 'active'",
            "minister_message_id IS NOT NULL",
            "minister_message_id > 0",
            "extract_status IN ('', 'pending')",
        ]
        params: List[Any] = []
        if night_id is not None and int(night_id) > 0:
            clauses.append("night_id = ?")
            params.append(int(night_id))
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT id AS chat_turn_id, minister_name, night_id, night_seq,
                   extract_status, error_pack_path, minister_message_id
            FROM chat_turns
            WHERE {where}
            ORDER BY night_id ASC, night_seq ASC, id ASC
            """,
            params,
        ).fetchall()
        messages = ChatMessageStore(self._conn)
        out: List[Dict[str, Any]] = []
        for row in rows:
            reply = messages.content_of(int(row["minister_message_id"]))
            if reply is None:
                continue
            item = dict(row)
            item.pop("minister_message_id", None)
            item["reply"] = reply
            out.append(item)
        return out

    def list_alive_night_chat_turns(self, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM chat_turns WHERE night_id = ? "
            "AND status NOT IN ('undone', 'failed', 'consumed') "
            "ORDER BY night_seq ASC, id ASC",
            (int(night_id),),
        ).fetchall()

    def set_chat_turn_protagonist(self, chat_turn_id: int, name: str) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET protagonist_name=? WHERE id=?",
            (name, int(chat_turn_id)),
        )

    def mark_extract_status_done(self, chat_turn_id: int) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET extract_status='done' "
            "WHERE id=? AND status NOT IN ('failed','undone')",
            (int(chat_turn_id),),
        )

    def insert_story_ledger_entry_row(
        self,
        *,
        night_id: int,
        seq: int,
        person_names: str,
        audibility: str,
        body: str,
        tags: str,
        source_chat_turn_id: int,
        presence_effect: str,
        order_key: float | None,
        origin_chat_turn_id: int,
        origin_ref: str,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO story_ledger_entries
                (night_id, seq, person_names, audibility, body, tags,
                 source_chat_turn_id, presence_effect, order_key, origin_chat_turn_id,
                 origin_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(night_id), int(seq), person_names, audibility, body, tags,
                int(source_chat_turn_id), presence_effect, order_key,
                int(origin_chat_turn_id), origin_ref,
            ),
        )
        return int(cur.lastrowid)

    # ----- Agno session history (framework tables; single owner) -----

    def _table_exists(self, table: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def agno_runs_length(self, session_id: str) -> int:
        """Count live Agno run rows for a session (``agno_runs`` table only)."""
        if not session_id or not self._table_exists("agno_runs"):
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM agno_runs WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row["n"] or 0)

    def truncate_agno_session_runs(self, session_id: str, keep_count: int) -> None:
        """截回 session 的 Agno 历史到 keep_count（transport 重试 per-attempt）。

        与 truncate_chat_turn_agno_runs 同接缝 ``_truncate_agno_runs_in_tx``；
        不改 chat_turn 状态、不碰游戏账/回话。
        """
        if not session_id:
            return
        with self._conn:
            self._truncate_agno_runs_in_tx(str(session_id), max(0, int(keep_count)))

    def truncate_chat_turn_agno_runs(self, chat_turn_id: int) -> None:
        """截回本轮起点的 Agno 历史（transport 重试 per-attempt）。

        复用 fail/undo/reconcile 同一 `_truncate_agno_runs_in_tx` 接缝；
        不改 chat_turn 状态、不碰游戏账/回话。
        """
        if not chat_turn_id:
            return
        row = self.row(chat_turn_id)
        if row is None:
            return
        self.truncate_agno_session_runs(
            str(row["agno_session_id"] or ""),
            int(row["agno_runs_before"] or 0),
        )

    def _truncate_agno_runs_in_tx(self, session_id: str, keep_count: int) -> None:
        """Truncate ``agno_runs`` rows for one session back to keep_count.

        Ownership is the live runs table only. Does not read or rewrite any
        legacy ``agno_sessions.runs`` blob.
        """
        if not session_id or not self._table_exists("agno_runs"):
            return
        keep = max(0, int(keep_count))
        rows = self._conn.execute(
            """
            SELECT run_id FROM agno_runs
            WHERE session_id = ?
            ORDER BY run_index ASC, created_at ASC, run_id ASC
            """,
            (session_id,),
        ).fetchall()
        if len(rows) <= keep:
            return
        drop_ids = [
            str(r["run_id"])
            for r in rows[keep:]
            if r["run_id"] is not None
        ]
        if drop_ids:
            self._conn.executemany(
                "DELETE FROM agno_runs WHERE session_id = ? AND run_id = ?",
                [(session_id, rid) for rid in drop_ids],
            )

    def list_ledger_summon_rows(self) -> Any:
        return self._conn.execute(
            "SELECT id, night_id, person_names, tags FROM story_ledger_entries ORDER BY id"
        ).fetchall()

    def insert_legacy(
        self,
        name: object,
        source_issue_id: object,
        modifiers: object,
        narrative_hint: object,
        start_month: object,
        duration_months: object,
        clear_gate: object,
        legacy_key: object,
    ) -> Any:
        return self._conn.execute(
            "INSERT INTO legacies\n               (name, source_issue_id, modifiers, narrative_hint,\n                start_month, duration_months, status, clear_gate, legacy_key)\n               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (
                name,
                source_issue_id,
                modifiers,
                narrative_hint,
                start_month,
                duration_months,
                clear_gate,
                legacy_key,
            ),
        )

    def set_legacy_statuses(self, status: str, legacy_ids: Iterable[int]) -> Any:
        return self._conn.executemany(
            "UPDATE legacies SET status=? WHERE id=?",
            [(status, int(legacy_id)) for legacy_id in legacy_ids],
        )

    def closed_nights_archive_rows(self) -> Any:
        return self._conn.execute(
            """
                SELECT id,turn,year,period,time_of_day,location,
                       ROW_NUMBER() OVER (
                           PARTITION BY turn, location, time_of_day ORDER BY id
                       ) AS scene_number,
                       COUNT(*) OVER (
                           PARTITION BY turn, location, time_of_day
                       ) AS scene_count
                FROM audience_nights WHERE status='closed' ORDER BY turn,id
                """
        ).fetchall()

    def active_chat_turn_actor_and_user_message(
        self,
        *,
        chat_turn_id: int,
        turn: int,
    ) -> Any:
        return self._conn.execute(
            "SELECT minister_name, user_message_id FROM chat_turns "
            "WHERE id=? AND turn=? AND status='active'",
            (int(chat_turn_id), int(turn)),
        ).fetchone()

    def sync_opening_legacy(
        self, *, legacy_key: str, name: str, modifiers: object,
        narrative_hint: str, clear_gate: object, passed: bool, start_month: int,
    ) -> bool:
        """Refresh the active opening fact, clear it, or seed the missing active row."""
        modifiers_json = json.dumps(modifiers, ensure_ascii=False)
        gate_json = json.dumps(clear_gate, ensure_ascii=False)
        cur = self._conn.execute(
            "UPDATE legacies SET name=?, modifiers=?, narrative_hint=?, clear_gate=?, "
            "status=CASE WHEN ? THEN 'cleared' ELSE status END "
            "WHERE legacy_key=? AND status='active'",
            (name, modifiers_json, narrative_hint, gate_json, passed, legacy_key),
        )
        if cur.rowcount:
            return True
        if passed:
            return False
        self.insert_legacy(
            name,
            None,
            modifiers_json,
            narrative_hint,
            start_month,
            -1,
            gate_json,
            legacy_key,
        )
        return True

    def list_night_ids(self) -> Any:
        return self._conn.execute(
            "SELECT id FROM audience_nights ORDER BY id"
        ).fetchall()

    def set_ledger_tags(self, tags: object, id: object) -> Any:
        return self._conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?", (tags, id)
        )

    def insert_economy_move(
        self,
        turn: object,
        year: object,
        period: object,
        account: object,
        delta: object,
        balance_after: object,
        category: object,
        reason: object,
        event_id: object,
        edict_id: object,
        actor: object,
        purpose: object,
        target_kind: object,
        target_id: object,
        dossier_id: object,
        origin_ref: object,
        beyond_intent: object,
    ) -> Any:
        return self._conn.execute(
            "INSERT INTO economy_ledger "
            "(turn, year, period, account, delta, balance_after, category, reason, "
            "event_id, edict_id, actor, purpose, target_kind, target_id, dossier_id, "
            "origin_ref, beyond_intent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn,
                year,
                period,
                account,
                delta,
                balance_after,
                category,
                reason,
                event_id,
                edict_id,
                actor,
                purpose,
                target_kind,
                target_id,
                dossier_id,
                origin_ref,
                beyond_intent,
            ),
        )

    def delete_chat_turn_ledger(
        self, source_chat_turn_id: object, origin_chat_turn_id: object
    ) -> Any:
        return self._conn.execute(
            "DELETE FROM story_ledger_entries "
            "WHERE source_chat_turn_id = ? OR origin_chat_turn_id = ?",
            (source_chat_turn_id, origin_chat_turn_id),
        )

    def set_chat_turn_status(self, status: object, id: object) -> Any:
        return self._conn.execute(
            "UPDATE chat_turns SET status=? WHERE id=?", (status, id)
        )

    def chat_turn_rollback_rows(self, chat_turn_id: object) -> Any:
        return self._conn.execute(
            """
                SELECT * FROM chat_turn_rollback_items
                WHERE chat_turn_id = ?
                ORDER BY id DESC
                """,
            (chat_turn_id,),
        ).fetchall()

    def ledger_archive_rows_for_nights(self, night_ids: list[int]) -> Any:
        if not night_ids:
            return []
        placeholders = ",".join("?" for _ in night_ids)
        return self._conn.execute(
            f"SELECT night_id,person_names,tags,source_chat_turn_id "
            f"FROM story_ledger_entries WHERE night_id IN ({placeholders}) "
            "ORDER BY night_id,COALESCE(order_key,seq),id",
            night_ids,
        ).fetchall()

    def chat_turn_archive_rows_for_nights(self, night_ids: list[int]) -> Any:
        if not night_ids:
            return []
        placeholders = ",".join("?" for _ in night_ids)
        return self._conn.execute(
            f"SELECT night_id,minister_name FROM chat_turns "
            f"WHERE night_id IN ({placeholders}) "
            f"AND status NOT IN ('undone', 'failed', 'consumed') "
            "ORDER BY night_id,night_seq,id",
            night_ids,
        ).fetchall()

    def ledger_totals(self, turn: int, excluded_ids: Iterable[int]) -> Any:
        ids = tuple(excluded_ids)
        clause = " AND id NOT IN (" + ",".join("?" for _ in ids) + ")" if ids else ""
        return self._conn.execute(
            "SELECT account, SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS income, "
            "SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS expense "
            f"FROM economy_ledger WHERE turn=?{clause} GROUP BY account ORDER BY account DESC",
            (turn, *ids),
        ).fetchall()

    def recent_ledger(self, excluded_ids: Iterable[int], limit: int | None) -> Any:
        ids = tuple(excluded_ids)
        sql = (
            "SELECT year,period,account,delta,category,reason,actor FROM economy_ledger"
        )
        params = list(ids)
        if ids:
            sql += " WHERE id NOT IN (" + ",".join("?" for _ in ids) + ")"
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self._conn.execute(sql, params).fetchall()

    def chat_turns_for_messages(self, message_ids: Iterable[int]) -> Any:
        ids = tuple(message_ids)
        placeholders = ",".join("?" for _ in ids)
        return self._conn.execute(
            f"SELECT id,user_message_id,minister_message_id FROM chat_turns "
            f"WHERE user_message_id IN ({placeholders}) OR minister_message_id IN ({placeholders}) "
            "ORDER BY id DESC",
            [*ids, *ids],
        ).fetchall()
