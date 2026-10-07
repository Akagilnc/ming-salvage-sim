"""What a character knows, and what the world knows out loud.

#1889: 人物公私经历与知识来源的持久读写从 ``db.py`` 大块按职责拆出。

Two ledgers, deliberately distinct:

``character_knowledge_events``
    One row per (character, event). ``character_name=''`` is the public lane —
    what everyone may know. A secret order never lands here (#883): those live
    in the assignee-only brief table, which has its own private read seam.

``character_knowledge_sources``
    A durable record several characters share, discovered by its
    ``participant_roster`` rather than by record kind — so a new producer
    becomes knowable without growing a reader branch.

The month an event happened is part of the fact, so year/period are recorded
here rather than inferred by callers. Exclusion lists are the secrecy
boundary and travel with the row that carries the content.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from uuid import uuid4

from ming_sim.applier import (
    StoredDocumentError,
    durable_int,
    load_stored_json,
    load_stored_list,
    load_stored_object,
    safe_json_dumps,
    sanitize_sqlite_text,
)
from ming_sim.participant_roster import participant_roster_names
from ming_sim.entities.column_write import upsert_by_pk

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS character_knowledge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn INTEGER NOT NULL,
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    character_name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    excluded_names TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(character_name, kind, source_id)
);
CREATE INDEX IF NOT EXISTS idx_character_knowledge_events_character
    ON character_knowledge_events(character_name, turn, id);
CREATE TABLE IF NOT EXISTS character_knowledge_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn INTEGER NOT NULL,
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL UNIQUE,
    participant_roster TEXT NOT NULL DEFAULT '[]',
    excluded_names TEXT NOT NULL DEFAULT '[]',
    excluded_targets TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_character_knowledge_sources_turn
    ON character_knowledge_sources(turn, id);
"""

# Source-id shapes that identify a private brief.
_SECRET_ORDER_SOURCE = re.compile(r"secret_order_brief:(\d+)")
_PUBLIC_SAYING_SOURCE = re.compile(r"public_saying:(\d+)")


def source_is_blank(source_id: object = "") -> bool:
    """True only when source_id has no non-whitespace content."""
    return not str(source_id or "").strip()


def source_identity(source_id: str = "") -> str:
    """Durable source identity for knowledge writes.

    Explicit identity (any non-blank string) is returned byte-for-byte so write
    and delete/lookup stay on the same key. Only a blank id is replaced: mint a
    unique structured token. Never derive identity from free title/body, and
    never strip or rewrite a provided non-blank id.
    """
    raw = str(source_id or "")
    if not source_is_blank(raw):
        return raw
    return f"knowledge:{uuid4().hex}"


def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


def _names(values: Optional[Iterable[str]]) -> List[str]:
    """De-duplicated, order-preserving list of non-empty names."""
    return list(dict.fromkeys(
        str(v).strip() for v in (values or []) if str(v).strip()
    ))


def _targets(values: Optional[Mapping[str, Iterable[str]]]) -> Dict[str, List[str]]:
    return {k: _names(v) for k, v in (values or {}).items()}


def _load_list(raw: object) -> List[str]:
    parsed = load_stored_list(raw, label="角色见闻名单")
    if any(not isinstance(item, str) for item in parsed):
        raise ValueError("名单成员须为文字")
    return parsed


def _load_targets(raw: object) -> Dict[str, List[str]]:
    """Decode an excluded_targets column: {"people": [...], "offices": [...]}."""
    parsed = load_stored_object(raw, label="角色见闻排除对象")
    out: Dict[str, List[str]] = {}
    for key, value in parsed.items():
        if not isinstance(value, list):
            raise ValueError(f"排除对象 {key} 须为列表，得 {type(value).__name__}")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("排除对象名单成员须为文字")
        out[str(key)] = value
    return out


_SNAPSHOT_COLUMNS = {
    "secret_orders": frozenset({
        "id", "turn_issued", "due_turn", "deadline_span", "year_issued", "period_issued",
        "minister_name", "title", "content", "tags", "importance", "status", "result",
        "sim_note", "excluded_names", "dossier_progress_json", "excluded_targets",
        "turn_closed", "created_at", "updated_at",
    }),
    "public_sayings": frozenset({
        "id", "turn", "year", "period", "body", "involved_characters", "affair_ref",
        "source_id", "excluded_names", "excluded_targets", "created_at",
    }),
}


class CharacterKnowledgeStore:
    """Single write port for both knowledge ledgers; reads return plain dicts."""

    def snapshot_rows(self, table: str) -> Any:
        if table not in _SNAPSHOT_COLUMNS:
            raise ValueError(table)
        return self._conn.execute(f"SELECT * FROM {table}").fetchall()

    def restore_snapshot(self, table: str, row: Mapping[str, object]) -> None:
        upsert_by_pk(self._conn, table, row, pk="id", allowed=_SNAPSHOT_COLUMNS[table], what=table)

    def delete_snapshot(self, table: str, row_id: object) -> None:
        if table not in _SNAPSHOT_COLUMNS:
            raise ValueError(table)
        self._conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))

    def secret_order_rows(self, status: str | None = None, minister_name: str | None = None) -> Any:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if minister_name:
            clauses.append("minister_name = ?")
            params.append(minister_name)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._conn.execute(
            f"SELECT * FROM secret_orders {where} ORDER BY id DESC", params,
        ).fetchall()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    def upsert_secret_brief(
        self, *, order_id: int, turn: int, year: int, period: int,
        minister_name: str, title: str, body: str, origin_chat_message_ids: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO secret_order_briefs "
            "(order_id,turn,year,period,minister_name,title,body,origin_chat_message_ids) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET "
            "turn=excluded.turn,year=excluded.year,period=excluded.period,"
            "minister_name=excluded.minister_name,title=excluded.title,body=excluded.body,"
            "origin_chat_message_ids=excluded.origin_chat_message_ids,updated_at=CURRENT_TIMESTAMP",
            (order_id, turn, year, period, minister_name, title, body, origin_chat_message_ids),
        )

    def secret_briefs_for(self, minister_name: str) -> list[Any]:
        return self._conn.execute(
            "SELECT turn,year,period,title,body,order_id FROM secret_order_briefs "
            "WHERE minister_name=? ORDER BY turn,order_id", (minister_name,),
        ).fetchall()

    def secret_brief_pins(self, order_id: int | None = None) -> list[Any]:
        if order_id is None:
            return self._conn.execute(
                "SELECT order_id,origin_chat_message_ids FROM secret_order_briefs",
            ).fetchall()
        return self._conn.execute(
            "SELECT order_id,origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
            (order_id,),
        ).fetchall()

    def has_active_secret_brief(self, minister_name: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM secret_order_briefs b INNER JOIN secret_orders o ON o.id=b.order_id "
            "WHERE b.minister_name=? AND o.status='active' LIMIT 1", (minister_name,),
        ).fetchone() is not None

    # ── write port ───────────────────────────────────────────────

    def record_participation(
        self, *, turn: int, year: int, period: int, participants: Iterable[str],
        kind: str, title: str, body: str = "", source_id: str = "",
        excluded_names: Optional[Iterable[str]] = None, commit: bool = True,
    ) -> int:
        """Record that each named character took part in one event.

        One source produces one row per participant, so re-recording the same
        event is idempotent (the unique key is character+kind+source).
        Identity is explicit source_id, or a fresh structured token when omitted
        — never free title, never a shared empty string.
        """
        source = source_identity(source_id)
        excluded = safe_json_dumps(
            _names(excluded_names), ensure_ascii=False)
        written = 0
        for name in _names(participants):
            self._conn.execute(
                "INSERT OR REPLACE INTO character_knowledge_events "
                "(turn,year,period,character_name,kind,title,body,source_id,excluded_names) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    int(turn), int(year), int(period), name, str(kind), str(title),
                    str(body), source, excluded,
                ),
            )
            written += 1
        if commit:
            self._conn.commit()
        return written

    def record_public_event(
        self, *, turn: int, year: int, period: int, title: str, body: str = "",
        source_id: str = "", excluded_names: Optional[Iterable[str]] = None,
        kind: str = "public", commit: bool = True,
    ) -> None:
        """Record one event in the public lane (character_name='').

        Identity is explicit source_id, or a fresh structured token when omitted
        — never free title, never a shared empty string.
        """
        source = source_identity(source_id)
        self._conn.execute(
            "INSERT OR REPLACE INTO character_knowledge_events "
            "(turn,year,period,character_name,kind,title,body,source_id,excluded_names) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                int(turn), int(year), int(period), "", sanitize_sqlite_text(kind),
                str(title), str(body), source,
                json.dumps(_names(excluded_names), ensure_ascii=False),
            ),
        )
        if commit:
            self._conn.commit()

    def register_source(
        self, *, turn: int, year: int, period: int, kind: str, title: str,
        body: str = "", source_id: str = "",
        participant_roster: Iterable[Mapping[str, object]] = (),
        excluded_names: Optional[Iterable[str]] = None,
        excluded_targets: Optional[Mapping[str, Iterable[str]]] = None,
        commit: bool = True,
    ) -> str:
        """Register a durable shared source and the characters who know it.

        Identity is explicit source_id, or a fresh structured token when omitted
        — never free title, never a shared empty string.
        """
        source = source_identity(source_id)
        roster = [
            dict(item) for item in participant_roster
            if item.get("character_id") or item.get("name")
        ]
        self._conn.execute(
            "INSERT OR REPLACE INTO character_knowledge_sources "
            "(turn,year,period,kind,title,body,source_id,participant_roster,"
            "excluded_names,excluded_targets) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                int(turn), int(year), int(period), sanitize_sqlite_text(kind),
                sanitize_sqlite_text(title), sanitize_sqlite_text(body),
                sanitize_sqlite_text(source),
                safe_json_dumps(roster, ensure_ascii=False),
                safe_json_dumps(_names(excluded_names), ensure_ascii=False),
                safe_json_dumps(_targets(excluded_targets), ensure_ascii=False),
            ),
        )
        if commit:
            self._conn.commit()
        return source

    # ── delete port ──────────────────────────────────────────────

    def delete_by_source_ids(self, source_ids: Iterable[str], *, commit: bool = True) -> int:
        """Drop every ledger row produced by these sources (events + sources).

        A retracted statement must leave no trace: the engine is a physical-fact
        ledger, so keeping the row would let a withdrawn claim stay knowable.
        """
        ids = list(dict.fromkeys(
            str(sid) for sid in source_ids if str(sid or "").strip()))
        if not ids:
            return 0
        removed = 0
        for sid in ids:
            removed += self._conn.execute(
                "DELETE FROM character_knowledge_events WHERE source_id = ?", (sid,)
            ).rowcount
            removed += self._conn.execute(
                "DELETE FROM character_knowledge_sources WHERE source_id = ?", (sid,)
            ).rowcount
        if commit:
            self._conn.commit()
        return removed

    def delete_sources_matching(self, pattern: str, *, commit: bool = True) -> int:
        """Drop source rows whose source_id matches a LIKE pattern."""
        removed = self._conn.execute(
            "DELETE FROM character_knowledge_sources WHERE source_id LIKE ?",
            (str(pattern),),
        ).rowcount
        if commit:
            self._conn.commit()
        return max(0, int(removed))

    # ── read port ────────────────────────────────────────────────

    def participant_record_rows(self):
        """Discover durable roster-bearing records without exposing dossier secrets."""
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for row in tables:
            table = str(row['name'])
            if table in {'character_knowledge_sources', 'decree_dossiers'}:
                continue
            quoted = '"' + table.replace('"', '""') + '"'
            columns = {str(c['name']) for c in self._conn.execute(f'PRAGMA table_info({quoted})').fetchall()}
            if 'participant_roster' not in columns:
                continue
            id_expr = 'id' if 'id' in columns else 'rowid'
            prefix = table[:-1] if table.endswith('s') else table
            source = 'source_id' if 'source_id' in columns else f"'{prefix}:' || {id_expr}"
            turn = next((c for c in ('turn', 'origin_turn', 'created_turn') if c in columns), '0')
            year = next((c for c in ('year', 'created_year') if c in columns), '0')
            period = next((c for c in ('period', 'created_period') if c in columns), '0')
            kind = 'kind' if 'kind' in columns else "'assignment'"
            title = 'title' if 'title' in columns else "''"
            body = next((c for c in ('body', 'stage_text', 'content', 'decree_text') if c in columns), "''")
            yield from self._conn.execute(
                f"SELECT {turn} AS turn, {year} AS year, {period} AS period, "
                f"{kind} AS kind, {title} AS title, {body} AS body, "
                f"{source} AS source_id, participant_roster "
                f"FROM {quoted} WHERE participant_roster <> '[]' ORDER BY turn, {id_expr}"
            ).fetchall()

    def events_for(
        self, character_name: str, *, include_exclusions: bool = False,
    ) -> List[Dict[str, object]]:
        """One character's own events, oldest first (``''`` = the public lane)."""
        rows = self._conn.execute(
            "SELECT turn, year, period, kind, title, body, source_id, excluded_names "
            "FROM character_knowledge_events WHERE character_name=? ORDER BY turn, id",
            (str(character_name or ""),),
        ).fetchall()
        return [self._event_row(row, include_exclusions) for row in rows]

    def all_sources(self) -> List[Dict[str, object]]:
        """Every registered shared source, oldest first."""
        return [
            dict(row) for row in self._conn.execute(
                "SELECT turn, year, period, kind, title, body, source_id, "
                "participant_roster, excluded_names, excluded_targets "
                "FROM character_knowledge_sources ORDER BY turn, id"
            ).fetchall()
        ]

    def public_events_for_turn(self, turn: int) -> List[Dict[str, object]]:
        """The public lane for one month, oldest first."""
        return [
            dict(row) for row in self._conn.execute(
                "SELECT id, turn, year, period, kind, title, body, source_id, excluded_names "
                "FROM character_knowledge_events WHERE character_name='' AND turn=? "
                "ORDER BY id",
                (int(turn),),
            ).fetchall()
        ]

    def record_investigation_spoiled_fact(
        self,
        *,
        target_name: str,
        fact_key: str,
        turn: int,
        year: int,
        period: int,
        effect: str,
        origin_ref: str = "",
    ) -> Dict[str, object]:
        """Persist one investigation spoil row; idempotent on (target, fact_key, effect)."""
        self._conn.execute(
            """
            INSERT INTO investigation_spoiled_facts
                (target_name, fact_key, turn, year, period, effect, origin_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_name, fact_key, effect) DO NOTHING
            """,
            (
                target_name, fact_key, int(turn), int(year), int(period),
                effect, str(origin_ref or "")[:120],
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM investigation_spoiled_facts "
            "WHERE target_name=? AND fact_key=? AND effect=?",
            (target_name, fact_key, effect),
        ).fetchone()
        return dict(row) if row is not None else {}

    def list_investigation_spoiled_facts(
        self, target_name: str,
    ) -> List[Dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM investigation_spoiled_facts WHERE target_name=? "
            "ORDER BY fact_key, id",
            (str(target_name or "").strip(),),
        ).fetchall()
        return [dict(r) for r in rows]

    def secret_order_row(self, order_id: int, *, active_only: bool = False) -> Any:
        sql = "SELECT * FROM secret_orders WHERE id = ?"
        if active_only:
            sql += " AND status = 'active'"
        return self._conn.execute(sql, (int(order_id),)).fetchone()

    def get_secret_order(self, order_id: int) -> Optional[Dict[str, object]]:
        """单查一条密令（任意状态）。不存在返回 None。"""
        r = self.secret_order_row(int(order_id))
        if not r:
            return None
        return {
            "id": durable_int(r["id"], label="secret_orders.id", blank=None),
            "minister_name": r["minister_name"],
            "title": r["title"], "content": r["content"],
            "status": r["status"], "result": r["result"] or "",
            "sim_note": r["sim_note"] or "",
            "turn_issued": durable_int(
                r["turn_issued"], label="secret_orders.turn_issued", blank=None,
            ),
            "due_turn": durable_int(
                r["due_turn"], label="secret_orders.due_turn", blank=0,
            ),
            "turn_closed": r["turn_closed"],
        }

    def set_secret_order_sim_note(self, order_id: int, value: str) -> None:
        self._conn.execute(
            "UPDATE secret_orders SET sim_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (str(value), int(order_id)),
        )

    def sources_for_turn(self, turn: int) -> List[Dict[str, object]]:
        """Shared sources registered in one month, oldest first."""
        return [
            dict(row) for row in self._conn.execute(
                "SELECT id, turn, year, period, title, body, source_id, "
                "participant_roster, excluded_names, excluded_targets "
                "FROM character_knowledge_sources WHERE turn=? ORDER BY id",
                (int(turn),),
            ).fetchall()
        ]

    def public_kind_for_source(self, source_id: str) -> Optional[str]:
        """The public-lane kind already recorded for this source, if any."""
        if source_is_blank(source_id):
            return None
        source = str(source_id or "")
        row = self._conn.execute(
            "SELECT kind FROM character_knowledge_events "
            "WHERE character_name='' AND source_id=?",
            (source,),
        ).fetchone()
        return None if row is None else str(row["kind"] or "")

    def register_issue_sources(self) -> int:
        """Project issues that name participants into the shared source ledger.

        Read-side projection is registry-driven: an issue row is a shared
        knowledge source, discovered by its participant_roster rather than by
        record kind. Secret orders are deliberately absent (#883).
        """
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO character_knowledge_sources "
            "(turn,year,period,kind,title,body,source_id,participant_roster) "
            "SELECT origin_turn, 0, 0, 'assignment', title, stage_text, "
            "'issue:' || id, participant_roster FROM issues "
            "WHERE participant_roster <> '[]'"
        )
        return max(0, int(cur.rowcount or 0))

    def event_sources_for(self, character_name: str) -> List[Dict[str, object]]:
        """(source_id, excluded_names) pairs from one character's own events."""
        return [
            {"source_id": str(row["source_id"] or ""),
             "excluded_names": str(row["excluded_names"] or "[]")}
            for row in self._conn.execute(
                "SELECT source_id, excluded_names FROM character_knowledge_events "
                "WHERE character_name=? ORDER BY turn, id",
                (str(character_name or ""),),
            ).fetchall()
        ]

    def source_by_id(self, source_id: str) -> Optional[Dict[str, object]]:
        """One registered shared source, or None."""
        if source_is_blank(source_id):
            return None
        source = str(source_id or "")
        row = self._conn.execute(
            "SELECT source_id, kind, participant_roster, excluded_names, excluded_targets "
            "FROM character_knowledge_sources WHERE source_id=?",
            (source,),
        ).fetchone()
        return None if row is None else dict(row)

    def sources_of_kind(self, kind: str) -> List[Dict[str, object]]:
        """Registered shared sources of one kind, oldest first."""
        return [
            dict(row) for row in self._conn.execute(
                "SELECT source_id, participant_roster, excluded_names, excluded_targets "
                "FROM character_knowledge_sources WHERE kind=? ORDER BY id",
                (str(kind or ""),),
            ).fetchall()
        ]

    def sources_upto_turn(self, upto_turn: int) -> List[Dict[str, object]]:
        """Registered shared sources up to and including a month, oldest first."""
        return [
            dict(row) for row in self._conn.execute(
                "SELECT turn, year, period, kind, title, body, source_id, "
                "participant_roster, excluded_names FROM character_knowledge_sources "
                "WHERE turn <= ? ORDER BY turn, id",
                (int(upto_turn),),
            ).fetchall()
        ]

    def has_public_event_with_prefix(self, prefix: str) -> bool:
        """Whether the public lane already holds an event under this id prefix.

        Idempotence for disclosure: a secret order must not be published twice.
        """
        row = self._conn.execute(
            "SELECT 1 FROM character_knowledge_events "
            "WHERE character_name='' AND source_id LIKE ? ESCAPE '\\' LIMIT 1",
            (str(prefix or ""),),
        ).fetchone()
        return row is not None

    def has_event_for_source(self, source_id: str) -> bool:
        """Whether any event row carries this source (event rows outrank source rows)."""
        if source_is_blank(source_id):
            return False
        return self._conn.execute(
            "SELECT 1 FROM character_knowledge_events WHERE source_id=? LIMIT 1",
            (str(source_id or ""),),
        ).fetchone() is not None

    def exclusions_for_source(self, source_id: str) -> List[str]:
        """Names excluded from a source, in ledger precedence order.

        The event row wins over the source row: the narrower, more specific
        record of who may not see this. Private briefs and public sayings keep
        their exclusions on their own tables (resolved by the caller, which owns
        those ledgers). A blank source_id is not an identity — no shared boundary.
        Non-blank ids are matched exactly (no strip rewrite).
        """
        if source_is_blank(source_id):
            return []
        source = str(source_id or "")
        row = self._conn.execute(
            "SELECT excluded_names FROM character_knowledge_events "
            "WHERE source_id=? ORDER BY id LIMIT 1",
            (source,),
        ).fetchone()
        if row is not None:
            return _load_list(row["excluded_names"])
        row = self._conn.execute(
            "SELECT excluded_names FROM character_knowledge_sources WHERE source_id=?",
            (source,),
        ).fetchone()
        return [] if row is None else _load_list(row["excluded_names"])

    def exclusion_targets_for_source(self, source_id: str) -> Dict[str, List[str]]:
        """People/offices excluded from a shared source."""
        if source_is_blank(source_id):
            return {}
        source = str(source_id or "")
        row = self._conn.execute(
            "SELECT excluded_targets FROM character_knowledge_sources WHERE source_id=?",
            (source,),
        ).fetchone()
        if row is None:
            return {}
        payload = _load_targets(row["excluded_targets"])
        return {
            "people": payload.get("people", []),
            "offices": payload.get("offices", []),
        }

    @staticmethod
    def roster_names(raw: object) -> set[str]:
        """Character names on a persisted roster column."""
        return participant_roster_names(raw)

    @staticmethod
    def secret_order_id_in(source_id: str) -> Optional[int]:
        """Order id when this source id names a private brief."""
        match = _SECRET_ORDER_SOURCE.fullmatch(str(source_id or ""))
        return None if match is None else int(match.group(1))

    @staticmethod
    def public_saying_id_in(source_id: str) -> Optional[int]:
        """Public-saying id when this source id names one."""
        match = _PUBLIC_SAYING_SOURCE.fullmatch(str(source_id or ""))
        return None if match is None else int(match.group(1))

    @staticmethod
    def _event_row(row: Any, include_exclusions: bool) -> Dict[str, object]:
        item: Dict[str, object] = {
            "turn": int(row["turn"]),
            "year": int(row["year"]),
            "period": int(row["period"]),
            "kind": row["kind"],
            "title": row["title"],
            "body": row["body"],
            "source_id": row["source_id"],
        }
        if include_exclusions:
            item["excluded_names"] = row["excluded_names"] or "[]"
        return item

    def record_secret_dossier_progress(
        self,
        order_id: int,
        dossier_id: int,
        turn: int,
        band: str,
        text: str,
        *,
        is_terminal: bool,
        origin: str,
    ) -> int:
        """Full private-rail write: load JSON, dedupe by turn+origin base, allocate id, sort, persist.

        Caller owns the transaction/commit. Missing order raises ValueError.
        """
        from ming_sim.supervision import report_origin_base

        row = self._conn.execute(
            "SELECT dossier_progress_json FROM secret_orders WHERE id=?",
            (int(order_id),),
        ).fetchone()
        if row is None:
            raise ValueError("密令不存在")
        reports = load_stored_list(
            row["dossier_progress_json"], label="dossier_progress_json",
        )
        # 同月、同一业务身份只留一条。催办/核议与月度奏报 origin base 不同，同月并存。
        # 既存成员 id/turn 与读缝 coerce→durable_int 同一契约：损坏沿系统边界上抛，
        # 不得靠 Python int() 截断/收 bool 正常消费（#1889 R5）。
        # 查重/id 分配的 get 默认 0 只是中间匹配；排序与既存 id 最终消费与旧算法/
        # coerce 一样要求键在场（缺 turn 不是合法 absence；turn=0 仍合法）。
        incoming = report_origin_base(origin)
        incoming_turn = int(turn)

        def _as_member(item: object) -> Mapping:
            if not isinstance(item, Mapping):
                raise StoredDocumentError("dossier_progress 成员须为对象")
            return item

        def _turn_for_dedupe(item: object) -> int:
            """查重中间默认：缺键当 0（旧 get）；键在场走 durable_int。"""
            m = _as_member(item)
            if "turn" not in m:
                return 0
            return durable_int(m["turn"], label="dossier_progress.turn", blank=None)

        def _id_for_allocate(item: object) -> int:
            """id 分配中间默认：缺键当 0（旧 get）；键在场走 durable_int。"""
            m = _as_member(item)
            if "id" not in m:
                return 0
            return durable_int(m["id"], label="dossier_progress.id", blank=None)

        def _required_turn(item: object) -> int:
            """最终消费（排序）：键必在场，与 coerce item['turn'] / 旧 int(item['turn']) 同。"""
            m = _as_member(item)
            try:
                raw = m["turn"]
            except KeyError as exc:
                raise StoredDocumentError("dossier_progress.turn 损坏") from exc
            return durable_int(raw, label="dossier_progress.turn", blank=None)

        def _required_id(item: object) -> int:
            """最终消费（既存 id / 排序）：键必在场。"""
            m = _as_member(item)
            try:
                raw = m["id"]
            except KeyError as exc:
                raise StoredDocumentError("dossier_progress.id 损坏") from exc
            return durable_int(raw, label="dossier_progress.id", blank=None)

        try:
            existing = next((
                item for item in reports
                if not item.get("is_terminal")
                and _turn_for_dedupe(item) == incoming_turn
                and report_origin_base(item.get("origin")) == incoming
            ), None)
            if existing is None or is_terminal:
                report_id = max(
                    (_id_for_allocate(item) for item in reports), default=0,
                ) + 1
                existing = {
                    "id": report_id, "dossier_id": int(dossier_id),
                    "turn": incoming_turn,
                    "progress_band": band, "memorial_text": text,
                    "is_terminal": bool(is_terminal), "origin": origin,
                }
                reports.append(existing)
            else:
                report_id = _required_id(existing)
                existing.update(
                    progress_band=band, memorial_text=text, origin=origin,
                )
            reports.sort(
                key=lambda item: (_required_turn(item), _required_id(item)),
            )
        except StoredDocumentError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise StoredDocumentError(
                f"dossier_progress 损坏：{exc}",
            ) from exc
        self._conn.execute(
            "UPDATE secret_orders SET dossier_progress_json=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(reports, ensure_ascii=False), int(order_id)),
        )
        return report_id

    def list_secret_dossier_progress_items(self, order_id: int) -> list:
        """Load private-rail progress members; missing order is legal absence ([])."""
        row = self._conn.execute(
            "SELECT dossier_progress_json FROM secret_orders WHERE id=?",
            (int(order_id),),
        ).fetchone()
        if row is None:
            return []
        return load_stored_list(
            row["dossier_progress_json"], label="dossier_progress_json",
        )

    def write_create_secret_order(self, params: Any = ()) -> Any:
        return self._conn.execute("\n                INSERT INTO secret_orders\n                    (turn_issued, due_turn, deadline_span, year_issued, period_issued, minister_name, title, content, tags, importance, status, excluded_names, excluded_targets)\n                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)\n                ", params)

    def write_close_in_current_transaction(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                UPDATE secret_orders\n                SET status = ?, result = ?, turn_closed = ?, updated_at = CURRENT_TIMESTAMP\n                WHERE id = ?\n                ', params)

    def write_submit_secret_order_for_review(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE secret_orders SET due_turn = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'active'",
            params,
        )

    def read_restore_secret_order_brief_projection_in_tx(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT turn_issued,year_issued,period_issued,minister_name,title,content FROM secret_orders WHERE id=?', params).fetchone()

    def read_upsert_secret_order(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id FROM secret_orders WHERE minister_name=? AND status='active' ORDER BY id DESC LIMIT 1", params).fetchone()

    def read_update_secret_order_by_id(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, tags, minister_name, excluded_names, excluded_targets FROM secret_orders WHERE id=?', params).fetchone()

    def write_update_secret_order_by_id(self, params: Any = ()) -> Any:
        return self._conn.execute('UPDATE secret_orders SET title=?, content=?, tags=?, due_turn=?, deadline_span=?, excluded_names=?, excluded_targets=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', params)

    def write_update_secret_order_by_id_secret_orders(self, params: Any = ()) -> Any:
        return self._conn.execute('UPDATE secret_orders SET title=?, content=?, tags=?, excluded_names=?, excluded_targets=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', params)

    def read_submit_secret_order_for_review(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status, turn_issued FROM secret_orders WHERE id = ?', params).fetchone()

    def read_rush_secret_order(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, title, status, result, due_turn FROM secret_orders WHERE id = ?', params).fetchone()

    def write_rush_secret_order(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE secret_orders SET due_turn = ?, deadline_span = 0, "
            "updated_at=CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )

    def write_rush_secret_order_secret_orders(self, params: Any = ()) -> Any:
        return self._conn.execute(
            "UPDATE secret_orders SET due_turn = ?, deadline_span = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )

    def read_auto_submit_due_secret_orders(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            SELECT id, title, result FROM secret_orders\n            WHERE status = 'active' AND due_turn > 0 AND due_turn <= ?\n            ORDER BY id\n            ", params).fetchall()

    def read_knowledge_exclusions_for_source(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT excluded_names FROM secret_orders WHERE id=?', params).fetchone()

    def read_knowledge_exclusion_targets_for_source(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT excluded_targets FROM secret_orders WHERE id=?', params).fetchone()

    def read_create_secret_order(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT COUNT(*) FROM secret_orders WHERE status='active'", params).fetchone()

    def read_interrupt_dossiers_for_character(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT status,result FROM secret_orders WHERE id=?', params).fetchone()

    def read_build_translation_target_grounding(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT id, title FROM secret_orders WHERE status='active' ORDER BY id", params).fetchall()

    def read_household_ledger(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id,excluded_names,excluded_targets FROM secret_orders', params).fetchall()

    def read_knowledge_exclusions_for_source_excluded_names(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT excluded_names FROM public_sayings WHERE id=?', params).fetchone()

    def read_knowledge_exclusion_targets_for_source_excluded_targets(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT excluded_targets FROM public_sayings WHERE id=?', params).fetchone()

    def write_record_public_saying(self, params: Any = ()) -> Any:
        return self._conn.execute('INSERT INTO public_sayings (turn, year, period, body, involved_characters, affair_ref, source_id, excluded_names, excluded_targets) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', params)

    def write_record_public_saying_public_sayings(self, params: Any = ()) -> Any:
        return self._conn.execute('UPDATE public_sayings SET source_id=? WHERE id=?', params)

    def read_list_public_sayings(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT id, turn, year, period, body, involved_characters, affair_ref, source_id, excluded_names, excluded_targets FROM public_sayings ORDER BY id', params).fetchall()
