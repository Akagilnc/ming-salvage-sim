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
from typing import Any, Dict, List, Mapping, Optional

from ming_sim.applier import (
    StoredDocumentError,
    durable_int,
    load_stored_list,
)

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


                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
CREATE INDEX IF NOT EXISTS idx_character_knowledge_sources_turn
    ON character_knowledge_sources(turn, id);
"""

def ensure_schema(conn: Any) -> None:
    conn.executescript(_SCHEMA_SQL)


class CharacterKnowledgeStore:
    """Single write port for both knowledge ledgers; reads return plain dicts."""

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

    # ── delete port ──────────────────────────────────────────────

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
            "turn_issued": durable_int(
                r["turn_issued"], label="secret_orders.turn_issued", blank=None,
            ),
            "due_turn": durable_int(
                r["due_turn"], label="secret_orders.due_turn", blank=0,
            ),
            "turn_closed": r["turn_closed"],
        }

    def list_secret_orders(
        self,
        status: str | None = None,
        minister_name: str | None = None,
    ) -> list[dict[str, object]]:
        from ming_sim.applier import durable_int, load_stored_list, load_stored_object
        from ming_sim.entities.dossier.store import DossierStore

        rows = self.secret_order_rows(status, minister_name)
        dossiers = DossierStore(self._conn)
        out: list[dict[str, object]] = []
        for r in rows:
            oid = durable_int(r["id"], label="secret_orders.id", blank=None)
            dossier = dossiers.get_for_secret_order(oid)
            out.append({
                "id": oid,
                "turn_issued": durable_int(
                    r["turn_issued"], label="secret_orders.turn_issued", blank=None,
                ),
                "due_turn": durable_int(
                    r["due_turn"], label="secret_orders.due_turn", blank=0,
                ),
                "deadline_span": durable_int(
                    r["deadline_span"], label="secret_orders.deadline_span", blank=0,
                ),
                "year_issued": durable_int(
                    r["year_issued"], label="secret_orders.year_issued", blank=None,
                ),
                "period_issued": durable_int(
                    r["period_issued"], label="secret_orders.period_issued", blank=None,
                ),
                "minister_name": r["minister_name"],
                "title": r["title"],
                "content": r["content"],
                "tags": load_stored_list(r["tags"], label="tags"),
                "importance": durable_int(
                    r["importance"], label="secret_orders.importance", blank=None,
                ),
                "status": r["status"],
                "result": r["result"] or "",
                    "dossier_progress": (
                    dossiers.list_dossier_progress(int(dossier["id"]))
                    if dossier is not None else []
                ),
                "turn_closed": r["turn_closed"],
            })
        return out

    def get_active_secret_orders_for_minister(self, minister_name: str) -> list[dict[str, object]]:
        return self.list_secret_orders(status="active", minister_name=minister_name)


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
