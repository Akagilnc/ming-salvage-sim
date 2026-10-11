"""Save-slot persistence: the reign header and the balance metrics.

#1889: 存读档的持久读写从 ``db.py`` 大块按职责拆出。The ``game_state`` row is the
reign header (which year/month/turn, and whether the game is over); the
``metrics`` table is the single source of truth for the 国库/内库 balances —
``economy_accounts`` is a read-time view derived from it, never a second copy.
"""

from __future__ import annotations

import json

from typing import Any, Dict, List, Mapping, Optional

from ming_sim.applier import load_stored_json, load_stored_list
from ming_sim.entities.column_write import checked_columns

# Population unit constant (shared with GameDB read path; no durable marker).
POPULATION_UNIT_PERSONS = "人"

_METRIC_UPSERT_SQL = (
    "INSERT INTO metrics (key, value) VALUES (?, ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)


_LEDGER_ORDER = (
    "turn", "year", "period", "account", "delta", "balance_after", "category",
    "reason", "event_id", "edict_id", "actor", "purpose", "target_kind",
    "target_id", "dossier_id", "origin_ref", "beyond_intent",
)
_LEDGER_COLUMNS = frozenset(_LEDGER_ORDER)


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


class ReignStateStore:
    """Single write port for the reign header and the balance metrics."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    def exists(self) -> bool:
        return self._conn.execute("SELECT 1 FROM game_state WHERE id = 1").fetchone() is not None


    def save_game_state(self, state) -> None:
        """Write reign header and balances from a GameState-like object."""
        self.save(
            year=state.year,
            period=state.period,
            turn=state.turn,
            turn_phase=state.turn_phase,
            ended=state.ended,
            ending_status=state.ending_status,
            metrics=state.metrics,
        )

    def save(
        self,
        *,
        year: int,
        period: int,
        turn: int,
        turn_phase: str,
        ended: bool,
        ending_status: str,
        metrics: Mapping[str, object],
        commit: bool = True,
    ) -> None:
        """Write the reign header and every balance metric."""
        self._conn.execute(
            "INSERT INTO game_state (id, year, period, turn, turn_phase, ended, ending_status) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET year = excluded.year, period = excluded.period, "
            "turn = excluded.turn, turn_phase = excluded.turn_phase, "
            "ended = excluded.ended, ending_status = excluded.ending_status",
            (
                int(year), int(period), int(turn), str(turn_phase),
                1 if ended else 0, str(ending_status),
            ),
        )
        self._conn.executemany(
            _METRIC_UPSERT_SQL,
            [(str(key), int(value)) for key, value in metrics.items()],
        )
        # Commit whenever asked: the writes above open an implicit transaction of
        # their own, and this is the save-slot write port — callers that own a
        # transaction pass commit=False (or hold the suspension flag, which
        # neutralises conn.commit).
        if commit:
            self._conn.commit()

    def read(self) -> Optional[Dict[str, object]]:
        """The reign header, or None when this save has never been initialized."""
        row = self._conn.execute(
            "SELECT year, period, turn, turn_phase, ended, ending_status "
            "FROM game_state WHERE id = 1"
        ).fetchone()
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

    def insert_ledger(self, row: Mapping[str, object]) -> None:
        """Append one economy_ledger row. Optional columns default in the table."""
        checked_columns(row, _LEDGER_COLUMNS, what="economy_ledger")
        columns = [column for column in _LEDGER_ORDER if column in row]
        if not columns:
            raise ValueError("economy_ledger insert needs fields")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO economy_ledger ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def read_current_settle_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn FROM game_state WHERE id = 1', params).fetchone()

    def read_has_meta_flag(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT value FROM metrics WHERE key=?', params).fetchone()

    def read_list_economy_moves_for_dossier(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT * FROM economy_ledger WHERE origin_ref=? ORDER BY id', params).fetchall()

    def read_ledger_paid_this_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT delta FROM economy_ledger WHERE origin_ref=? AND turn=? AND delta<0', params).fetchall()

    def read_scan_misappropriation(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                SELECT id, origin_ref, reason, purpose, delta FROM economy_ledger\n                WHERE turn=? AND account=? AND delta<0\n                ', params).fetchall()

    def read_had_prior_funding(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT COUNT(*) AS c FROM economy_ledger WHERE origin_ref=? AND delta<0 AND turn<=?', params).fetchone()

    def read_budget_ledger_rows(self, params: Any = ()) -> Any:
        return self._conn.execute(
            'SELECT id, account, delta, balance_after, category, reason '
            'FROM economy_ledger WHERE turn = ? ORDER BY id',
            params,
        ).fetchall()

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
        row = self.read_current_settle_turn()
        if row is None or row["turn"] is None:
            return int(fallback)
        return int(row["turn"])

    def has_meta_flag(self, key: str) -> bool:
        row = self.read_has_meta_flag((key,))
        return row is not None and int(row["value"]) == 1

    def list_economy_moves_for_dossier(self, dossier_id: int) -> List[Dict[str, object]]:
        """Ledger rows for one dossier; beyond_intent via sole coerce_beyond_intent_flag."""
        from ming_sim.applier import coerce_beyond_intent_flag

        rows: List[Dict[str, object]] = []
        for row in self.read_list_economy_moves_for_dossier((f"dossier:{int(dossier_id)}",)):
            item = dict(row)
            item["beyond_intent"] = bool(
                coerce_beyond_intent_flag(item.get("beyond_intent"))
            )
            rows.append(item)
        return rows


    def read_is_pending_source_round_owned(self, params: Any) -> Any:
        return self._conn.execute("SELECT 1 FROM chat_turns t JOIN game_state g ON g.id=1 WHERE t.id=? AND t.night_id=? AND t.status='active' AND t.minister_message_id>0 AND t.extract_status='pending' AND g.turn=?", params)

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
        row = self._conn.execute(
            "SELECT next_event_seq FROM audience_nights WHERE id = ?",
            (nid,),
        ).fetchone()
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

    def read_chat_turn(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM chat_turns WHERE id = ?", (int(chat_turn_id),),
        ).fetchone()

    def _chat_turn_rollback_items(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM chat_turn_rollback_items WHERE chat_turn_id = ? ORDER BY id DESC",
            (int(chat_turn_id),),
        ).fetchall()

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
        row = self._conn.execute(
            "SELECT extract_status FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
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

    def _current_open_night_id(self) -> int:
        """当前开着（open/closing）的召对夜 id；无夜返回 0。"""
        row = self._conn.execute(
            "SELECT id FROM audience_nights "
            "WHERE status IN ('open', 'closing') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row is not None else 0

    def kv_get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv_store(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, value),
        )
        self._conn.commit()

    def insert_chat_turn_row(
        self,
        *,
        minister_name: str,
        turn: int,
        year: int,
        period: int,
        agno_session_id: str,
        agno_runs_before: int,
        night_id: int,
        night_seq: int,
        status: str,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO chat_turns
                (minister_name, turn, year, period, agno_session_id, agno_runs_before,
                 night_id, night_seq, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                minister_name, int(turn), int(year), int(period),
                agno_session_id, max(0, int(agno_runs_before)),
                int(night_id), int(night_seq), status,
            ),
        )
        return int(cur.lastrowid)

    def set_chat_turn_status(self, chat_turn_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET status = ? WHERE id = ?",
            (status, int(chat_turn_id)),
        )

    def open_or_closing_night(self) -> Any:
        return self._conn.execute(
            "SELECT * FROM audience_nights "
            "WHERE status IN ('open', 'closing') ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def night_by_id(self, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM audience_nights WHERE id = ?", (int(night_id),)
        ).fetchone()

    def insert_night(self, column_sql: str, values_sql: str, params: tuple) -> int:
        cur = self._conn.execute(
            f"INSERT INTO audience_nights {column_sql} VALUES {values_sql}",
            params,
        )
        return int(cur.lastrowid)

    def update_night(self, assignments: str, night_id: int, params: tuple = ()) -> None:
        self._conn.execute(
            f"UPDATE audience_nights SET {assignments} WHERE id = ?",
            (*params, int(night_id)),
        )

    def night_status(self, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT status FROM audience_nights WHERE id = ?", (int(night_id),)
        ).fetchone()

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

    def list_night_ids(self) -> Any:
        return self._conn.execute("SELECT id FROM audience_nights ORDER BY id").fetchall()

    def ledger_tags(self, entry_id: int) -> Any:
        return self._conn.execute(
            "SELECT tags FROM story_ledger_entries WHERE id=?", (int(entry_id),)
        ).fetchone()

    def set_ledger_tags(self, entry_id: int, tags: str) -> None:
        self._conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?",
            (tags, int(entry_id)),
        )

    def ledger_origin_chat_turn_id(self, entry_id: int) -> Any:
        return self._conn.execute(
            "SELECT origin_chat_turn_id FROM story_ledger_entries WHERE id=?",
            (int(entry_id),),
        ).fetchone()

    def delete_ledger_entry(self, entry_id: int) -> None:
        self._conn.execute("DELETE FROM story_ledger_entries WHERE id=?", (int(entry_id),))

    def ledger_by_origin_ref(self, origin_ref: str) -> Any:
        return self._conn.execute(
            "SELECT * FROM story_ledger_entries WHERE origin_ref = ? LIMIT 1",
            (origin_ref,),
        ).fetchone()

    def list_ledger_summon_rows(self) -> Any:
        return self._conn.execute(
            "SELECT id, night_id, person_names, tags FROM story_ledger_entries ORDER BY id"
        ).fetchall()

    def delete_rollback_items_for_turn(self, chat_turn_id: int) -> None:
        self._conn.execute(
            "DELETE FROM chat_turn_rollback_items WHERE chat_turn_id = ?",
            (int(chat_turn_id),),
        )

    def chat_turn_exists(self, chat_turn_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM chat_turns WHERE id=?", (int(chat_turn_id),)
        ).fetchone() is not None


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

    def open_night_id(self) -> int:
        row = self._conn.execute(
            "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else 0

    def list_chat_turns_for_projection(self, minister_name: str, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT id, user_message_id, minister_message_id FROM chat_turns "
            "WHERE minister_name=? AND night_id=?",
            (minister_name, int(night_id)),
        ).fetchall()


    MEMORIAL_READS_KV_KEY = "memorial_reads"

    def memorial_read_keys(self) -> set[str]:
        raw = self.kv_get(self.MEMORIAL_READS_KV_KEY)
        if not raw:
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
        return [dict(r) for r in self.list_in_flight_chat_turn_rows(
            night_id=night_id, minister_name=minister_name, turn=turn,
        )]

    def get_last_active_chat_turn(
        self, minister_name: str, turn: int,
    ) -> Optional[Dict[str, Any]]:
        row = self.last_active_chat_turn_row(minister_name, int(turn))
        return dict(row) if row is not None else None

    def get_interrupted_reply_retries(
        self, minister_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """中断回话轮 DTO：轮行 + 问话原文；缺消息行跳过。"""
        from ming_sim.entities.record_store import ChatMessageStore

        messages = ChatMessageStore(self._conn)
        out: List[Dict[str, Any]] = []
        for row in self.list_interrupted_chat_turn_rows(minister_name):
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

        messages = ChatMessageStore(self._conn)
        out: List[Dict[str, Any]] = []
        for row in self.list_post_reply_retry_rows(minister_name):
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

        messages = ChatMessageStore(self._conn)
        out: List[Dict[str, Any]] = []
        for row in self.list_unextracted_chat_turn_rows(night_id):
            reply = messages.content_of(int(row["minister_message_id"]))
            if reply is None:
                continue
            item = dict(row)
            item.pop("minister_message_id", None)
            item["reply"] = reply
            out.append(item)
        return out

    def list_in_flight_chat_turn_rows(
        self,
        *,
        night_id: Optional[int] = None,
        minister_name: Optional[str] = None,
        turn: Optional[int] = None,
    ) -> Any:
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
        return self._conn.execute(
            f"SELECT * FROM chat_turns WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()

    def list_interrupted_chat_turn_rows(self, minister_name: Optional[str] = None) -> Any:
        clauses = ["status = 'interrupted'", "user_message_id IS NOT NULL"]
        params: List[Any] = []
        if minister_name is not None:
            clauses.append("minister_name = ?")
            params.append(str(minister_name))
        where = " AND ".join(clauses)
        return self._conn.execute(
            f"SELECT id, minister_name, turn, error_pack_path, user_message_id "
            f"FROM chat_turns WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()

    def list_post_reply_retry_rows(self, minister_name: str) -> Any:
        return self._conn.execute(
            """SELECT id, minister_name, turn, post_reply_recovery,
                      post_reply_error_pack_path, user_message_id, minister_message_id
               FROM chat_turns
               WHERE minister_name = ? AND status = 'active'
                 AND post_reply_recovery != ''
                 AND post_reply_recovery NOT LIKE 'recovering:%' ORDER BY id ASC""",
            (minister_name,),
        ).fetchall()

    def delete_ledger_for_chat_turn(self, chat_turn_id: int) -> None:
        self._conn.execute(
            "DELETE FROM story_ledger_entries "
            "WHERE source_chat_turn_id = ? OR origin_chat_turn_id = ?",
            (int(chat_turn_id), int(chat_turn_id)),
        )

    def mark_chat_turn_undone(self, chat_turn_id: int) -> None:
        self._conn.execute(
            """
            UPDATE chat_turns
            SET status = 'undone', undone_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(chat_turn_id),),
        )

    def link_minister_reply(self, chat_turn_id: int, message_id: int) -> None:
        self._conn.execute(
            """
            UPDATE chat_turns
            SET minister_message_id = ?,
                error_pack_path = '',
                status = CASE WHEN status = 'generating' THEN 'active' ELSE status END
            WHERE id = ?
            """,
            (int(message_id), int(chat_turn_id)),
        )

    def last_active_chat_turn_row(self, minister_name: str, turn: int) -> Any:
        return self._conn.execute(
            """
            SELECT * FROM chat_turns
            WHERE minister_name = ? AND turn = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (minister_name, int(turn)),
        ).fetchone()

    def list_unextracted_chat_turn_rows(self, night_id: Optional[int] = None) -> Any:
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
        return self._conn.execute(
            f"""
            SELECT id AS chat_turn_id, minister_name, night_id, night_seq,
                   extract_status, error_pack_path, minister_message_id
            FROM chat_turns
            WHERE {where}
            ORDER BY night_id ASC, night_seq ASC, id ASC
            """,
            params,
        ).fetchall()

    def insert_rollback_item_rows(self, rows: List[tuple]) -> None:
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO chat_turn_rollback_items
                (chat_turn_id, kind, target_table, target_id, before_json, after_json, rollback_strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def list_alive_night_chat_turns(self, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM chat_turns WHERE night_id = ? "
            "AND status NOT IN ('undone', 'failed', 'consumed') "
            "ORDER BY night_seq ASC, id ASC",
            (int(night_id),),
        ).fetchall()

    def list_ledger_ordered_for_night(self, night_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM story_ledger_entries WHERE night_id = ? "
            "ORDER BY COALESCE(order_key, seq) ASC, id ASC",
            (int(night_id),),
        ).fetchall()

    def chat_turn_night_seq(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT night_seq FROM chat_turns WHERE id=?", (int(chat_turn_id),),
        ).fetchone()

    def chat_turn_ids_for_message_ids(self, message_ids: list[int]) -> Any:
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        return self._conn.execute(
            f"SELECT id FROM chat_turns WHERE user_message_id IN ({placeholders}) "
            f"OR minister_message_id IN ({placeholders})",
            [*message_ids, *message_ids],
        ).fetchall()

    def set_chat_turn_protagonist(self, chat_turn_id: int, name: str) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET protagonist_name=? WHERE id=?",
            (name, int(chat_turn_id)),
        )

    def rollback_chat_turn_id_for_pending_action(self, pending_action_id: int) -> Any:
        return self._conn.execute(
            """
            SELECT chat_turn_id FROM chat_turn_rollback_items
            WHERE target_table='pending_actions' AND target_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (str(int(pending_action_id)),),
        ).fetchone()

    def chat_turns_for_user_message_ids(self, message_ids: list[int]) -> Any:
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        return self._conn.execute(
            f"SELECT user_message_id, minister_message_id FROM chat_turns "
            f"WHERE user_message_id IN ({placeholders})",
            tuple(sorted(message_ids)),
        ).fetchall()

    def latest_chat_turn_id_for_message_ids(self, message_ids: list[int]) -> int:
        if not message_ids:
            return 0
        placeholders = ",".join("?" for _ in message_ids)
        row = self._conn.execute(
            f"""
            SELECT id FROM chat_turns
            WHERE user_message_id IN ({placeholders})
               OR minister_message_id IN ({placeholders})
            ORDER BY id DESC LIMIT 1
            """,
            [*message_ids, *message_ids],
        ).fetchone()
        return int(row["id"]) if row is not None else 0

    def active_prior_chat_turn_exists(
        self,
        *,
        earlier_id: int,
        current_id: int,
        actor: str,
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM chat_turns earlier JOIN chat_turns current "
            "ON earlier.night_id=current.night_id AND earlier.turn=current.turn "
            "WHERE earlier.id=? AND current.id=? AND earlier.id<current.id "
            "AND earlier.minister_name=? AND current.minister_name=? "
            "AND earlier.minister_message_id IS NOT NULL "
            "AND earlier.status='active' AND current.status='active' "
            "AND earlier.undone_at IS NULL AND current.undone_at IS NULL",
            (int(earlier_id), int(current_id), actor, actor),
        ).fetchone()
        return row is not None

    def active_chat_turn_user_message_id(
        self, *, chat_turn_id: int, minister_name: str, turn: int,
    ) -> Any:
        return self._conn.execute(
            "SELECT user_message_id FROM chat_turns "
            "WHERE id=? AND minister_name=? AND turn=? AND status='active'",
            (int(chat_turn_id), minister_name, int(turn)),
        ).fetchone()

    def active_chat_turn_actor_and_user_message(
        self, *, chat_turn_id: int, turn: int,
    ) -> Any:
        return self._conn.execute(
            "SELECT minister_name, user_message_id FROM chat_turns "
            "WHERE id=? AND turn=? AND status='active'",
            (int(chat_turn_id), int(turn)),
        ).fetchone()

    def chat_turn_night_id(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT night_id FROM chat_turns WHERE id=?", (int(chat_turn_id),),
        ).fetchone()

    def mark_extract_status_done(self, chat_turn_id: int) -> None:
        self._conn.execute(
            "UPDATE chat_turns SET extract_status='done' "
            "WHERE id=? AND status NOT IN ('failed','undone')",
            (int(chat_turn_id),),
        )

    def chat_turn_status_and_minister_message(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT status, minister_message_id FROM chat_turns WHERE id=?",
            (int(chat_turn_id),),
        ).fetchone()

    def chat_turn_status(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT status FROM chat_turns WHERE id=?", (int(chat_turn_id),),
        ).fetchone()

    def chat_turn_user_message_id(self, chat_turn_id: int) -> Any:
        return self._conn.execute(
            "SELECT user_message_id FROM chat_turns WHERE id=?", (int(chat_turn_id),),
        ).fetchone()

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
        row = self.read_chat_turn(chat_turn_id)
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
