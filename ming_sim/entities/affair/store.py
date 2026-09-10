"""Affair records: identity, birth, close-by-declaration, pointers (ADR 0154)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ming_sim.applier import connection_owns_transaction, sanitize_sqlite_text

_ATTACH_NEW = "new"
_ATTACH_EXISTING = "existing"
_ATTACH_CLOSE = "close"
ATTACH_BIRTH = frozenset({_ATTACH_NEW, _ATTACH_EXISTING})
ATTACH_RESULT_CLOSE = frozenset({_ATTACH_CLOSE})
_ORIGIN_AFFAIR = "affair"
_ORIGIN_DOSSIER = "dossier"
_POINTER_TABLES = {
    "decree_dossiers": "案卷",
    "issues": "局势",
}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS affairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    origin TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','closed')),
    birth_key TEXT NOT NULL DEFAULT '',
    created_turn INTEGER NOT NULL,
    created_year INTEGER NOT NULL,
    created_period INTEGER NOT NULL,
    closed_turn INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_affairs_open
    ON affairs(status, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_affairs_declared_identity
    ON affairs(birth_key) WHERE birth_key <> '';
"""


@dataclass(frozen=True)
class Affair:
    """One continuing matter. Current situation lives on textual facts, not here."""

    id: int
    name: str
    origin: str
    status: str
    birth_key: str
    created_turn: int
    created_year: int
    created_period: int
    closed_turn: int


class AffairStore:
    """World-record home for affairs. Close only by explicit declaration."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        conn.executescript(_SCHEMA_SQL)

    def open(
        self,
        *,
        name: str,
        origin: str,
        year: int,
        period: int,
        turn: int,
        birth_key: str = "",
    ) -> Affair:
        title = str(name or "").strip()
        cause = str(origin or "").strip()
        if not title:
            raise ValueError("事务名字不能为空")
        if not cause:
            raise ValueError("事务起因不能为空")
        key = str(birth_key or "").strip()
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "INSERT INTO affairs (name, origin, status, birth_key, "
            "created_turn, created_year, created_period) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?)",
            (
                sanitize_sqlite_text(title),
                sanitize_sqlite_text(cause),
                sanitize_sqlite_text(key),
                int(turn),
                int(year),
                int(period),
            ),
        )
        if owns:
            self._conn.commit()
        return self.get(int(cur.lastrowid))

    def get(self, affair_id: int) -> Affair:
        row = self._conn.execute(
            "SELECT id, name, origin, status, birth_key, created_turn, "
            "created_year, created_period, closed_turn "
            "FROM affairs WHERE id=?",
            (int(affair_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"事务不存在：{affair_id}")
        return _row_to_affair(row)

    def list_open(self) -> tuple[Affair, ...]:
        rows = self._conn.execute(
            "SELECT id, name, origin, status, birth_key, created_turn, "
            "created_year, created_period, closed_turn "
            "FROM affairs WHERE status='open' ORDER BY id"
        ).fetchall()
        return tuple(_row_to_affair(row) for row in rows)

    def declare_closed(self, affair_id: int, *, turn: int) -> Affair:
        """LLM-declared close. No conditions, no dossier-status checks."""
        self.get(affair_id)
        owns = connection_owns_transaction(self._conn)
        self._conn.execute(
            "UPDATE affairs SET status='closed', closed_turn=? WHERE id=?",
            (int(turn), int(affair_id)),
        )
        if owns:
            self._conn.commit()
        return self.get(affair_id)

    def resolve_declaration(
        self,
        declaration: Mapping[str, object],
        *,
        year: int,
        period: int,
        turn: int,
        allowed: frozenset[str] = ATTACH_BIRTH,
    ) -> int:
        parsed = parse_affair_declaration(declaration, allowed=allowed)
        if parsed["attach"] == _ATTACH_EXISTING:
            affair_id = int(parsed["affair_id"])
            self.get(affair_id)
            return affair_id
        key = str(parsed.get("birth_key") or "").strip()
        if key:
            existing = self._conn.execute(
                "SELECT id FROM affairs WHERE birth_key=?",
                (key,),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        return self.open(
            name=str(parsed["name"]),
            origin=str(parsed["origin"]),
            year=year,
            period=period,
            turn=turn,
            birth_key=key,
        ).id

    def peek_declared_id(
        self,
        declaration: Mapping[str, object],
        *,
        allowed: frozenset[str] = ATTACH_BIRTH,
    ) -> int | None:
        """Read the declared identity without creating an affair."""
        parsed = parse_affair_declaration(declaration, allowed=allowed)
        if parsed["attach"] == _ATTACH_EXISTING:
            affair_id = int(parsed["affair_id"])
            self.get(affair_id)
            return affair_id
        key = str(parsed.get("birth_key") or "").strip()
        if not key:
            return None
        row = self._conn.execute(
            "SELECT id FROM affairs WHERE birth_key=?", (key,),
        ).fetchone()
        return None if row is None else int(row["id"])

    def close_from_declaration(
        self,
        declaration: Mapping[str, object],
        *,
        turn: int,
        authorized_ids: set[int],
    ) -> int:
        """Close only an open affair id visible in this batch's structured input."""
        parsed = parse_affair_declaration(
            declaration, allowed=ATTACH_RESULT_CLOSE,
        )
        affair_id = int(parsed["affair_id"])
        if affair_id not in authorized_ids:
            raise ValueError("事务不在本批可见输入")
        return self.declare_closed(affair_id, turn=turn).id

    def attach_from_declaration(
        self,
        table: str,
        row_id: int,
        declaration: Mapping[str, object],
        *,
        year: int,
        period: int,
        turn: int,
        authorized_ids: set[int] | None = None,
    ) -> int:
        """Bind a row from a birth declaration. Peek before create so conflicts leave no orphan."""
        parsed = parse_affair_declaration(declaration, allowed=ATTACH_BIRTH)
        if parsed["attach"] == _ATTACH_EXISTING and authorized_ids is not None:
            if int(parsed["affair_id"]) not in authorized_ids:
                raise ValueError("事务不在本批可见输入")
        current = self._current_pointer(table, row_id)
        peeked = self.peek_declared_id(declaration, allowed=ATTACH_BIRTH)
        if current:
            if peeked != current:
                raise ValueError(
                    f"{_POINTER_TABLES[table]}已指向事务 {current}，"
                    f"不能改指 {peeked or '新事务'}"
                )
            return current
        affair_id = self.resolve_declaration(
            declaration, year=year, period=period, turn=turn,
            allowed=ATTACH_BIRTH,
        )
        self.attach_pointer(table, row_id, affair_id)
        return affair_id

    def attach_pointer(self, table: str, row_id: int, affair_id: int) -> None:
        """Unbound may bind once; same id is idempotent; a different id fails loud."""
        self.get(affair_id)
        current = self._current_pointer(table, row_id)
        want = int(affair_id)
        if current == want:
            return
        if current != 0:
            raise ValueError(
                f"{_POINTER_TABLES[table]}已指向事务 {current}，不能改指 {want}"
            )
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            f"UPDATE {table} SET affair_id=? WHERE id=? AND affair_id=0",
            (want, int(row_id)),
        )
        if int(cur.rowcount or 0) != 1:
            raise ValueError(
                f"{_POINTER_TABLES[table]}已指向其它事务，不能改指 {want}"
            )
        if owns:
            self._conn.commit()

    def point_dossier(self, dossier_id: int, affair_id: int) -> None:
        self.attach_pointer("decree_dossiers", dossier_id, affair_id)

    def _current_pointer(self, table: str, row_id: int) -> int:
        label = _POINTER_TABLES.get(table)
        if label is None:
            raise ValueError(f"事务指针表非法：{table}")
        row = self._conn.execute(
            f"SELECT affair_id FROM {table} WHERE id=?",
            (int(row_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"{label}不存在：{row_id}")
        return int(row["affair_id"] or 0)

    def dossiers(self, affair_id: int) -> tuple[dict[str, object], ...]:
        self.get(affair_id)
        rows = self._conn.execute(
            "SELECT id, action_type, affair_id FROM decree_dossiers "
            "WHERE affair_id=? ORDER BY id",
            (int(affair_id),),
        ).fetchall()
        return tuple(
            {
                "id": int(row["id"]),
                "action_type": str(row["action_type"]),
                "affair_id": int(row["affair_id"] or 0),
            }
            for row in rows
        )

    def point_issue(self, issue_id: int, affair_id: int) -> None:
        self.attach_pointer("issues", issue_id, affair_id)

    def bind_from_origin_ref(self, table: str, row_id: int, origin_ref: str) -> None:
        """Follow origin_ref onto an affair. Dossier hops; affair:id binds directly."""
        kind, target = parse_origin_ref(origin_ref)
        if kind == _ORIGIN_AFFAIR:
            self.attach_pointer(table, row_id, target)
            return
        if kind != _ORIGIN_DOSSIER:
            return
        row = self._conn.execute(
            "SELECT affair_id FROM decree_dossiers WHERE id=?",
            (int(target),),
        ).fetchone()
        if row is None:
            return
        current = int(row["affair_id"] or 0)
        if current:
            self.attach_pointer(table, row_id, current)

    @staticmethod
    def origin_ref(affair_id: int) -> str:
        return f"{_ORIGIN_AFFAIR}:{int(affair_id)}"

    def origin_refs(self, affair_id: int) -> tuple[str, ...]:
        self.get(affair_id)
        refs = [self.origin_ref(affair_id)]
        refs.extend(f"{_ORIGIN_DOSSIER}:{int(row['id'])}" for row in self.dossiers(affair_id))
        return tuple(refs)

    def affair_id_for_issue(self, issue_id: int) -> int:
        row = self._conn.execute(
            "SELECT affair_id FROM issues WHERE id=?", (int(issue_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"局势不存在：{issue_id}")
        return int(row["affair_id"] or 0)

    @staticmethod
    def current_situation(textual_facts: Any, affair_id: int):
        return textual_facts.readable_materials(
            subject_kind="affair", subject_id=str(int(affair_id)),
        )

    def origin_ref_from_result_item(
        self,
        item: Mapping[str, object] | None,
        *,
        year: int,
        period: int,
        turn: int,
        authorized_ids: set[int] | None = None,
    ) -> str:
        """Birth declaration on a result item becomes affair:<id> when origin_ref is empty."""
        if not item:
            return ""
        origin_ref = str(item.get("origin_ref") or item.get("来源引用") or "").strip()
        if origin_ref:
            return origin_ref
        parsed = declaration_from_payload(item, allowed=ATTACH_BIRTH)
        if parsed is None:
            return ""
        if parsed["attach"] == _ATTACH_EXISTING and authorized_ids is not None:
            if int(parsed["affair_id"]) not in authorized_ids:
                raise ValueError("事务不在本批可见输入")
        return self.origin_ref(
            self.resolve_declaration(
                parsed, year=year, period=period, turn=turn, allowed=ATTACH_BIRTH,
            )
        )

    def experiences(self, affair_id: int) -> tuple[dict[str, object], ...]:
        """Read-time projection: story-ledger rows tagged or pointed at this affair."""
        from ming_sim.audience_night import exact_mingfa_publication_directive_id

        self.get(affair_id)
        refs = set(self.origin_refs(affair_id))
        directive_ids: set[int] = set()
        for row in self._conn.execute(
            "SELECT d.directive_id AS dossier_directive, "
            "pa.committed_directive_id AS committed_directive "
            "FROM decree_dossiers d "
            "LEFT JOIN pending_actions pa ON pa.id = d.pending_action_id "
            "WHERE d.affair_id=?",
            (int(affair_id),),
        ).fetchall():
            for key in ("dossier_directive", "committed_directive"):
                value = int(row[key] or 0)
                if value > 0:
                    directive_ids.add(value)
        out: list[dict[str, object]] = []
        for row in self._conn.execute(
            "SELECT id, person_names, tags, body, origin_ref "
            "FROM story_ledger_entries ORDER BY id"
        ).fetchall():
            origin = str(row["origin_ref"] or "").strip()
            try:
                tags = json.loads(row["tags"] or "[]")
            except (TypeError, ValueError):
                tags = []
            if not isinstance(tags, list):
                tags = []
            tagged = any(
                exact_mingfa_publication_directive_id(tag) in directive_ids
                for tag in tags
            )
            if origin not in refs and not tagged:
                continue
            try:
                people = json.loads(row["person_names"] or "[]")
            except (TypeError, ValueError):
                people = []
            if not isinstance(people, list):
                people = []
            out.append({
                "id": int(row["id"]),
                "body": str(row["body"] or ""),
                "origin_ref": origin,
                "person_names": [str(name) for name in people if str(name).strip()],
                "tags": [str(tag) for tag in tags if str(tag).strip()],
            })
        return tuple(out)


def parse_affair_declaration(
    raw: object,
    *,
    allowed: frozenset[str] | None = None,
) -> dict[str, object]:
    """Typed LLM declaration only. No prose parsing."""
    if not isinstance(raw, Mapping):
        raise ValueError("事务声明须为对象")
    attach = str(raw.get("attach") or "").strip()
    permitted = ATTACH_BIRTH | ATTACH_RESULT_CLOSE if allowed is None else allowed
    if attach not in permitted:
        if attach == _ATTACH_CLOSE:
            raise ValueError("本阶段不能了结事务")
        if attach in {_ATTACH_NEW, _ATTACH_EXISTING}:
            raise ValueError("顶层事务声明只接受了结")
        raise ValueError("事务声明 attach 不在本阶段")
    if attach == _ATTACH_NEW:
        name = str(raw.get("name") or "").strip()
        origin = str(raw.get("origin") or "").strip()
        if not name or not origin:
            raise ValueError("新事务声明须有名字与起因")
        key = str(raw.get("birth_key") or "").strip()
        out: dict[str, object] = {"attach": _ATTACH_NEW, "name": name, "origin": origin}
        if key:
            out["birth_key"] = key
        return out
    try:
        affair_id = int(raw.get("affair_id"))
    except (TypeError, ValueError):
        affair_id = 0
    if affair_id <= 0:
        raise ValueError(
            "了结须有 affair_id" if attach == _ATTACH_CLOSE else "接到已开事务须有 affair_id"
        )
    return {"attach": attach, "affair_id": affair_id}


def declaration_from_payload(
    payload: Mapping[str, object] | None,
    *,
    allowed: frozenset[str] = ATTACH_BIRTH,
) -> Mapping[str, object] | None:
    if not payload:
        return None
    raw = payload.get("affair_declaration")
    if raw is None:
        raw = payload.get("事务声明")
    if raw is None:
        return None
    return parse_affair_declaration(raw, allowed=allowed)


def parse_origin_ref(origin_ref: object) -> tuple[str, int] | tuple[None, None]:
    text = str(origin_ref or "").strip()
    if ":" not in text:
        return None, None
    kind, _, rest = text.partition(":")
    if kind not in {_ORIGIN_AFFAIR, _ORIGIN_DOSSIER}:
        return None, None
    try:
        target = int(rest)
    except (TypeError, ValueError):
        return None, None
    if target <= 0:
        return None, None
    return kind, target


def _row_to_affair(row: Any) -> Affair:
    return Affair(
        id=int(row["id"]),
        name=str(row["name"]),
        origin=str(row["origin"]),
        status=str(row["status"]),
        birth_key=str(row["birth_key"] or ""),
        created_turn=int(row["created_turn"]),
        created_year=int(row["created_year"]),
        created_period=int(row["created_period"]),
        closed_turn=int(row["closed_turn"] or 0),
    )
