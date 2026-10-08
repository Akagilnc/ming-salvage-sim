"""Person event log: the append-only record of what a person did, and when.

#1889: 人物公私经历的持久写读从 ``db.py`` 大块按职责拆出。This module owns the
``person_logs`` table — its schema, its single write port, and its reads. The
month it happened is part of the fact (a log line without its month cannot be
placed in the reign), so year/period are recorded here rather than inferred by
callers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from ming_sim.applier import connection_owns_transaction
from ming_sim.entities.column_write import upsert_by_pk


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS person_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn INTEGER NOT NULL,
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    person_name TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_summary TEXT NOT NULL DEFAULT '',
    derived_from TEXT NOT NULL DEFAULT '',
    normalized TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    origin_ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(person_name) REFERENCES characters(name)
);
CREATE INDEX IF NOT EXISTS idx_person_logs_person
    ON person_logs(person_name, turn, id);
CREATE INDEX IF NOT EXISTS idx_person_logs_turn
    ON person_logs(turn, person_name);
CREATE INDEX IF NOT EXISTS idx_person_logs_origin
    ON person_logs(origin_ref, id);
"""


def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


_EDGE_COLUMNS = frozenset({
    "id", "source", "target", "event_kind", "context", "origin", "origin_round", "turn",
    "year", "period", "evidence", "affair_id", "created_at",
})


class PersonLogStore:
    """Single write port for ``person_logs``; reads return plain dicts."""

    def edge_snapshot_rows(self) -> Any:
        return self._conn.execute("SELECT * FROM relation_edge_events").fetchall()

    def restore_edge(self, row: Mapping[str, object]) -> None:
        upsert_by_pk(self._conn, "relation_edge_events", row, pk="id", allowed=_EDGE_COLUMNS, what="relation_edge_events")

    def delete_edge(self, row_id: object) -> None:
        self._conn.execute("DELETE FROM relation_edge_events WHERE id=?", (row_id,))

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        ensure_schema(conn)

    def append(
        self,
        *,
        turn: int,
        year: int,
        period: int,
        person_name: str,
        action: str,
        payload_summary: str = "",
        derived_from: str = "",
        normalized: "str | Mapping[str, object]" = "",
        source: str = "",
        origin_ref: str = "",
        commit: bool = True,
    ) -> int:
        """Record one person event, dated by the month it happened."""
        name = str(person_name or "").strip()
        if not name:
            raise ValueError("person log requires person_name")
        act = str(action or "").strip()
        if not act:
            raise ValueError("person log requires action")
        if isinstance(normalized, Mapping):
            # Sorted keys so an identical event re-records byte-identically.
            normalized_text = json.dumps(dict(normalized), ensure_ascii=False, sort_keys=True)
        else:
            normalized_text = str(normalized or "")
        cur = self._conn.execute(
            "INSERT INTO person_logs "
            "(turn, year, period, person_name, action, payload_summary, "
            " derived_from, normalized, source, origin_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(turn), int(year), int(period),
                name, act,
                str(payload_summary or ""),
                str(derived_from or ""),
                # Full value: normalized is structured audit JSON, and any
                # truncation would cut it into something unparseable.
                normalized_text,
                str(source or ""),
                str(origin_ref or ""),
            ),
        )
        if commit:
            self._conn.commit()
        return int(cur.lastrowid or 0)

    def by_origin(self, origin_ref: str) -> List[Dict[str, object]]:
        """Every log line derived from one causal origin, oldest first."""
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM person_logs WHERE origin_ref=? ORDER BY turn, id",
                (str(origin_ref or ""),),
            ).fetchall()
        ]

    def count_by_origin(
        self, origin_ref: str, *, turn: int, action: str = "",
    ) -> int:
        """How many log lines this origin produced in one turn (optionally one action).

        Counted in SQL so the origin/turn index applies — the caller asks "how
        much of this origin landed", not "show me the rows".
        """
        sql = "SELECT COUNT(*) FROM person_logs WHERE origin_ref=? AND turn=?"
        params: list[object] = [str(origin_ref or ""), int(turn)]
        act = str(action or "").strip()
        if act:
            sql += " AND action=?"
            params.append(act)
        row = self._conn.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0

    def write_record_relation_edge_event(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            INSERT OR IGNORE INTO relation_edge_events\n                (source, target, event_kind, context, origin, origin_round,\n                 turn, year, period, evidence)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n            ', params)

    def write_delete_relation_edge_events_for_chat_turn(self, params: Any = ()) -> Any:
        return self._conn.execute('DELETE FROM relation_edge_events WHERE origin LIKE ?', params)

    def read_record_relation_edge_event(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            SELECT id FROM relation_edge_events\n            WHERE source = ? AND target = ? AND event_kind = ? AND context = ? AND origin = ?\n            ', params).fetchone()

    def read_guofu_targets_of_0056(self, params: Any = ()) -> Any:
        return self._conn.execute("SELECT DISTINCT target FROM relation_edge_events WHERE source='皇帝' AND event_kind='辜负' AND turn=? AND origin LIKE ?", params).fetchall()

    def read_existing_leg_id(self, params: Any = ()) -> Any:
        return self._conn.execute('\n            SELECT id FROM relation_edge_events\n            WHERE source = ? AND target = ? AND event_kind = ?\n              AND (origin = ? OR origin LIKE ?)\n            ORDER BY id LIMIT 1\n            ', params).fetchone()

    def read_select_faction_brew_targets(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT source, target, MAX(id) AS max_id FROM relation_edge_events WHERE year = ? AND period = ? GROUP BY source, target', params).fetchall()

    def read_project_relation_ledger(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT DISTINCT source, target FROM relation_edge_events', params).fetchall()

    def read_import_relationship_seed(self, params: Any = ()) -> Any:
        return self._conn.execute('SELECT COUNT(*) AS c FROM relation_edge_events', params).fetchone()

    def write_apply_seed_founding_segment(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            INSERT INTO relation_summaries\n                (source, target, dimension, founding_segment, recent_segment,\n                 last_event_id, last_brewed_turn, last_brewed_year, last_brewed_period)\n            VALUES (?, ?, ?, ?, '', 0, 0, 0, 0)\n            ON CONFLICT(source, target) DO UPDATE SET\n                dimension = excluded.dimension,\n                founding_segment = excluded.founding_segment,\n                updated_at = CURRENT_TIMESTAMP\n            ", params)

    def apply_seed_founding_segment(
        self,
        *,
        source: str,
        target: str,
        dimension: str,
        founding_segment: str,
    ) -> None:
        """#638 S7：seed 可选初始摘要落奠基段（只增不改；近况段/水位不动）。"""
        if dimension not in ("君臣", "大臣"):
            raise ValueError(f"未知关系维度: {dimension!r}")
        owns = connection_owns_transaction(self._conn)
        self.write_apply_seed_founding_segment(
            (str(source), str(target), dimension, str(founding_segment)),
        )
        if owns:
            self._conn.commit()

    def apply_relation_brew_result(
        self,
        *,
        source: str,
        target: str,
        dimension: str,
        founding_segment: str,
        recent_segment: str,
        last_event_id: int,
        turn: int,
        year: int,
        period: int,
    ) -> None:
        """摘要落定＋该关系 pending 清除在同一 DB 事务内原子落定。"""
        if dimension not in ("君臣", "大臣"):
            raise ValueError(f"未知关系维度: {dimension!r}")
        owns = connection_owns_transaction(self._conn)
        try:
            self.write_apply_relation_brew_result((
                str(source), str(target), dimension,
                str(founding_segment), str(recent_segment),
                int(last_event_id), int(turn), int(year), int(period),
            ))
            self.write_apply_relation_brew_result_relation_brew_pending(
                (str(source), str(target)),
            )
            if owns:
                self._conn.commit()
        except Exception:
            if owns:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            raise

    def mark_relation_brew_pending(
        self,
        *,
        source: str,
        target: str,
        year: int,
        period: int,
        reason: str = "",
    ) -> None:
        """酿制失败的月份进持久 pending-backlog。"""
        owns = connection_owns_transaction(self._conn)
        try:
            self.write_mark_relation_brew_pending(
                (str(source), str(target), int(year), int(period), str(reason)),
            )
            if owns:
                self._conn.commit()
        except Exception:
            if owns:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            raise

    def claim_relation_brew_targets(self, *, year: int, period: int) -> int:
        """settled 年月入选关系先作 durable claim。返回本次新认领的关系数。"""
        owns = connection_owns_transaction(self._conn)
        cur = self.write_claim_relation_brew_targets(
            (int(year), int(period), int(year), int(period)),
        )
        if owns:
            self._conn.commit()
        return max(int(cur.rowcount or 0), 0)

    def claim_faction_brew_targets(self, *, year: int, period: int) -> int:
        """settled 年月涉派派系先作 durable claim。返回本次新认领的派系数。"""
        owns = connection_owns_transaction(self._conn)
        cur = self.write_claim_faction_brew_targets(
            (int(year), int(period), int(year), int(period)),
        )
        if owns:
            self._conn.commit()
        return max(int(cur.rowcount or 0), 0)

    def mark_faction_brew_pending(
        self,
        *,
        faction: str,
        year: int,
        period: int,
        reason: str = "",
    ) -> None:
        """派系酿制失败月进持久 pending-backlog。"""
        owns = connection_owns_transaction(self._conn)
        try:
            self.write_mark_faction_brew_pending(
                (str(faction), int(year), int(period), str(reason)),
            )
            if owns:
                self._conn.commit()
        except Exception:
            if owns:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            raise

    def write_claim_relation_brew_targets(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            INSERT INTO relation_brew_pending (source, target, year, period, reason)\n            SELECT e.source, e.target, ?, ?, '月末新事件认领'\n            FROM relation_edge_events AS e\n            LEFT JOIN relation_summaries AS s\n                ON s.source = e.source AND s.target = e.target\n            WHERE e.year = ? AND e.period = ?\n              AND e.id > COALESCE(s.last_event_id, 0)\n            GROUP BY e.source, e.target\n            ON CONFLICT(source, target) DO NOTHING\n            ", params)

    def write_claim_faction_brew_targets(self, params: Any = ()) -> Any:
        return self._conn.execute("\n            INSERT INTO relation_brew_pending\n                (source, target, year, period, reason, item_kind)\n            SELECT DISTINCT '', c.faction, ?, ?, '月末涉派新事件认领', '派系'\n            FROM relation_edge_events AS e\n            JOIN characters AS c ON c.name = e.source OR c.name = e.target\n            JOIN factions AS f ON f.name = c.faction\n            LEFT JOIN faction_stance_summaries AS s ON s.faction = c.faction\n            WHERE e.year = ? AND e.period = ?\n              AND e.id > COALESCE(s.last_event_id, 0)\n            ON CONFLICT(source, target) DO NOTHING\n            ", params)

    def write_apply_relation_brew_result(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                INSERT INTO relation_summaries\n                    (source, target, dimension, founding_segment, recent_segment,\n                     last_event_id, last_brewed_turn, last_brewed_year, last_brewed_period)\n                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n                ON CONFLICT(source, target) DO UPDATE SET\n                    dimension = excluded.dimension,\n                    founding_segment = excluded.founding_segment,\n                    recent_segment = excluded.recent_segment,\n                    last_event_id = excluded.last_event_id,\n                    last_brewed_turn = excluded.last_brewed_turn,\n                    last_brewed_year = excluded.last_brewed_year,\n                    last_brewed_period = excluded.last_brewed_period,\n                    updated_at = CURRENT_TIMESTAMP\n                ', params)

    def write_apply_relation_brew_result_relation_brew_pending(self, params: Any = ()) -> Any:
        return self._conn.execute('DELETE FROM relation_brew_pending WHERE source = ? AND target = ?', params)

    def write_mark_relation_brew_pending(self, params: Any = ()) -> Any:
        return self._conn.execute('\n                INSERT INTO relation_brew_pending (source, target, year, period, reason)\n                VALUES (?, ?, ?, ?, ?)\n                ON CONFLICT(source, target) DO UPDATE SET\n                    year = excluded.year,\n                    period = excluded.period,\n                    reason = excluded.reason\n                ', params)

    def write_mark_faction_brew_pending(self, params: Any = ()) -> Any:
        return self._conn.execute("\n                INSERT INTO relation_brew_pending\n                    (source, target, year, period, reason, item_kind)\n                VALUES ('', ?, ?, ?, ?, '派系')\n                ON CONFLICT(source, target) DO UPDATE SET\n                    year = excluded.year,\n                    period = excluded.period,\n                    reason = excluded.reason\n                ", params)

    def write_apply_faction_brew_result(self, params: Any = ()) -> Any:
        return self._conn.execute("DELETE FROM relation_brew_pending WHERE item_kind = '派系' AND target = ?", params)

    def get_relation_summary(self, source: str, target: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM relation_summaries WHERE source = ? AND target = ?",
            (str(source), str(target)),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_relation_summaries(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM relation_summaries ORDER BY source, target",
        ).fetchall()
        return [dict(row) for row in rows]

    def get_relation_edge_events(
        self,
        *,
        person: Optional[str] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        event_kind: Optional[str] = None,
        evidence: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Filter + assemble relation edge rows; evidence column is bool."""
        from ming_sim.relations import normalize_evidence, validate_edge_kind

        clauses: list[str] = []
        params: list[Any] = []
        if person is not None:
            clauses.append("(source = ? OR target = ?)")
            params.extend([str(person), str(person)])
        if source is not None:
            clauses.append("source = ?")
            params.append(str(source))
        if target is not None:
            clauses.append("target = ?")
            params.append(str(target))
        if event_kind is not None:
            clauses.append("event_kind = ?")
            params.append(validate_edge_kind(event_kind))
        if evidence is not None:
            clauses.append("evidence = ?")
            params.append(int(normalize_evidence(evidence)))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM relation_edge_events {where} ORDER BY turn, id",
            params,
        ).fetchall()
        return [
            {
                **dict(row),
                "evidence": bool(row["evidence"]),
            }
            for row in rows
        ]

    def get_relation_brew_pending(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM relation_brew_pending WHERE item_kind = '关系' ORDER BY source, target",
        ).fetchall()
        return [dict(row) for row in rows]

    def get_faction_brew_pending(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM relation_brew_pending WHERE item_kind = '派系' ORDER BY target",
        ).fetchall()
        return [
            {
                "faction": row["target"],
                "year": row["year"],
                "period": row["period"],
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


