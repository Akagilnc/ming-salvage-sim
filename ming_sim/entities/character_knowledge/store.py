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
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ming_sim.applier import safe_json_dumps, sanitize_sqlite_text
from ming_sim.participant_roster import participant_roster_names

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

# Source-id shapes that identify a private brief / legacy secret order.
_SECRET_ORDER_SOURCE = re.compile(r"secret_order(?:_brief)?:(\d+)")
_PUBLIC_SAYING_SOURCE = re.compile(r"public_saying:(\d+)")


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
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


def _load_targets(raw: object) -> Dict[str, List[str]]:
    """Decode an excluded_targets column: {"people": [...], "offices": [...]}."""
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for key, value in parsed.items():
        out[str(key)] = [str(x) for x in value] if isinstance(value, list) else []
    return out


class CharacterKnowledgeStore:
    """Single write port for both knowledge ledgers; reads return plain dicts."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    # ── write port ───────────────────────────────────────────────

    def record_participation(
        self, *, turn: int, year: int, period: int, participants: Iterable[str],
        kind: str, title: str, body: str = "", source_id: str = "",
        excluded_names: Optional[Iterable[str]] = None, commit: bool = True,
    ) -> int:
        """Record that each named character took part in one event.

        One source produces one row per participant, so re-recording the same
        event is idempotent (the unique key is character+kind+source).
        """
        source = str(source_id or f"{kind}:{int(turn)}:{title}")
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
        """Record one event in the public lane (character_name='')."""
        source = str(source_id or f"public:{int(turn)}:{title}")
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
        """Register a durable shared source and the characters who know it."""
        source = str(source_id or f"{kind}:{int(turn)}:{title}")
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
                "SELECT turn, year, period, title, body, source_id, excluded_names "
                "FROM character_knowledge_events WHERE character_name='' AND turn=? "
                "ORDER BY id",
                (int(turn),),
            ).fetchall()
        ]

    def sources_for_turn(self, turn: int) -> List[Dict[str, object]]:
        """Shared sources registered in one month, oldest first."""
        return [
            dict(row) for row in self._conn.execute(
                "SELECT turn, year, period, title, body, source_id, "
                "participant_roster, excluded_names, excluded_targets "
                "FROM character_knowledge_sources WHERE turn=? ORDER BY id",
                (int(turn),),
            ).fetchall()
        ]

    def public_kind_for_source(self, source_id: str) -> Optional[str]:
        """The public-lane kind already recorded for this source, if any."""
        row = self._conn.execute(
            "SELECT kind FROM character_knowledge_events "
            "WHERE character_name='' AND source_id=?",
            (str(source_id or ""),),
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
        row = self._conn.execute(
            "SELECT source_id, kind, participant_roster, excluded_names, excluded_targets "
            "FROM character_knowledge_sources WHERE source_id=?",
            (str(source_id or ""),),
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
        return self._conn.execute(
            "SELECT 1 FROM character_knowledge_events WHERE source_id=? LIMIT 1",
            (str(source_id or ""),),
        ).fetchone() is not None

    def exclusions_for_source(self, source_id: str) -> List[str]:
        """Names excluded from a source, in ledger precedence order.

        The event row wins over the source row: the narrower, more specific
        record of who may not see this. Private briefs and public sayings keep
        their exclusions on their own tables (resolved by the caller, which owns
        those ledgers).
        """
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
        row = self._conn.execute(
            "SELECT excluded_targets FROM character_knowledge_sources WHERE source_id=?",
            (str(source_id or ""),),
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
        """Order id when this source id names a brief / legacy secret order."""
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
