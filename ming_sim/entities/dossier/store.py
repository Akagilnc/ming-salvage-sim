"""Dossier records: the durable truth of one decree under adjudication (ADR 0151).

The dossier is the only writable representation of "this decree exists, who
carries it, and where it stands". Verdicts and effects are materialized by the
settlement side; this store owns the row, its status chain, and the projections
read off that row.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from ming_sim.constants import DOSSIER_LINK_TYPES
from ming_sim.decree_vocabulary import dossier_action_policy
from ming_sim.strict_types import strict_int

DOSSIER_STATUSES = frozenset({"proposed", "promulgated", "executing", "closed"})
DOSSIER_TRANSITIONS = {
    "proposed": frozenset({"promulgated"}),
    "promulgated": frozenset({"executing", "closed"}),
    "executing": frozenset({"closed"}),
    "closed": frozenset(),
}
PROMULGATION_BLOCKED_LAYERS = frozenset({
    "", "cabinet_drafting", "palace_rescript", "six_offices",
})
DOSSIER_MODES = frozenset({"ordinary", "midzhi"})
# #619 / ADR 0073 reported-progress origin namespace (ID-11 open append).
DOSSIER_REPORT_ORIGIN_NS = "dossier-report:"
DOSSIER_REPORT_ORIGIN_MONTHLY = "dossier-report:monthly_errand"
DOSSIER_REPORT_ORIGIN_VERDICT = "dossier-report:execution_verdict"
DOSSIER_EXECUTION_OUTCOMES = frozenset({
    "executing", "fulfilled", "degraded", "failed", "transformed",
})

DOSSIER_SCHEMA_SQL = """
-- #571：旨意案卷是一等 durable truth。status 主链恰四值；封驳/留中
-- 只落 promulgation_decision + rescript_pending 组合态，不污染主链枚举。
CREATE TABLE IF NOT EXISTS decree_dossiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    target_kind TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    executor_kind TEXT NOT NULL DEFAULT '',
    executor_id TEXT NOT NULL DEFAULT '',
    source_chat_turn_id INTEGER NOT NULL DEFAULT 0,
    pending_action_id INTEGER NOT NULL DEFAULT 0,
    directive_id INTEGER,
    secret_order_id INTEGER,
    region_id TEXT NOT NULL DEFAULT '',
    decree_text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK(status IN ('proposed','promulgated','executing','closed')),
    promulgation_decision TEXT NOT NULL DEFAULT '',
    promulgation_blocked_layer TEXT NOT NULL DEFAULT '',
    promulgation_reason TEXT NOT NULL DEFAULT '',
    rescript_pending INTEGER NOT NULL DEFAULT 0,
    held_turn INTEGER NOT NULL DEFAULT 0,
    legal_reason_code TEXT NOT NULL DEFAULT '',
    stigma_json TEXT NOT NULL DEFAULT '[]',
    extension_json TEXT NOT NULL DEFAULT '{}',
    participant_roster TEXT NOT NULL DEFAULT '[]',
    office_archive_keys TEXT NOT NULL DEFAULT '[]',
    due_turn INTEGER NOT NULL DEFAULT 0,
    execution_outcome TEXT NOT NULL DEFAULT '',
    execution_note TEXT NOT NULL DEFAULT '',
    closed_turn INTEGER NOT NULL DEFAULT 0,
    interruption_reason TEXT NOT NULL DEFAULT '',
    created_turn INTEGER NOT NULL,
    created_year INTEGER NOT NULL,
    created_period INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    affair_id INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(directive_id) REFERENCES turn_directives(id) ON DELETE CASCADE,
    FOREIGN KEY(secret_order_id) REFERENCES secret_orders(id) ON DELETE CASCADE
);
-- #654：fan-out 幂等键＝(source_id, region_id)；单行 region_id='' 与旧语义等价
-- #1837：幂等键含 action_type，一份 pending 可同时产拨帑+任免两类案卷
-- （非属地 grant 的 region_id='' 不再把 appointment 短路成既有 grant 行）。
CREATE UNIQUE INDEX IF NOT EXISTS idx_decree_dossiers_pending_action
    ON decree_dossiers(pending_action_id, region_id, action_type)
    WHERE pending_action_id > 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_decree_dossiers_directive
    ON decree_dossiers(directive_id, region_id) WHERE directive_id > 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_decree_dossiers_secret_order
    ON decree_dossiers(secret_order_id) WHERE secret_order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_decree_dossiers_status
    ON decree_dossiers(status, id);
CREATE INDEX IF NOT EXISTS idx_decree_dossiers_target
    ON decree_dossiers(target_kind, target_id, status);
CREATE INDEX IF NOT EXISTS idx_decree_dossiers_executor
    ON decree_dossiers(executor_kind, executor_id, status)
"""


def normalize_dossier_mode(value: object) -> str:
    mode = value.strip() if isinstance(value, str) else value
    if not isinstance(mode, str) or mode not in DOSSIER_MODES:
        raise ValueError(f"案卷 mode 非法：{mode}")
    return mode


def has_execution_surface(
    action_type: object, payload: Optional[Mapping[str, object]] = None,
) -> bool:
    return dossier_action_policy(action_type, payload)["execution_surface"] not in {
        "terminal", "immediate",
    }


def hydrate_dossier_row(row: Any) -> dict[str, object]:
    """One fail-loud hydration contract for every dossier read (ADR 0005)."""
    out = dict(row)
    out["id"] = int(out["id"])
    out["region_id"] = str(out.get("region_id") or "")
    for key in (
        "source_chat_turn_id", "pending_action_id", "directive_id",
        "due_turn", "created_turn", "created_year", "created_period",
        "held_turn", "affair_id",
    ):
        out[key] = int(out.get(key) or 0)
    if out.get("secret_order_id") is not None:
        out["secret_order_id"] = int(out["secret_order_id"])
    out["rescript_pending"] = bool(out.get("rescript_pending"))
    try:
        payload = json.loads(out.get("payload_json") or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"案卷#{out['id']} payload_json 无效") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"案卷#{out['id']} payload_json 非对象")
    out["payload"] = payload
    out["mode"] = normalize_dossier_mode(
        payload["mode"] if "mode" in payload else "ordinary"
    )
    try:
        stigma = json.loads(out.get("stigma_json") or "[]")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"案卷#{out['id']} stigma_json 无效") from exc
    if not isinstance(stigma, list):
        raise ValueError(f"案卷#{out['id']} stigma_json 非列表")
    out["stigma"] = stigma
    try:
        roster = json.loads(out.get("participant_roster") or "[]")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"案卷#{out['id']} participant_roster 无效") from exc
    if not isinstance(roster, list):
        raise ValueError(f"案卷#{out['id']} participant_roster 非列表")
    out["participant_roster"] = roster
    try:
        extension = json.loads(out.get("extension_json") or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"案卷#{out['id']} extension_json 无效") from exc
    if not isinstance(extension, dict):
        raise ValueError(f"案卷#{out['id']} extension_json 非对象")
    signal = extension.get("execution_signal")
    if signal is not None and not isinstance(signal, dict):
        raise ValueError(f"案卷#{out['id']} execution_signal 非对象")
    out["execution_signal"] = signal
    return out


class DossierStore:
    """World-record home for dossiers. The row is the truth; views read it."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        conn.executescript(DOSSIER_SCHEMA_SQL)

    @staticmethod
    def ensure_locality_indexes(conn: Any) -> None:
        """#654 / #1837：pending 幂等键＝(pending_action_id, region_id, action_type)；
        directive 仍 (directive_id, region_id)；secret_order 不动。"""
        conn.execute("DROP INDEX IF EXISTS idx_decree_dossiers_pending_action")
        conn.execute("DROP INDEX IF EXISTS idx_decree_dossiers_directive")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_decree_dossiers_pending_action "
            "ON decree_dossiers(pending_action_id, region_id, action_type) "
            "WHERE pending_action_id > 0"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_decree_dossiers_directive "
            "ON decree_dossiers(directive_id, region_id) WHERE directive_id > 0"
        )

    def _commit(self, commit: bool) -> None:
        if commit and not bool(getattr(self._conn, "_commit_suspended", False)) and int(
            getattr(self._conn, "_atomic_depth", 0) or 0
        ) == 0:
            self._conn.commit()

    # ── identity reads ────────────────────────────────────────────

    def get(self, dossier_id: int) -> Optional[dict[str, object]]:
        row = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE id=?", (int(dossier_id),)
        ).fetchone()
        return None if row is None else hydrate_dossier_row(row)

    def get_for_directive(self, directive_id: int) -> Optional[dict[str, object]]:
        """存在性哨兵：确定序取首行（#654 fan-out 下 N 行时勿当唯一读面）。"""
        row = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE directive_id=? "
            "ORDER BY region_id, id LIMIT 1",
            (int(directive_id),),
        ).fetchone()
        return None if row is None else hydrate_dossier_row(row)

    def list_for_directive(self, directive_id: int) -> list[dict[str, object]]:
        """#654：directive 名下全部子差务，ORDER BY region_id, id。"""
        rows = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE directive_id=? "
            "ORDER BY region_id, id",
            (int(directive_id),),
        ).fetchall()
        return [hydrate_dossier_row(r) for r in rows]

    def get_for_secret_order(self, secret_order_id: int) -> Optional[dict[str, object]]:
        row = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE secret_order_id=?",
            (int(secret_order_id),),
        ).fetchone()
        return None if row is None else hydrate_dossier_row(row)

    def list_dossiers(
        self, *, status: Optional[str] = None, target_kind: Optional[str] = None,
        target_id: Optional[object] = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            if status not in DOSSIER_STATUSES:
                raise ValueError(f"案卷 status 非法：{status}")
            clauses.append("status=?")
            params.append(status)
        if target_kind is not None:
            clauses.append("target_kind=?")
            params.append(str(target_kind))
        if target_id is not None:
            clauses.append("target_id=?")
            params.append(str(target_id))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM decree_dossiers{where} ORDER BY id", params
        ).fetchall()
        return [hydrate_dossier_row(row) for row in rows]

    def find_by_decision_key(
        self, decision_key: str,
    ) -> Optional[dict[str, object]]:
        """按批红 decision_key 取廷议案卷（payload.decision_key + deliberation_state）。"""
        key = str(decision_key or "").strip()
        if not key:
            return None
        row = self._conn.execute(
            """
            SELECT * FROM decree_dossiers
            WHERE json_extract(payload_json, '$.decision_key') = ?
              AND json_extract(payload_json, '$.deliberation_state') IS NOT NULL
            ORDER BY id LIMIT 1
            """,
            (key,),
        ).fetchone()
        if row is None:
            return None
        out = hydrate_dossier_row(row)
        # 读缝附 payload 对象，避免调用方只认 payload 键时踩空
        try:
            out["payload"] = json.loads(str(out.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            out["payload"] = {}
        if not isinstance(out["payload"], dict):
            out["payload"] = {}
        return out

    def authorizes_effects(self, dossier_id: int) -> bool:
        """Return whether a dossier crossed either lawful promulgation path."""
        row = self._conn.execute(
            """
            SELECT d.status,d.promulgation_decision,
                   EXISTS(
                       SELECT 1 FROM decree_dossier_decisions h
                       WHERE h.dossier_id=d.id
                         AND h.rescript_action='force_promulgated'
                   ) AS was_force_promulgated
            FROM decree_dossiers d WHERE d.id=?
            """,
            (int(dossier_id),),
        ).fetchone()
        if row is None:
            return False
        return (
            str(row["status"] or "") in {"promulgated", "executing"}
            or str(row["promulgation_decision"] or "") == "promulgated"
            or bool(row["was_force_promulgated"])
        )

    # ── status chain ──────────────────────────────────────────────

    def transition(
        self, dossier_id: int, new_status: str, *, commit: bool = True,
    ) -> None:
        row = self._conn.execute(
            "SELECT status,action_type,payload_json,execution_outcome "
            "FROM decree_dossiers WHERE id=?",
            (int(dossier_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        old_status = str(row["status"])
        if new_status == old_status:
            return
        if new_status not in DOSSIER_TRANSITIONS[old_status]:
            raise ValueError(f"案卷非法迁移：{old_status} -> {new_status}")
        if old_status == "promulgated" and new_status == "closed":
            payload = json.loads(str(row["payload_json"] or "{}"))
            if has_execution_surface(row["action_type"], payload):
                raise ValueError("带执行判定面的案卷不得从 promulgated 直接 closed")
            if not str(row["execution_outcome"] or ""):
                raise ValueError("直达结案仍须填写执行格")
        closed_sql = ", closed_at=CURRENT_TIMESTAMP" if new_status == "closed" else ""
        self._conn.execute(
            f"UPDATE decree_dossiers SET status=?,updated_at=CURRENT_TIMESTAMP{closed_sql} "
            "WHERE id=?",
            (new_status, int(dossier_id)),
        )
        self._commit(commit)

    def close(
        self, dossier_id: int, reason: str = "", *, commit: bool = True,
    ) -> None:
        row = self.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        if row["status"] == "proposed":
            raise ValueError("待判案卷不能绕过颁布格直接结案")
        payload = json.loads(str(row.get("payload_json") or "{}"))
        immediate = not has_execution_surface(row["action_type"], payload)
        if row["status"] == "promulgated" and not immediate:
            raise ValueError("带执行判定面的案卷必须先进入 executing 并填写执行格")
        if row["status"] == "executing" and not str(row.get("execution_outcome") or ""):
            raise ValueError("执行中案卷须先填写执行格再结案")
        if row["status"] != "closed":
            self.transition(dossier_id, "closed", commit=False)
        self._conn.execute(
            "UPDATE decree_dossiers SET interruption_reason=? WHERE id=?",
            (str(reason or ""), int(dossier_id)),
        )
        self._commit(commit)

    # ── payload / participants / links ────────────────────────────

    def update_payload(
        self, dossier_id: int, payload: Mapping[str, object], *, commit: bool = True,
    ) -> None:
        """Replace payload_json for an existing dossier (deliberation_state 等 typed 字段)."""
        did = int(dossier_id)
        if self._conn.execute(
            "SELECT 1 FROM decree_dossiers WHERE id=?", (did,)
        ).fetchone() is None:
            raise KeyError(f"案卷不存在：{did}")
        if not isinstance(payload, Mapping):
            raise ValueError("案卷 payload 须为对象")
        self._conn.execute(
            "UPDATE decree_dossiers SET payload_json=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (json.dumps(dict(payload), ensure_ascii=False), did),
        )
        if commit:
            self._commit(True)

    def add_links(
        self, source_dossier_id: int, links: Iterable[Mapping[str, object]], *,
        commit: bool = True,
    ) -> None:
        """把确认后的新→旧案卷关联整批落账；任一坏引用则整批拒收并留痕。"""
        source_id = strict_int(source_dossier_id, accept_numeric_strings=False)
        source = self.get(source_id)
        if source is None:
            raise ValueError("关联来源指向不存在案卷")
        normalized: list[tuple[int, str, str]] = []
        rejection: Optional[tuple[int, str, str, str]] = None
        for item in links:
            try:
                target_id = strict_int(
                    item.get("target_dossier_id"), accept_numeric_strings=False
                )
            except (AttributeError, ValueError):
                target_id = 0
            relation = str(item.get("relation_type") or "") if isinstance(item, dict) else ""
            note = str(item.get("note") or "").strip() if isinstance(item, dict) else ""
            if self.get(target_id) is None:
                rejection = (target_id, relation, note, "关联指向不存在案卷")
            elif target_id >= source_id:
                rejection = (target_id, relation, note, "案卷关联只允许新案卷指向旧案卷")
            elif relation not in DOSSIER_LINK_TYPES:
                rejection = (target_id, relation, note, "案卷关联类型非法")
            elif not note:
                rejection = (target_id, relation, note, "案卷关联说明不能为空")
            if rejection is not None:
                break
            normalized.append((target_id, relation, note))
        if rejection is not None:
            target_id, relation, note, reason = rejection
            self.record_link_rejection(source_id, target_id, relation, note, reason)
            self._commit(commit)
            exc = ValueError(reason)
            # commit_pending_actions rolls its business savepoint back.  Carry the
            # rejected item across that boundary so its outer failure path can
            # persist the audit without retaining the incomplete secret order.
            # source_id belongs to the savepoint and may be reused after rollback.
            exc.dossier_link_rejection = (0, target_id, relation, note, reason)  # type: ignore[attr-defined]
            raise exc
        self._conn.executemany(
            """INSERT OR IGNORE INTO decree_dossier_links
               (source_dossier_id,target_dossier_id,relation_type,note)
               VALUES (?,?,?,?)""",
            [(source_id, target_id, relation, note)
             for target_id, relation, note in normalized],
        )
        self._commit(commit)

    def record_link_rejection(
        self, source_id: int, target_id: int, relation: str, note: str,
        reason: str, *, pending_action_id: Optional[int] = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO decree_dossier_link_rejections
               (source_dossier_id,pending_action_id,target_dossier_id,relation_type,note,reason)
               VALUES (?,?,?,?,?,?)""",
            (source_id, pending_action_id, target_id, relation, note, reason),
        )

    def links(
        self, dossier_id: int, *, direction: str = "outgoing",
    ) -> list[dict[str, object]]:
        """从任一端查询同一份单向关联真源。"""
        if direction not in {"outgoing", "incoming"}:
            raise ValueError("案卷关联查询方向非法")
        column = "source_dossier_id" if direction == "outgoing" else "target_dossier_id"
        rows = self._conn.execute(
            f"SELECT * FROM decree_dossier_links WHERE {column}=? ORDER BY id",
            (strict_int(dossier_id, accept_numeric_strings=False),),
        ).fetchall()
        return [dict(row) for row in rows]

    def link_rejections(
        self, source_dossier_id: Optional[int] = None, *,
        pending_action_id: Optional[int] = None,
    ) -> list[dict[str, object]]:
        if (source_dossier_id is None) == (pending_action_id is None):
            raise ValueError("须且只能按来源案卷或待确认动作查询拒收记录")
        if pending_action_id is not None:
            column, value = "pending_action_id", pending_action_id
        else:
            column, value = "source_dossier_id", source_dossier_id
        rows = self._conn.execute(
            f"SELECT * FROM decree_dossier_link_rejections WHERE {column}=? ORDER BY id",
            (strict_int(value, accept_numeric_strings=False),),
        ).fetchall()
        return [dict(row) for row in rows]

    def endorsements(self, dossier_id: int) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT id,dossier_id,form,endorser_id,imperial,source_chat_turn_id,decision_key "
            "FROM decree_dossier_endorsements WHERE dossier_id=? ORDER BY id",
            (int(dossier_id),),
        ).fetchall()
        return [{
            "id": int(row["id"]), "dossier_id": int(row["dossier_id"]),
            "form": str(row["form"]), "endorser_id": str(row["endorser_id"]),
            "imperial": bool(row["imperial"]),
            "source_chat_turn_id": int(row["source_chat_turn_id"] or 0),
            "decision_key": str(row["decision_key"] or ""),
        } for row in rows]

    def endorsed_candidates(self, current_turn: int) -> list[dict[str, object]]:
        """Typed backing choices projected from durable named endorsements."""
        rows = self._conn.execute(
            """SELECT d.id AS dossier_id, e.endorser_id, d.decree_text AS subject
               FROM decree_dossier_endorsements e
               JOIN decree_dossiers d ON d.id=e.dossier_id
               WHERE e.endorser_id<>'' AND d.created_turn<=?
               ORDER BY d.id DESC, e.id DESC""",
            (int(current_turn),),
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            dossier_id = int(row["dossier_id"])
            result.append({
                "dossier_id": dossier_id,
                "endorser_id": str(row["endorser_id"]),
                "subject": str(row["subject"] or ""),
            })
        return result

    def decisions(self, dossier_id: int) -> list[dict[str, object]]:
        """Production audit/restore read seam for the append-only verdict history."""
        rows = self._conn.execute(
            "SELECT * FROM decree_dossier_decisions WHERE dossier_id=? ORDER BY id",
            (strict_int(dossier_id, accept_numeric_strings=False),),
        ).fetchall()
        decisions: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["id"] = int(item["id"])
            item["dossier_id"] = int(item["dossier_id"])
            item["turn"] = int(item["turn"])
            item["primary_opponents"] = json.loads(
                str(item.pop("primary_opponents_json") or "[]")
            )
            item["criteria_snapshot"] = json.loads(
                str(item.pop("criteria_snapshot_json") or "{}")
            )
            item["affected_parties"] = json.loads(
                str(item.pop("affected_parties_json") or "[]")
            )
            item["midzhi_unpromulgatable"] = bool(
                item["midzhi_unpromulgatable"]
            )
            decisions.append(item)
        return decisions

    def list_for_simulation(self, turn: int) -> list[dict[str, object]]:
        """本月新生/重判案卷及所有未结案执行中案卷。

        #658：旧案本回合刚获 pending 颁布 verdict（如 stalled→backed 后顺颁）
        亦入同一清单，不另建第二可见集。
        """
        rows = self._conn.execute(
            """
            SELECT d.*,
                MAX(CASE WHEN
                       (d.created_turn=? AND d.promulgation_decision='promulgated')
                    OR (h.turn=? AND h.decision='promulgated')
                    OR (h.rescript_action='force_promulgated' AND h.turn=? - 1)
                THEN 1 ELSE 0 END) AS executable_this_turn
            FROM decree_dossiers d
            LEFT JOIN decree_dossier_decisions h ON h.dossier_id=d.id
            WHERE (
                    d.status='proposed'
                AND (
                       (d.created_turn=? AND d.promulgation_decision='')
                    OR (
                           d.promulgation_decision='rejected'
                       AND d.rescript_pending=0
                       AND d.held_turn > 0
                       AND ? > d.held_turn
                    )
                    OR (
                           d.promulgation_decision=''
                       AND EXISTS (
                               SELECT 1 FROM pending_promulgation_verdicts pv
                               WHERE pv.turn=? AND pv.dossier_id=d.id
                           )
                    )
                )
            ) OR (
                    d.status='executing'
            ) OR (
                    d.status='promulgated'
                AND (
                       d.created_turn=?
                    OR (h.turn=? AND h.decision='promulgated')
                    OR (
                           h.rescript_action='force_promulgated'
                       AND h.turn=? - 1
                    )
                )
            )
            GROUP BY d.id
            ORDER BY d.id
            """,
            (
                int(turn), int(turn), int(turn),
                int(turn), int(turn), int(turn),
                int(turn), int(turn), int(turn),
            ),
        ).fetchall()
        visible = []
        for row in rows:
            payload = json.loads(str(row["payload_json"] or "{}"))
            policy = dossier_action_policy(row["action_type"], payload)
            # Admission-owned effects never run through the simulator again.
            # An in-transit dossier remains visible as execution context until
            # its execution verdict closes it, however.
            if str(row["action_type"]) == "secret_order":
                continue
            if (
                policy["effect_owner"] != "immediate"
                or str(row["status"]) == "executing"
            ):
                visible.append(hydrate_dossier_row(row))
        return visible

    # ── write port ───────────────────────────────────────────────

    def find_existing_for_source(
        self, *, secret_order_id: Optional[int], directive_id: int,
        pending_action_id: int, action: str, region_id: str,
    ) -> Optional[int]:
        """Idempotency key lookup: only real (>0) source ids key a dossier row."""
        if secret_order_id is not None:
            sql, params = "secret_order_id = ?", (int(secret_order_id),)
        elif int(directive_id or 0) > 0:
            sql, params = (
                "directive_id = ? AND region_id = ?",
                (int(directive_id), region_id),
            )
        elif int(pending_action_id or 0) > 0:
            # #1837：同 pending 可挂多 action_type（组合拨帑+任免）；幂等按三类键查。
            sql, params = (
                "pending_action_id = ? AND region_id = ? AND action_type = ?",
                (int(pending_action_id), region_id, action),
            )
        else:
            return None
        existing = self._conn.execute(
            f"SELECT id FROM decree_dossiers WHERE {sql}", params,
        ).fetchone()
        return None if existing is None else int(existing["id"])

    def insert_row(
        self, *, action: str, target_kind: str, target_id: str,
        executor_kind: str, executor_id: str, source_chat_turn_id: int,
        pending_action_id: int, directive_id: int,
        secret_order_id: Optional[int], region_id: str, decree_text: str,
        payload: Mapping[str, object], status: str, due_turn: int,
        extension: Mapping[str, object], participant_roster: object,
        office_archive_keys: list[str], turn: int, year: int, period: int,
        affair_id: int,
    ) -> int:
        """The single INSERT that brings a dossier into being."""
        cur = self._conn.execute(
            """
            INSERT INTO decree_dossiers
                (action_type,target_kind,target_id,executor_kind,executor_id,
                 source_chat_turn_id,pending_action_id,
                 directive_id,secret_order_id,region_id,decree_text,payload_json,status,due_turn,
                 extension_json,participant_roster,office_archive_keys,
                 created_turn,created_year,created_period,affair_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                action, target_kind, target_id,
                executor_kind, executor_id,
                int(source_chat_turn_id), int(pending_action_id),
                None if int(directive_id) <= 0 else int(directive_id),
                None if secret_order_id is None else int(secret_order_id),
                region_id,
                decree_text, json.dumps(dict(payload), ensure_ascii=False), status,
                max(0, int(due_turn)),
                json.dumps(dict(extension), ensure_ascii=False),
                json.dumps(participant_roster, ensure_ascii=False),
                json.dumps(sorted(office_archive_keys), ensure_ascii=False),
                int(turn), int(year), int(period),
                int(affair_id),
            ),
        )
        return int(cur.lastrowid)

    def set_stigma(
        self, dossier_id: int, stigma: list[dict[str, object]], *, commit: bool = True,
    ) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET stigma_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(stigma, ensure_ascii=False), int(dossier_id)),
        )
        self._commit(commit)

    def set_participants_and_archive(
        self, dossier_id: int, roster: object, archive_keys: list[str], *,
        commit: bool = True,
    ) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET participant_roster=?,office_archive_keys=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                json.dumps(roster, ensure_ascii=False),
                json.dumps(sorted(archive_keys), ensure_ascii=False),
                int(dossier_id),
            ),
        )
        self._commit(commit)

    # ── endorsements ──────────────────────────────────────────────

    def add_endorsement(
        self, dossier_id: int, *, form: str, source_chat_turn_id: int = 0,
        decision_key: str = "", endorser_id: str = "", imperial: bool = False,
        commit: bool = True,
    ) -> int:
        """Persist one already-spoken ADR 0070 endorsement; never re-judge willingness."""
        did, cid, dkey, kind, person, is_imperial = self._validate_endorsement(
            dossier_id, form=form, source_chat_turn_id=source_chat_turn_id,
            decision_key=decision_key, endorser_id=endorser_id, imperial=imperial,
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO decree_dossier_endorsements "
            "(dossier_id,form,endorser_id,imperial,source_chat_turn_id,decision_key) "
            "VALUES (?,?,?,?,?,?)",
            (did, kind, person, int(is_imperial), cid, dkey),
        )
        row = self._conn.execute(
            "SELECT id FROM decree_dossier_endorsements WHERE dossier_id=? AND form=? "
            "AND endorser_id=? AND imperial=? AND source_chat_turn_id=? AND decision_key=?",
            (did, kind, person, int(is_imperial), cid, dkey),
        ).fetchone()
        if commit:
            self._commit(True)
        return int(row["id"])

    def _validate_endorsement(
        self, dossier_id: object, *, form: object,
        source_chat_turn_id: object = 0, decision_key: object = "",
        endorser_id: object = "", imperial: object = False,
    ) -> tuple[int, int, str, str, str, bool]:
        """#658：provenance 恰取 source_chat_turn_id>0 或 decision_key 非空之一。"""
        if isinstance(dossier_id, bool) or not isinstance(dossier_id, int):
            raise ValueError("背书案卷 id 须为整数")
        if isinstance(source_chat_turn_id, bool) or not isinstance(source_chat_turn_id, int):
            raise ValueError("背书来源对话轮 id 须为整数")
        if not isinstance(decision_key, str):
            raise ValueError("背书 decision_key 须为字符串")
        if not isinstance(form, str) or not isinstance(endorser_id, str):
            raise ValueError("背书形式与人物须为字符串")
        did, cid = dossier_id, int(source_chat_turn_id)
        dkey = decision_key.strip()
        kind, person = form.strip(), endorser_id.strip()
        if not isinstance(imperial, bool):
            raise ValueError("御笔标记须为布尔")
        is_imperial = imperial
        # 恰一种 provenance：召对 chat_turn XOR 批红/下旨 decision_key。
        has_turn = cid > 0
        has_key = bool(dkey)
        if has_turn == has_key:
            raise ValueError("背书 provenance 须恰为 source_chat_turn_id 或 decision_key 之一")
        if self._conn.execute(
            "SELECT 1 FROM decree_dossiers WHERE id=?", (did,)
        ).fetchone() is None:
            raise ValueError("背书所指案卷不存在")
        if has_turn:
            if self._conn.execute(
                "SELECT 1 FROM chat_turns WHERE id=?", (cid,)
            ).fetchone() is None:
                raise ValueError("背书来源对话轮不存在")
        if kind not in {"会签", "当面站台", "御笔手敕"}:
            raise ValueError("背书形式非法")
        if kind == "御笔手敕":
            if not is_imperial or person:
                raise ValueError("御笔手敕必须使用御笔标记且不得具名大臣")
        else:
            if is_imperial or not person:
                raise ValueError("会签/当面站台必须具名背书人")
            if self._conn.execute(
                "SELECT 1 FROM characters WHERE name=?", (person,)
            ).fetchone() is None:
                raise ValueError("背书人物不存在")
        return did, cid, dkey, kind, person, is_imperial

    def set_promulgation(
        self, dossier_id: int, *, status: str, promulgation: str,
        rescript_pending: int, blocked_layer: str, reason: str,
        legal_reason_code: str, held_turn: int, turn: int,
    ) -> None:
        """Write the promulgation/批红 combination state onto the row."""
        self._conn.execute(
            """
            UPDATE decree_dossiers SET
                status=?,promulgation_decision=?,rescript_pending=?,
                promulgation_blocked_layer=?,promulgation_reason=?,
                legal_reason_code=?,held_turn=?,updated_at=CURRENT_TIMESTAMP,
                closed_turn=CASE WHEN ?=\'closed\' THEN ? ELSE closed_turn END,
                closed_at=CASE WHEN ?=\'closed\' THEN CURRENT_TIMESTAMP ELSE closed_at END
            WHERE id=?
            """,
            (
                status, promulgation, rescript_pending, blocked_layer, reason,
                legal_reason_code, held_turn,
                status, turn, status, int(dossier_id),
            ),
        )

    def insert_decision(
        self, dossier_id: int, turn: int, *, decision: str, blocked_layer: str,
        rescript_action: str, reason: str, legal_reason_code: str,
        primary_opponents_json: str, gatekeeper_id: Optional[str],
        criteria_snapshot_json: str,
    ) -> None:
        """Append one row to the append-only verdict history."""
        self._conn.execute(
            """
            INSERT INTO decree_dossier_decisions
                (dossier_id,turn,decision,blocked_layer,rescript_action,reason,
                 legal_reason_code,primary_opponents_json,gatekeeper_id,
                 criteria_snapshot_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(dossier_id), int(turn), decision, blocked_layer,
                rescript_action, reason, legal_reason_code,
                primary_opponents_json, gatekeeper_id, criteria_snapshot_json,
            ),
        )

    def set_execution(
        self, dossier_id: int, *, outcome: str, note: str, turn: int,
    ) -> None:
        self._conn.execute(
            """
            UPDATE decree_dossiers
            SET execution_outcome=?, execution_note=?, closed_turn=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (outcome, str(note or ""), 0 if outcome == "executing" else int(turn),
             int(dossier_id)),
        )

    def set_interruption_reason_if_empty(self, dossier_id: int, reason: str) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET interruption_reason="
            "CASE WHEN interruption_reason='' THEN ? ELSE interruption_reason END "
            "WHERE id=?",
            (reason, int(dossier_id)),
        )

    def force_close(self, dossier_id: int, *, turn: int, reason: str) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET status='closed',closed_turn=?,"
            "interruption_reason=?,closed_at=CURRENT_TIMESTAMP WHERE id=?",
            (int(turn), reason, int(dossier_id)),
        )

    def merge_execution_note(self, dossier_id: int, merged: str, *, commit: bool = True) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET execution_note=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (merged, int(dossier_id)),
        )
        if commit:
            self._commit(True)

    def set_raw_payload(self, dossier_id: int, payload: Mapping[str, object]) -> None:
        """Payload write with no existence probe (idempotent backfill / push-bind path)."""
        self._conn.execute(
            "UPDATE decree_dossiers SET payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(dict(payload), ensure_ascii=False), int(dossier_id)),
        )

    def proposed_appointment_rows(self) -> list[Any]:
        return self._conn.execute(
            "SELECT id,target_id,payload_json FROM decree_dossiers "
            "WHERE status='proposed' AND action_type='appointment'"
        ).fetchall()

    def ids_for_secret_order(self, secret_order_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM decree_dossiers WHERE secret_order_id=? ORDER BY region_id, id",
            (int(secret_order_id),),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def first_id_by_region(
        self, *, directive_id: int = 0, pending_action_id: int = 0,
    ) -> dict[str, int]:
        """Composite-key 查补：first existing id per region for one source key."""
        if int(directive_id or 0) > 0:
            sql, params = "directive_id=?", (int(directive_id),)
        else:
            sql, params = "pending_action_id=?", (int(pending_action_id),)
        rows = self._conn.execute(
            f"SELECT id, region_id FROM decree_dossiers WHERE {sql} ORDER BY region_id, id",
            params,
        ).fetchall()
        out: dict[str, int] = {}
        for row in rows:
            key = str(row["region_id"] or "")
            if key not in out:
                out[key] = int(row["id"])
        return out

    def bound_to_directive(self, dossier_id: int, directive_id: int) -> Optional[int]:
        row = self._conn.execute(
            "SELECT id FROM decree_dossiers WHERE id=? AND directive_id=?",
            (int(dossier_id), int(directive_id)),
        ).fetchone()
        return None if row is None else int(row["id"])

    def bind_directive(self, dossier_id: int, directive_id: int) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET directive_id=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND (directive_id IS NULL OR directive_id=0 OR directive_id=?)",
            (int(directive_id), int(dossier_id), int(directive_id)),
        )

    def bind_pending_action(self, dossier_id: int, pending_action_id: int) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET pending_action_id=? "
            "WHERE directive_id=? AND (pending_action_id IS NULL "
            "OR pending_action_id=0 OR pending_action_id=?)",
            (int(pending_action_id), int(dossier_id), int(pending_action_id)),
        )

    def open_by_executor(self, character_name: str) -> list[Any]:
        return self._conn.execute(
            """
            SELECT id,secret_order_id,status FROM decree_dossiers
            WHERE executor_kind='character' AND executor_id=?
              AND status IN ('promulgated','executing')
            ORDER BY id
            """,
            (str(character_name),),
        ).fetchall()

    def in_transit_grants(self) -> list[Any]:
        """executing 且仍在途的拨帑案卷（成案不足额已 failed+close 的不在此列）。"""
        return self._conn.execute(
            """
            SELECT * FROM decree_dossiers
            WHERE status='executing' AND action_type='grant_allocation'
            """
        ).fetchall()

    def active_effect_facts(self) -> list[Any]:
        return self._conn.execute(
            """
            SELECT id, decree_text, execution_outcome, executor_id,
                   executor_kind, participant_roster, status
            FROM decree_dossiers
            WHERE status IN ('promulgated', 'executing')
               OR (status='closed' AND execution_outcome='transformed')
            ORDER BY id
            """
        ).fetchall()

    def closed_outcome_rows_before(self, turn: int) -> list[Any]:
        return self._conn.execute(
            """
            SELECT id, execution_outcome, closed_turn, status
            FROM decree_dossiers
            WHERE execution_outcome IN ('failed', 'transformed')
              AND closed_turn > 0
              AND closed_turn < ?
            ORDER BY id
            """,
            (int(turn),),
        ).fetchall()

    def next_id(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(id),0)+1 FROM decree_dossiers"
        ).fetchone()
        return int(row[0] if row else 1)

    def payload_of(self, dossier_id: int) -> str:
        row = self._conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (int(dossier_id),)
        ).fetchone()
        return str(row["payload_json"] or "{}") if row is not None else "{}"

    def executor_payload_of(self, dossier_id: int) -> tuple[str, str]:
        row = self._conn.execute(
            "SELECT executor_id, payload_json FROM decree_dossiers WHERE id=?",
            (int(dossier_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        return str(row["executor_id"] or ""), str(row["payload_json"] or "{}")

    def payload_by_pending_action(self, pending_action_id: int) -> str:
        row = self._conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE pending_action_id=?",
            (int(pending_action_id),),
        ).fetchone()
        return str(row["payload_json"] or "{}") if row is not None else "{}"

    def all_ids(self) -> list[int]:
        return [
            int(r["id"]) for r in
            self._conn.execute("SELECT id FROM decree_dossiers ORDER BY id").fetchall()
        ]

    def all_payloads(self) -> list[tuple[int, str]]:
        return [
            (int(r["id"]), str(r["payload_json"] or "{}")) for r in
            self._conn.execute(
                "SELECT id, payload_json FROM decree_dossiers ORDER BY id"
            ).fetchall()
        ]

    def active_secret_order_dossiers(self) -> list[Any]:
        return self._conn.execute(
            """
            SELECT d.* FROM decree_dossiers d
            JOIN secret_orders s ON s.id=d.secret_order_id
            WHERE s.status='active'
              AND d.status IN ('promulgated','executing')
            ORDER BY d.id
            """
        ).fetchall()

    def supervision_link_rows(self) -> list[Any]:
        return self._conn.execute(
            """
            SELECT l.source_dossier_id, l.target_dossier_id, l.relation_type,
                   s.status AS source_status, t.status AS target_status
            FROM decree_dossier_links l
            JOIN decree_dossiers s ON s.id = l.source_dossier_id
            JOIN decree_dossiers t ON t.id = l.target_dossier_id
            ORDER BY l.id
            """
        ).fetchall()

    def reconciliation_loss_rows(self, turn: int) -> list[Any]:
        return self._conn.execute(
            """
            SELECT r.dossier_id, r.loss_amount, d.action_type
            FROM decree_dossier_reconciliations r
            JOIN decree_dossiers d ON d.id = r.dossier_id
            WHERE r.turn = ? AND r.loss_amount > 0
            ORDER BY r.id
            """,
            (int(turn),),
        ).fetchall()

    def participant_row(self, dossier_id: int) -> Any:
        return self._conn.execute(
            "SELECT participant_roster,action_type,decree_text "
            "FROM decree_dossiers WHERE id=?",
            (int(dossier_id),),
        ).fetchone()

    def archive_keys_row(self, dossier_id: int) -> Any:
        return self._conn.execute(
            "SELECT office_archive_keys FROM decree_dossiers WHERE id=?",
            (int(dossier_id),),
        ).fetchone()

    def referenceable_rows(self, current_turn: int) -> list[Any]:
        return self._conn.execute(
            """SELECT d.*,
                      s.title AS secret_title,
                      EXISTS(
                          SELECT 1 FROM decree_dossier_decisions h
                          WHERE h.dossier_id=d.id
                            AND h.rescript_action='force_promulgated'
                      ) AS was_force_promulgated
               FROM decree_dossiers d
               LEFT JOIN secret_orders s ON s.id=d.secret_order_id
               WHERE d.created_turn <= ?
               ORDER BY d.id DESC""",
            (int(current_turn),),
        ).fetchall()

    def force_promulgate(self, dossier_id: int) -> None:
        self._conn.execute(
            "UPDATE decree_dossiers SET status='promulgated',rescript_pending=0,"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (int(dossier_id),),
        )

    def secret_order_for_pending(self, pending_action_id: int) -> Any:
        return self._conn.execute(
            "SELECT secret_order_id FROM decree_dossiers "
            "WHERE pending_action_id=? AND secret_order_id IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (int(pending_action_id),),
        ).fetchone()

    def dossier_count_created_turn(self, turn: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM decree_dossiers WHERE created_turn=?",
            (int(turn),),
        ).fetchone()
        return 0 if row is None else int(row["n"] or 0)

    # ── satellite fact tables ─────────────────────────────────────

    def reconciliations(self, dossier_id: int) -> list[dict[str, object]]:
        """被护案卷侧对账真源读缝（逐路×回合，restore 同源）。"""
        rows = self._conn.execute(
            """
            SELECT * FROM decree_dossier_reconciliations
            WHERE dossier_id=? ORDER BY turn, id
            """,
            (int(dossier_id),),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "dossier_id": int(row["dossier_id"]),
                "turn": int(row["turn"]),
                "ordered_amount": int(row["ordered_amount"]),
                "arrived_amount": int(row["arrived_amount"]),
                "loss_amount": int(row["loss_amount"]),
                "escorted": bool(row["escorted"]),
                "escort_source_dossier_id": (
                    int(row["escort_source_dossier_id"])
                    if row["escort_source_dossier_id"] is not None else None
                ),
                "relation_type": str(row["relation_type"] or ""),
                "note": str(row["note"] or ""),
            }
            for row in rows
        ]

    def has_supervision_presence(self, dossier_id: int, turn: int) -> bool:
        """本 turn 该案卷是否有稽核在场（空子暴露统一在场门）。"""
        row = self._conn.execute(
            """
            SELECT 1 FROM dossier_supervision_presence
            WHERE dossier_id=? AND turn=? AND present=1 LIMIT 1
            """,
            (int(dossier_id), int(turn)),
        ).fetchone()
        return row is not None

    def record_actual_progress(
        self, dossier_id: int, turn: int, *, units: float, fidelity_state: str,
        floor_state: str, note: str = "", commit: bool = True,
    ) -> dict[str, object]:
        """#1504 实况轨月度进度（0073）。禁与 dossier_progress_json/sim_note 混写。"""
        did = int(dossier_id)
        origin = f"dossier:{did}"
        self._conn.execute(
            """
            INSERT INTO dossier_actual_progress
                (dossier_id, turn, units, fidelity_state, floor_state, note, origin_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dossier_id, turn) DO UPDATE SET
                units=excluded.units,
                fidelity_state=excluded.fidelity_state,
                floor_state=excluded.floor_state,
                note=excluded.note,
                origin_ref=excluded.origin_ref
            """,
            (
                did,
                int(turn),
                float(units),
                str(fidelity_state),
                str(floor_state),
                str(note or "")[:240],
                origin,
            ),
        )
        if commit and int(getattr(self._conn, "_atomic_depth", 0) or 0) == 0:
            self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM dossier_actual_progress WHERE dossier_id=? AND turn=?",
            (did, int(turn)),
        ).fetchone()
        return dict(row) if row is not None else {
            "dossier_id": did,
            "turn": int(turn),
            "units": float(units),
            "fidelity_state": str(fidelity_state),
            "floor_state": str(floor_state),
            "note": str(note or "")[:240],
            "origin_ref": origin,
        }

    def actual_progress(self, dossier_id: int) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM dossier_actual_progress WHERE dossier_id=? ORDER BY turn, id",
            (int(dossier_id),),
        ).fetchall()
        return [dict(r) for r in rows]

    def actual_progress_units(self, dossier_id: int) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS total FROM dossier_actual_progress "
            "WHERE dossier_id=?",
            (int(dossier_id),),
        ).fetchone()
        return float(row["total"] if row is not None else 0.0)

    def draft_directives_with_dossier(self, turn: int) -> list[dict[str, object]]:
        """Settlement projection: drafts whose dossier creation succeeded."""
        rows = self._conn.execute(
            """SELECT td.* FROM turn_directives td
               WHERE td.turn<=? AND td.status='draft'
                 AND EXISTS (SELECT 1 FROM decree_dossiers d WHERE d.directive_id=td.id)
               ORDER BY td.id""",
            (int(turn),),
        ).fetchall()
        return [dict(row) for row in rows]
