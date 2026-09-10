"""Affair records: identity, birth, close-by-declaration, pointers (ADR 0154)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ming_sim.applier import connection_owns_transaction, sanitize_sqlite_text

_ATTACH_NEW = "new"
_ATTACH_EXISTING = "existing"

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
    ) -> int:
        parsed = parse_affair_declaration(declaration)
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

    def point_dossier(self, dossier_id: int, affair_id: int) -> None:
        self.get(affair_id)
        owns = connection_owns_transaction(self._conn)
        self._conn.execute(
            "UPDATE decree_dossiers SET affair_id=? WHERE id=? AND affair_id=0",
            (int(affair_id), int(dossier_id)),
        )
        if owns:
            self._conn.commit()

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
        self.get(affair_id)
        row = self._conn.execute(
            "SELECT id FROM issues WHERE id=?", (int(issue_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"局势不存在：{issue_id}")
        owns = connection_owns_transaction(self._conn)
        self._conn.execute(
            "UPDATE issues SET affair_id=? WHERE id=? AND affair_id=0",
            (int(affair_id), int(issue_id)),
        )
        if owns:
            self._conn.commit()

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


def parse_affair_declaration(raw: object) -> dict[str, object]:
    """Typed LLM declaration only. No prose parsing."""
    if not isinstance(raw, Mapping):
        raise ValueError("事务声明须为对象")
    attach = str(raw.get("attach") or "").strip()
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
    if attach == _ATTACH_EXISTING:
        try:
            affair_id = int(raw.get("affair_id"))
        except (TypeError, ValueError):
            affair_id = 0
        if affair_id <= 0:
            raise ValueError("接到已开事务须有 affair_id")
        return {"attach": _ATTACH_EXISTING, "affair_id": affair_id}
    raise ValueError("事务声明 attach 须为 new 或 existing")


def declaration_from_payload(payload: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if not payload:
        return None
    raw = payload.get("affair_declaration")
    if raw is None:
        return None
    return parse_affair_declaration(raw)


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
