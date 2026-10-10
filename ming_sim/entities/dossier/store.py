"""Dossier records: the durable truth of one decree under adjudication (ADR 0151).

The dossier is the only writable representation of "this decree exists, who
carries it, and where it stands". Verdicts and effects are materialized by the
settlement side; this store owns the row, its status chain, and the projections
read off that row.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from ming_sim.applier import (
    StoredDocumentError,
    durable_int,
    load_stored_list,
    load_stored_object,
    load_stored_object_list,
    parse_engine_payload_json,
    safe_json_dumps,
    sanitize_sqlite_text,
)
from ming_sim.constants import DOSSIER_LINK_TYPES
from ming_sim.decree_vocabulary import DOSSIER_ACTION_TYPES, dossier_action_policy
from ming_sim.strict_types import strict_int
from ming_sim.participant_roster import load_participant_roster
from ming_sim.entities.character.store import CharacterStore

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

_DOSSIER_COLUMNS = frozenset({
    "id", "action_type", "target_kind", "target_id", "executor_kind", "executor_id",
    "source_chat_turn_id", "pending_action_id", "directive_id", "secret_order_id",
    "region_id", "decree_text", "payload_json", "status", "promulgation_decision",
    "promulgation_blocked_layer", "promulgation_reason", "rescript_pending",
    "held_turn", "legal_reason_code", "stigma_json", "extension_json",
    "participant_roster", "office_archive_keys", "due_turn", "execution_outcome",
    "execution_note", "closed_turn", "interruption_reason", "created_turn",
    "created_year", "created_period", "created_at", "updated_at", "closed_at",
    "affair_id",
})
_DECISION_COLUMNS = frozenset({
    "id", "dossier_id", "turn", "decision", "blocked_layer", "rescript_action",
    "reason", "legal_reason_code", "primary_opponents_json", "gatekeeper_id",
    "criteria_snapshot_json", "affected_parties_json", "midzhi_unpromulgatable",
    "created_at",
})
_PROGRESS_COLUMNS = frozenset({
    "id", "dossier_id", "turn", "progress_band", "memorial_text", "is_terminal",
    "origin", "created_at",
})
_PENDING_ACTION_COLUMNS = frozenset({
    "id", "turn", "kind", "action", "target_id", "minister_name", "payload_json",
    "status", "committed_directive_id", "night_id", "night_approved", "version",
    "source_chat_turn_id", "created_at",
})
_LINK_COLUMNS = frozenset({
    "id", "source_dossier_id", "target_dossier_id", "relation_type", "note", "created_at",
})
DOSSIER_REPORT_ORIGIN_MONTHLY = "dossier-report:monthly_errand"
DOSSIER_REPORT_ORIGIN_VERDICT = "dossier-report:execution_verdict"
DOSSIER_REPORT_ORIGIN_RUSH = "dossier-report:rush"
DOSSIER_REPORT_ORIGIN_REVIEW = "dossier-report:review_claim"
DOSSIER_EXECUTION_OUTCOMES = frozenset({
    "executing", "fulfilled", "degraded", "failed", "transformed",
})

# 事实表列白名单（ADR 0077 禁「钝化数值列」的 schema 契约；守门在 store 侧）。
DENUNCIATION_TABLE = "faction_denunciations"
DENUNCIATION_ALLOWED_COLS = frozenset({
    "id", "turn", "accuser_name", "accuser_faction",
    "subject_name", "subject_faction", "target_dossier_id",
    "origin", "payload_json", "memorial_text",
})
PRESENCE_TABLE = "dossier_supervision_presence"
EXPOSURE_TABLE = "dossier_loophole_exposures"
PRESENCE_ALLOWED_COLS = frozenset({
    "id", "dossier_id", "turn", "auditor_name", "audit_dossier_id",
    "relation_type", "present",
})
EXPOSURE_ALLOWED_COLS = frozenset({
    "id", "dossier_id", "turn", "action_type", "execution_form",
})
# 全库禁「钝化数值」列名片段（AC1）
FORBIDDEN_DULLING_COL_FRAGMENTS = (
    "dull", "dulling", "钝化", "陋规", "supervision_score", "dull_rate",
)

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
    ON decree_dossiers(executor_kind, executor_id, status);
-- ADR 0054：只存新案卷→旧案卷；关系本身无状态位。
CREATE TABLE IF NOT EXISTS decree_dossier_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_dossier_id INTEGER NOT NULL,
    target_dossier_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL
        CHECK(relation_type IN ('护卫','稽核','接应')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_dossier_id, target_dossier_id, relation_type),
    FOREIGN KEY(source_dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE,
    FOREIGN KEY(target_dossier_id) REFERENCES decree_dossiers(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_decree_dossier_links_target
    ON decree_dossier_links(target_dossier_id, id);
-- #567 / ADR 0054+0058：被护案卷侧机械对账（逐路×回合）；非 0058 进展容器。
CREATE TABLE IF NOT EXISTS decree_dossier_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    ordered_amount INTEGER NOT NULL,
    arrived_amount INTEGER NOT NULL,
    loss_amount INTEGER NOT NULL,
    escorted INTEGER NOT NULL DEFAULT 0 CHECK(escorted IN (0,1)),
    escort_source_dossier_id INTEGER,
    relation_type TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dossier_id, turn),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dossier_reconciliations_dossier
    ON decree_dossier_reconciliations(dossier_id, turn, id);
-- ADR 0070：担名与办事名单分立；条目只能指向落条目前已存在的案卷。
-- #658 later-wins：provenance 恰为 source_chat_turn_id>0 或 decision_key 非空之一。
-- chat_turn 删除走显式清理（见 rollback 路径），不靠 FK CASCADE 绑死批红路径。
CREATE TABLE IF NOT EXISTS decree_dossier_endorsements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    form TEXT NOT NULL CHECK(form IN ('会签','当面站台','御笔手敕')),
    endorser_id TEXT NOT NULL DEFAULT '',
    imperial INTEGER NOT NULL DEFAULT 0 CHECK(imperial IN (0,1)),
    source_chat_turn_id INTEGER NOT NULL DEFAULT 0,
    decision_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dossier_id, form, endorser_id, imperial, source_chat_turn_id, decision_key),
    CHECK (
        (source_chat_turn_id > 0 AND decision_key = '')
        OR (source_chat_turn_id = 0 AND decision_key != '')
    ),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dossier_endorsements_dossier
    ON decree_dossier_endorsements(dossier_id, id);
CREATE TABLE IF NOT EXISTS decree_dossier_link_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_dossier_id INTEGER NOT NULL,
    pending_action_id INTEGER,
    target_dossier_id INTEGER NOT NULL DEFAULT 0,
    relation_type TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dossier_link_rejections_source
    ON decree_dossier_link_rejections(source_dossier_id, id);
CREATE TABLE IF NOT EXISTS decree_dossier_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    decision TEXT NOT NULL,
    blocked_layer TEXT NOT NULL DEFAULT '',
    rescript_action TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    legal_reason_code TEXT NOT NULL DEFAULT '',
    primary_opponents_json TEXT NOT NULL DEFAULT '[]',
    gatekeeper_id TEXT,
    criteria_snapshot_json TEXT NOT NULL DEFAULT '{}',
    affected_parties_json TEXT NOT NULL DEFAULT '[]',
    midzhi_unpromulgatable INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_decree_dossier_decisions_dossier
    ON decree_dossier_decisions(dossier_id, id);
-- #619 / ADR 0073: general reported-progress rail for non-secret
-- execution-surface dossiers. Secret monthly rows stay on
-- secret_orders.dossier_progress_json (#566/#883); no shared table+flag.
CREATE TABLE IF NOT EXISTS dossier_reported_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    progress_band TEXT NOT NULL,
    memorial_text TEXT NOT NULL,
    is_terminal INTEGER NOT NULL DEFAULT 0 CHECK(is_terminal IN (0,1)),
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dossier_reported_progress_dossier
    ON dossier_reported_progress(dossier_id, turn, id);
-- #625 / ADR 0077: supervision fact bottom (no dulling numeric cols).
-- Presence: one row per (dossier_id, turn, auditor); consecutive months derived at read.
CREATE TABLE IF NOT EXISTS dossier_supervision_presence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    auditor_name TEXT NOT NULL,
    audit_dossier_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL
        CHECK(relation_type IN ('稽核')),
    present INTEGER NOT NULL DEFAULT 1 CHECK(present IN (0,1)),
    UNIQUE(dossier_id, turn, auditor_name),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE,
    FOREIGN KEY(audit_dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_supervision_presence_dossier
    ON dossier_supervision_presence(dossier_id, turn, id);
-- Loophole exposure: class key = action_type + execution_form (enums only).
CREATE TABLE IF NOT EXISTS dossier_loophole_exposures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    execution_form TEXT NOT NULL,
    UNIQUE(dossier_id, turn, action_type, execution_form),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_loophole_exposures_dossier
    ON dossier_loophole_exposures(dossier_id, turn, id);
-- #1504 / ADR 0073+0120: covert 实况进度容器（非 0058 奏报；origin 纪律可累加）。
CREATE TABLE IF NOT EXISTS dossier_actual_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    units REAL NOT NULL,
    fidelity_state TEXT NOT NULL,
    floor_state TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    origin_ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dossier_id, turn),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dossier_actual_progress_dossier
    ON dossier_actual_progress(dossier_id, turn, id);
-- #627 / ADR 0077 ID-12: faction denunciation entries (independent carrier).
-- Truth bottom lives in origin marks (#619 compose_report_origin); payload holds
-- fork exposure. Never write dossier_loophole_exposures from this path.
CREATE TABLE IF NOT EXISTS faction_denunciations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn INTEGER NOT NULL,
    accuser_name TEXT NOT NULL,
    accuser_faction TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    subject_faction TEXT NOT NULL,
    target_dossier_id INTEGER NOT NULL,
    origin TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    memorial_text TEXT NOT NULL,
    -- 去重键=检举人×案卷×真伪类（不含 turn）；由承接查询单源+LIMIT 1 执行。
    -- 升级再落要求同键多行，故不加 UNIQUE（含 turn 会撞同回合升级；去 turn 会堵一切升级）。
    FOREIGN KEY(target_dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_faction_denunciations_turn
    ON faction_denunciations(turn, id);
CREATE INDEX IF NOT EXISTS idx_faction_denunciations_target
    ON faction_denunciations(target_dossier_id, turn, id);
-- ADR 0056: existence of this append-only rail is the idempotency key;
-- stigma_json is deliberately not used as a cost guard.
CREATE TABLE IF NOT EXISTS decree_cost_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    cost_kind TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    delta INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    cost_identity TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dossier_id, cost_identity, cost_kind, target_kind, target_id),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_decree_cost_events_dossier
    ON decree_cost_events(dossier_id, id);
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


def hydrate_dossier_row(row: Any) -> dict[str, Any]:
    """One fail-loud hydration contract for every dossier read (ADR 0005).

    Columns come from ``SELECT *`` over a wide table, so the hydrated shape is
    genuinely dynamic; the typed contract is the fail-loud parsing below, not a
    closed key set.

    Existing-row field/member faults are StoredDocumentError (durable read seam),
    not product ValueError — callers that isolate LLM bad items must not wash them.
    """
    try:
        out: dict[str, Any] = dict(row)
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
        payload = load_stored_object(out.get("payload_json"), label="payload_json")
        out["payload"] = payload
        out["mode"] = normalize_dossier_mode(
            payload["mode"] if "mode" in payload else "ordinary"
        )
        stigma = load_stored_list(out.get("stigma_json"), label="stigma_json")
        out["stigma"] = stigma
        roster = load_participant_roster(out.get("participant_roster"))
        out["participant_roster"] = roster
        extension = load_stored_object(out.get("extension_json"), label="extension_json")
        signal = extension.get("execution_signal")
        if signal is not None and not isinstance(signal, dict):
            raise ValueError(f"案卷#{out['id']} execution_signal 非对象")
        out["execution_signal"] = signal
        return out
    except StoredDocumentError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        try:
            did = int(row["id"])  # type: ignore[index]
            label = f"案卷#{did}"
        except Exception:
            label = "案卷"
        raise StoredDocumentError(f"{label} 持久行损坏：{exc}") from exc


class DossierStore:
    """World-record home for dossiers. The row is the truth; views read it."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _owns(self) -> bool:
        """Snapshot before this method's first DML.

        SQLite opens an implicit transaction on UPDATE/INSERT, so reading
        in_transaction afterwards would skip every commit.
        """
        from ming_sim.applier import connection_owns_transaction

        return connection_owns_transaction(self._conn)

    def _commit(self, commit: bool, owns: bool) -> None:
        if commit and owns:
            self._conn.commit()

    def get(self, dossier_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE id=?", (int(dossier_id),)
        ).fetchone()
        return None if row is None else hydrate_dossier_row(row)

    def get_for_directive(self, directive_id: int) -> Optional[dict[str, Any]]:
        """存在性哨兵：确定序取首行（#654 fan-out 下 N 行时勿当唯一读面）。"""
        row = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE directive_id=? "
            "ORDER BY region_id, id LIMIT 1",
            (int(directive_id),),
        ).fetchone()
        return None if row is None else hydrate_dossier_row(row)

    def get_for_secret_order(self, secret_order_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE secret_order_id=?",
            (int(secret_order_id),),
        ).fetchone()
        return None if row is None else hydrate_dossier_row(row)

    def list_dossiers(
        self, *, status: Optional[str] = None, target_kind: Optional[str] = None,
        target_id: Optional[object] = None,
    ) -> list[dict[str, Any]]:
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
    ) -> Optional[dict[str, Any]]:
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
        # hydrate_dossier_row 是唯一解析口（payload 已解析并 fail-loud），不再二次解析。
        return hydrate_dossier_row(row)

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
        owns = self._owns()
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
            payload = load_stored_object(row["payload_json"], label="payload_json")
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
        self._commit(commit, owns)

    def mark_secret_order_in_progress(
        self, order_id: int, *, commit: bool = True,
    ) -> None:
        """任何首次实际办理入口共用：密令轴在办时，案卷轴幂等进入 executing。"""
        owns = self._owns()
        dossier = self.get_for_secret_order(order_id)
        if dossier is None:
            raise ValueError("密令进展缺少对应案卷")
        if dossier["status"] == "promulgated":
            self.transition(
                int(dossier["id"]), "executing", commit=False,
            )
        elif dossier["status"] != "executing":
            raise ValueError("在办密令的案卷不处于可执行状态")
        self._commit(commit, owns)

    def close(
        self, dossier_id: int, reason: str = "", *, commit: bool = True,
    ) -> None:
        owns = self._owns()
        row = self.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        if row["status"] == "proposed":
            raise ValueError("待判案卷不能绕过颁布格直接结案")
        # get() 已按 hydrate_dossier_row 解析并 fail-loud 校验过 payload，直接复用。
        immediate = not has_execution_surface(row["action_type"], row["payload"])
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
        self._commit(commit, owns)

    # ── payload / participants / links ────────────────────────────

    @staticmethod
    def _coerce_todo_payload_json(payload_json: object) -> str:
        """#624：引擎侧 payload_json 序列化；非法非空响亮拒绝，禁静默丢底。"""
        if payload_json is not None and not isinstance(payload_json, (str, dict)):
            raise ValueError(
                f"next_audience_todos.payload_json 类型非法：{type(payload_json).__name__}"
            )
        data = load_stored_object(payload_json, label="next_audience_todos.payload_json")
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _parse_todo_payload_json(raw: object) -> dict[str, object]:
        return parse_engine_payload_json(
            raw, surface="next_audience_todos.payload_json",
        )

    def insert_next_audience_todo(
        self,
        *,
        commitment_ref: int,
        stage_idx: int,
        due_turn: int,
        criterion_text: str = "",
        origin_context: str = "",
        status: str = "pending",
        entry_kind: str = "staged_commitment",
        created_turn: int = 0,
        payload_json: object = None,
        commit: bool = True,
    ) -> int:
        """#620 P2：次回合召对待办写端。UNIQUE(commitment_ref, stage_idx, entry_kind) 去重。

        #624：payload_json 引擎侧列（真伪底）；默认 '{}'。
        返回新建行 id；已存在则返回 0（幂等，不覆盖）。
        """
        owns = self._owns()
        payload_blob = self._coerce_todo_payload_json(payload_json)
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO next_audience_todos "
            "(commitment_ref, stage_idx, due_turn, criterion_text, origin_context, "
            "status, entry_kind, created_turn, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(commitment_ref),
                int(stage_idx),
                int(due_turn),
                sanitize_sqlite_text(str(criterion_text or "")),
                sanitize_sqlite_text(str(origin_context or "")),
                sanitize_sqlite_text(str(status or "pending") or "pending"),
                sanitize_sqlite_text(
                    str(entry_kind or "staged_commitment") or "staged_commitment"
                ),
                int(created_turn or 0),
                sanitize_sqlite_text(payload_blob),
            ),
        )
        self._commit(commit, owns)
        if cur.rowcount <= 0:
            return 0
        return int(cur.lastrowid)

    def list_next_audience_todos(
        self,
        *,
        status: str | None = None,
        commitment_ref: int | None = None,
    ) -> list[dict[str, object]]:
        """下一召对回合可读的待办条目（restore 只读 DB 接续）。"""
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status=?")
            params.append(str(status))
        if commitment_ref is not None:
            clauses.append("commitment_ref=?")
            params.append(int(commitment_ref))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            "SELECT id, commitment_ref, stage_idx, due_turn, criterion_text, origin_context, "
            "status, entry_kind, created_turn, payload_json FROM next_audience_todos "
            f"{where} ORDER BY due_turn, commitment_ref, stage_idx, id",
            tuple(params),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "commitment_ref": int(r["commitment_ref"]),
                "stage_idx": int(r["stage_idx"]),
                "due_turn": int(r["due_turn"]),
                "criterion_text": str(r["criterion_text"] or ""),
                "origin_context": str(r["origin_context"] or ""),
                "status": str(r["status"] or ""),
                "entry_kind": str(r["entry_kind"] or ""),
                "created_turn": int(r["created_turn"] or 0),
                "payload_json": self._parse_todo_payload_json(r["payload_json"]),
            }
            for r in rows
        ]

    def audience_todo(self, todo_id: int) -> Any:
        return self._conn.execute(
            "SELECT id, status, payload_json FROM next_audience_todos WHERE id=?", (todo_id,),
        ).fetchone()

    def mark_next_audience_todo_status(
        self,
        todo_id: int,
        status: str,
        *,
        payload_patch: object = None,
        commit: bool = True,
    ) -> bool:
        """#621 P3：待办消费单写口 pending→consumed/rolled。

        幂等：目标态已是 status 且无 payload_patch，或非 pending 源态 → False。
        payload_patch：可选 dict，并入既有 payload_json；允许 pending 原位落判决痕迹。
        commit=False 可入外层事务。
        """
        allowed = {"consumed", "rolled", "pending"}
        new_status = str(status or "").strip()
        if new_status not in allowed:
            raise ValueError(f"next_audience_todos status 非法：{new_status}")
        patch: dict[str, object] | None = None
        if payload_patch is not None:
            if not isinstance(payload_patch, dict):
                raise ValueError(
                    "next_audience_todos payload_patch 须为对象，得 "
                    f"{type(payload_patch).__name__}"
                )
            patch = dict(payload_patch)
        row = self.audience_todo(int(todo_id))
        if row is None:
            return False
        current = str(row["status"] or "")
        if current == new_status and patch is None:
            return False
        # pending 原位更新只用于在同一 durable todo 落 payload 事实；无 patch 不复活。
        if new_status == "pending" and current != "pending":
            return False
        if current != "pending":
            return False
        owns = self._owns()
        if patch is not None:
            existing = self._parse_todo_payload_json(row["payload_json"])
            merged = dict(existing)
            merged.update(patch)
            payload_blob = self._coerce_todo_payload_json(merged)
            cur = self._conn.execute(
                "UPDATE next_audience_todos SET status=?, payload_json=? "
                "WHERE id=? AND status='pending'",
                (new_status, sanitize_sqlite_text(payload_blob), int(todo_id)),
            )
        else:
            cur = self._conn.execute(
                "UPDATE next_audience_todos SET status=? "
                "WHERE id=? AND status='pending'",
                (new_status, int(todo_id)),
            )
        self._commit(commit, owns)
        return int(cur.rowcount or 0) > 0

    def set_audience_todo_origin(self, todo_id: int, origin: str) -> None:
        self._conn.execute(
            "UPDATE next_audience_todos SET origin_context=? WHERE id=?", (origin, todo_id),
        )

    def count_audience_todos(self, params: Any) -> Any:
        return self._conn.execute(
            "SELECT COUNT(*) AS c FROM next_audience_todos "
            "WHERE commitment_ref=? AND entry_kind=? AND status=?", params,
        ).fetchone()

    def urge_history(self, action: str, kind: str, target_id: int) -> Any:
        return self._conn.execute(
            "SELECT id, turn, kind, action, target_id, payload_json, status FROM pending_actions "
            "WHERE status='committed' AND action=? AND kind=? AND target_id=? ORDER BY turn, id",
            (action, kind, target_id),
        ).fetchall()

    def append_commitment_urge(self, params: Any) -> None:
        self._conn.execute(
            "INSERT INTO pending_actions (turn, kind, action, target_id, minister_name, payload_json, status) "
            "VALUES (?, ?, ?, ?, '', ?, 'committed')", params,
        )

    def exists(self, dossier_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM decree_dossiers WHERE id=?", (int(dossier_id),),
        ).fetchone() is not None

    def source_chat_turn_exists(self, chat_turn_id: int) -> bool:
        from ming_sim.entities.reign_state.store import ReignStateStore
        return ReignStateStore(self._conn).chat_turn_exists(int(chat_turn_id))

    def update_payload(
        self, dossier_id: int, payload: Mapping[str, object], *, commit: bool = True,
    ) -> None:
        """Replace payload_json for an existing dossier (deliberation_state 等 typed 字段)."""
        owns = self._owns()
        did = int(dossier_id)
        if not self.exists(did):
            raise KeyError(f"案卷不存在：{did}")
        if not isinstance(payload, Mapping):
            raise ValueError("案卷 payload 须为对象")
        self._conn.execute(
            "UPDATE decree_dossiers SET payload_json=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (json.dumps(dict(payload), ensure_ascii=False), did),
        )
        self._commit(commit, owns)

    def add_links(
        self, source_dossier_id: int, links: Iterable[Mapping[str, object]], *,
        commit: bool = True,
    ) -> None:
        """把确认后的新→旧案卷关联整批落账；任一坏引用则整批拒收并留痕。"""
        owns = self._owns()
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
            note = str(item.get("note") or "") if isinstance(item, dict) else ""
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
            self._commit(commit, owns)
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
        self._commit(commit, owns)

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
            item["primary_opponents"] = load_stored_list(
                item.pop("primary_opponents_json"), label="primary_opponents_json",
            )
            item["criteria_snapshot"] = load_stored_object(
                item.pop("criteria_snapshot_json"), label="criteria_snapshot_json",
            )
            item["affected_parties"] = load_stored_list(
                item.pop("affected_parties_json"), label="affected_parties_json",
            )
            item["midzhi_unpromulgatable"] = bool(
                item["midzhi_unpromulgatable"]
            )
            decisions.append(item)
        return decisions

    def list_for_simulation(self, turn: int) -> list[dict[str, Any]]:
        """本月新生/重判案卷及所有未结案执行中案卷。

        判决真源为 staged_declarations / decree_dossier_decisions；不另建第二批次表。
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
                int(turn), int(turn),
                int(turn), int(turn), int(turn),
            ),
        ).fetchall()
        visible = []
        for row in rows:
            if str(row["action_type"]) == "secret_order":
                # Admission-owned effects never run through the simulator again.
                continue
            # 单一解析口：hydrate 出 payload 后同一份结果既判策略又供下游，载荷只解一次。
            item = hydrate_dossier_row(row)
            policy = dossier_action_policy(item["action_type"], item["payload"])
            # An in-transit dossier remains visible as execution context until
            # its execution verdict closes it, however.
            if (
                policy["effect_owner"] != "immediate"
                or str(item["status"]) == "executing"
            ):
                visible.append(item)
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
        owns = self._owns()
        self._conn.execute(
            "UPDATE decree_dossiers SET stigma_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(stigma, ensure_ascii=False), int(dossier_id)),
        )
        self._commit(commit, owns)

    def append_midzhi_stigma(
        self, dossier_id: int, *, decision: str, turn: int, commit: bool = True,
    ) -> None:
        """Append one marker per dossier semantic midzhi event, regardless of replay turn."""
        owns = self._owns()
        marker_fields = {
            "rejected": ("predeclared", "rejected"),
            "promulgated": ("predeclared", "promulgated"),
            "force_promulgated": ("rescript", "force_promulgated"),
        }
        if decision not in marker_fields:
            raise ValueError(f"中旨 stigma 判决非法：{decision}")
        row = self.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        reason, source_action = marker_fields[decision]
        marker = {
            "kind": "midzhi", "reason": reason, "turn": int(turn),
            "source_action": source_action,
        }
        stigma = list(row["stigma"])
        event_key = (marker["kind"], marker["reason"])
        if not any(
            (item.get("kind"), item.get("reason")) == event_key
            for item in stigma if isinstance(item, dict)
        ):
            stigma.append(marker)
            self.set_stigma(int(dossier_id), stigma, commit=False)
        self._commit(commit, owns)

    def set_participants_and_archive(
        self, dossier_id: int, roster: object, archive_keys: list[str], *,
        commit: bool = True,
    ) -> None:
        owns = self._owns()
        self._conn.execute(
            "UPDATE decree_dossiers SET participant_roster=?,office_archive_keys=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                json.dumps(roster, ensure_ascii=False),
                json.dumps(sorted(archive_keys), ensure_ascii=False),
                int(dossier_id),
            ),
        )
        self._commit(commit, owns)

    # ── endorsements ──────────────────────────────────────────────

    def add_endorsement(
        self, dossier_id: int, *, form: str, source_chat_turn_id: int = 0,
        decision_key: str = "", endorser_id: str = "", imperial: bool = False,
        commit: bool = True,
    ) -> int:
        """Persist one already-spoken ADR 0070 endorsement; never re-judge willingness."""
        owns = self._owns()
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
        self._commit(commit, owns)
        return int(row["id"])

    def inherit_payload_endorsements(
        self, dossier_id: int, payload: Mapping[str, object], *, commit: bool = False,
    ) -> list[int]:
        """#1842：成案时把载荷 endorsements 继承到案卷（来源仍为声明轮）。"""
        if not isinstance(payload, Mapping):
            return []
        owns = self._owns()
        raw_items = load_stored_object_list(
            payload.get("endorsements"), label="endorsements",
        )
        if not raw_items:
            return []
        new_ids: list[int] = []
        for raw in raw_items:
            form = str(raw.get("form") or "").strip()
            endorser_id = str(raw.get("endorser_id") or "").strip()
            imperial = bool(raw.get("imperial", False))
            source_cid = int(raw.get("source_chat_turn_id") or 0)
            if form == "御笔手敕":
                imperial, endorser_id = True, ""
            if form not in {"会签", "当面站台", "御笔手敕"} or source_cid <= 0:
                continue
            eid = self.add_endorsement(
                int(dossier_id),
                form=form,
                endorser_id=endorser_id,
                imperial=imperial,
                source_chat_turn_id=source_cid,
                commit=False,
            )
            new_ids.append(int(eid))
        if new_ids:
            self._commit(commit, owns)
        return new_ids

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
        if not self.exists(did):
            raise ValueError("背书所指案卷不存在")
        if has_turn:
            if not self.source_chat_turn_exists(cid):
                raise ValueError("背书来源对话轮不存在")
        if kind not in {"会签", "当面站台", "御笔手敕"}:
            raise ValueError("背书形式非法")
        if kind == "御笔手敕":
            if not is_imperial or person:
                raise ValueError("御笔手敕必须使用御笔标记且不得具名大臣")
        else:
            if is_imperial or not person:
                raise ValueError("会签/当面站台必须具名背书人")
            if CharacterStore(self._conn).read_assert_characters_exist((person,)) is None:
                raise ValueError("背书人物不存在")
        return did, cid, dkey, kind, person, is_imperial

    def attach_pending_action_endorsement(
        self, action_id: int, entry: Mapping[str, object], *, commit: bool = True,
    ) -> None:
        """#1842：把本轮背书挂进暂存载荷 endorsements 列表（不造待背书表）。"""
        owns = self._owns()
        aid = int(action_id)
        row = self.pending_action_payload_status(aid)
        if row is None:
            raise KeyError(f"暂存动作不存在：{aid}")
        if str(row["status"] or "") != "pending":
            raise ValueError(f"暂存动作状态不可挂背书：{row['status']}")
        payload = load_stored_object(row["payload_json"], label="payload_json")
        form = str(entry.get("form") or "").strip()
        endorser_id = str(entry.get("endorser_id") or "").strip()
        imperial = bool(entry.get("imperial", False))
        source_cid = int(entry.get("source_chat_turn_id") or 0)
        # 暂存阶段尚无 dossier：只验形式/人物/来源轮（与成案背书同口径）。
        if form == "御笔手敕":
            imperial, endorser_id = True, ""
        if form not in {"会签", "当面站台", "御笔手敕"}:
            raise ValueError("背书形式非法")
        if form == "御笔手敕":
            if not imperial or endorser_id:
                raise ValueError("御笔手敕必须使用御笔标记且不得具名大臣")
        else:
            if imperial or not endorser_id:
                raise ValueError("会签/当面站台必须具名背书人")
            if CharacterStore(self._conn).read_assert_characters_exist((endorser_id,)) is None:
                raise ValueError("背书人物不存在")
        if source_cid <= 0:
            raise ValueError("背书来源对话轮 id 须为正整数")
        if not self.source_chat_turn_exists(source_cid):
            raise ValueError("背书来源对话轮不存在")
        items = load_stored_object_list(
            payload.get("endorsements"), label="endorsements",
        )
        # 同轮同形同人去重（INSERT OR IGNORE 同语义）。
        key = (form, endorser_id, imperial, source_cid)
        kept = []
        for raw in items:
            k = (
                str(raw.get("form") or "").strip(),
                str(raw.get("endorser_id") or "").strip(),
                bool(raw.get("imperial", False)),
                int(raw.get("source_chat_turn_id") or 0),
            )
            if k == key:
                continue
            kept.append(dict(raw))
        kept.append({
            "form": form, "endorser_id": endorser_id,
            "imperial": imperial, "source_chat_turn_id": source_cid,
        })
        payload["endorsements"] = kept
        self.set_pending_payload(
            aid, json.dumps(payload, ensure_ascii=False),
        )
        self._commit(commit, owns)

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

    def record_dossier_decision(
        self, dossier_id: int, decision: str, *, reason: str = "",
        blocked_layer: str = "", legal_reason_code: str = "",
        primary_opponents: Optional[list[dict[str, str]]] = None,
        gatekeeper_id: Optional[str] = None,
        criteria_snapshot: Optional[dict[str, object]] = None,
        commit: bool = True,
    ) -> None:
        """颁布/批红组合态。rejected 与 hold 永不成为主链 status。"""
        from ming_sim.entities.reign_state.store import ReignStateStore

        owns = self._owns()
        if str(legal_reason_code or "").strip():
            raise ValueError("legal_reason_code 仅供尚未落地的依律集写入路径")
        decision = str(decision or "").strip()
        if decision not in {"promulgated", "rejected", "hold", "withdrawn"}:
            raise ValueError(f"案卷判决非法：{decision}")
        blocked_layer = str(blocked_layer or "")
        if blocked_layer not in PROMULGATION_BLOCKED_LAYERS:
            raise ValueError(f"颁布关口非法：{blocked_layer}")
        row = self.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        slot_reason = str(reason or "")
        slot_legal_reason = str(legal_reason_code or "")
        if decision in {"hold", "withdrawn"}:
            if not blocked_layer:
                blocked_layer = str(row.get("promulgation_blocked_layer") or "")
            slot_reason = str(row.get("promulgation_reason") or "")
            slot_legal_reason = str(row.get("legal_reason_code") or "")
        turn_row = ReignStateStore(self._conn).read_current_settle_turn()
        current_turn = int(turn_row["turn"] if turn_row else 0)
        if (
            decision in {"promulgated", "rejected"}
            and int(row.get("held_turn") or 0) > 0
            and current_turn <= int(row["held_turn"])
        ):
            raise ValueError("留中案卷只可在下月重判")
        if row["status"] != "proposed":
            raise ValueError("只有 proposed 案卷可写颁布/批红判决")
        if decision == "promulgated":
            status, promulgation, pending = "promulgated", "promulgated", 0
        elif decision == "rejected":
            status, promulgation, pending = "proposed", "rejected", 1
        elif decision == "hold":
            if row["promulgation_decision"] != "rejected" or not row["rescript_pending"]:
                raise ValueError("留中只可承接打回＋批红待抉择组合态")
            status, promulgation, pending = "proposed", "rejected", 0
        else:
            if row["promulgation_decision"] != "rejected" or not row["rescript_pending"]:
                raise ValueError("收回只可承接打回＋批红待抉择组合态")
            status, promulgation, pending = "closed", "rejected", 0
        held_turn = (
            current_turn
            if decision == "hold" else int(row.get("held_turn") or 0)
        )
        self.set_promulgation(
            int(dossier_id), status=status, promulgation=promulgation,
            rescript_pending=pending, blocked_layer=blocked_layer,
            reason=slot_reason, legal_reason_code=slot_legal_reason,
            held_turn=held_turn, turn=current_turn,
        )
        self.insert_decision(
            int(dossier_id), current_turn,
            decision=promulgation if decision != "hold" else "rejected",
            blocked_layer=blocked_layer,
            rescript_action=decision if decision in {"hold", "withdrawn"} else "",
            reason=str(reason or ""),
            legal_reason_code=slot_legal_reason,
            primary_opponents_json=safe_json_dumps(primary_opponents or []),
            gatekeeper_id=(
                str(gatekeeper_id).strip() if gatekeeper_id is not None else None
            ),
            criteria_snapshot_json=safe_json_dumps(criteria_snapshot or {}),
        )
        self._commit(commit, owns)

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

    def record_execution(
        self, dossier_id: int, outcome: str, note: str, turn: int, *,
        close: bool = True, commit: bool = True,
    ) -> None:
        """完整执行格持久：校验 → 写 outcome → 可选结案 → 空子暴露。

        纯案卷记录；人事/财政效果物化不在此。
        """
        owns = self._owns()
        row = self.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        outcome = str(outcome or "").strip()
        if outcome not in DOSSIER_EXECUTION_OUTCOMES:
            raise ValueError(f"执行 outcome 非法：{outcome}")
        if outcome == "executing" and close:
            raise ValueError("executing 是非终态，必须以 close=False 记录")
        immediate = (
            row["status"] == "promulgated"
            and not has_execution_surface(row["action_type"], row["payload"])
        )
        if row["status"] != "executing" and not immediate:
            raise ValueError("执行格只能写入 executing 或无判定面已颁案卷")
        self.set_execution(
            int(dossier_id), outcome=outcome, note=str(note or ""), turn=int(turn),
        )
        if close:
            self.close(
                dossier_id,
                str(note or "") if outcome == "failed" else "",
                commit=False,
            )
        # #625：走样/变形/烂尾终值 → 空子暴露（与对账路统一：本 turn 稽核在场门）
        if outcome in {"degraded", "transformed", "failed"}:
            action_type = str(row.get("action_type") or "").strip()
            if (
                action_type in DOSSIER_ACTION_TYPES
                and self.has_supervision_presence(int(dossier_id), int(turn))
            ):
                self.record_loophole_exposure(
                    int(dossier_id), int(turn), action_type, outcome,
                    commit=False,
                )
        self._commit(commit, owns)

    def record_monthly_supervision_presence(
        self, turn: int, *, commit: bool = False,
    ) -> dict[str, object]:
        """月度在场扫描：稽核链 → presence 行；同 turn UNIQUE 幂等不双计。"""
        from ming_sim.supervision import (
            SUPERVISION_RELATION,
            resolve_dossier_owner_name,
        )

        owns = self._owns()
        turn_i = int(turn)
        presence_written = 0
        link_rows = self.audit_link_rows(SUPERVISION_RELATION)
        for link in link_rows:
            source_status = str(link["source_status"] or "")
            target_status = str(link["target_status"] or "")
            if source_status not in {"promulgated", "executing"}:
                continue
            if target_status not in {"promulgated", "executing"}:
                continue
            audit_dossier = self.get(int(link["source_dossier_id"]))
            if audit_dossier is None:
                continue
            auditor = resolve_dossier_owner_name(audit_dossier)
            if not auditor:
                continue
            self.upsert_presence(
                int(link["target_dossier_id"]), turn_i, auditor_name=auditor,
                audit_dossier_id=int(link["source_dossier_id"]),
                relation_type=SUPERVISION_RELATION,
            )
            presence_written += 1
        self._commit(commit, owns)
        return {"presence_written": presence_written, "turn": turn_i}

    def record_monthly_loophole_exposures_from_reconciliations(
        self, turn: int, *, commit: bool = False,
    ) -> dict[str, object]:
        """对账后暴露派生：本回合 loss>0 且该案卷当月稽核在场 → 暴露行。"""
        owns = self._owns()
        turn_i = int(turn)
        exposure_written = 0
        recon_rows = self.reconciliation_loss_rows(turn_i)
        for row in recon_rows:
            did = int(row["dossier_id"])
            if not self.has_supervision_presence(did, turn_i):
                continue
            action_type = (
                str(row["action_type"] or "grant_allocation").strip()
                or "grant_allocation"
            )
            if self.record_loophole_exposure(
                did, turn_i, action_type, "degraded", commit=False,
            ):
                exposure_written += 1
        self._commit(commit, owns)
        return {"exposure_written": exposure_written, "turn": turn_i}

    def is_pending_owned_by_turn(self, action_id: object, chat_turn_id: int) -> bool:
        """#1890：这道交办是不是「本源轮、且仍 pending」。"""
        try:
            aid = int(action_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        ctid = int(chat_turn_id or 0)
        if aid <= 0 or ctid <= 0:
            return False
        row = self.pending_source_status(aid)
        if row is None:
            return False
        return (
            int(row["source_chat_turn_id"] or 0) == ctid
            and str(row["status"] or "") == "pending"
        )


    def grant_escort_presence(
        self, dossier_id: int,
    ) -> tuple[bool, int | None, str]:
        """被护案卷侧查入链：护卫/稽核在场与否（0054 逐路独立）。"""
        escort_relations = frozenset({"护卫", "稽核"})
        for link in self.links(int(dossier_id), direction="incoming"):
            relation = str(link.get("relation_type") or "").strip()
            if relation in escort_relations:
                return True, int(link["source_dossier_id"]), relation
        return False, None, ""

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

    # ── satellite read seams ─────────────────────────────────────

    def pending_action_dossier_ids(
        self, pending_action_id: int, *, secret_only: bool = False,
    ) -> list[int]:
        sql = "SELECT id FROM decree_dossiers WHERE pending_action_id=?"
        if secret_only:
            sql += " AND secret_order_id IS NOT NULL"
        return [
            int(r["id"]) for r in self._conn.execute(sql + " ORDER BY id", (int(pending_action_id),)).fetchall()
        ]

    def has_incoming_audit_link(self, dossier_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM decree_dossier_links "
            "WHERE target_dossier_id=? AND relation_type='稽核' LIMIT 1",
            (int(dossier_id),),
        ).fetchone() is not None

    def rows_with_affair(self) -> list[Any]:
        return self._conn.execute(
            "SELECT affair_id, participant_roster FROM decree_dossiers WHERE affair_id != 0"
        ).fetchall()

    def reported_progress_rows(
        self, dossier_id: int, *, as_of_turn: Optional[int] = None,
    ) -> list[Any]:
        sql = (
            "SELECT id, dossier_id, turn, progress_band, memorial_text, "
            "is_terminal, origin FROM dossier_reported_progress WHERE dossier_id=?"
        )
        params: tuple = (int(dossier_id),)
        if as_of_turn is not None:
            sql += " AND turn<=?"
            params = (int(dossier_id), int(as_of_turn))
        return self._conn.execute(sql + " ORDER BY turn, id", params).fetchall()

    def presence_rows(
        self, dossier_id: int, *, as_of_turn: Optional[int] = None,
    ) -> list[dict[str, object]]:
        sql = (
            "SELECT id, dossier_id, turn, auditor_name, audit_dossier_id, "
            "relation_type, present FROM dossier_supervision_presence WHERE dossier_id=?"
        )
        params: tuple = (int(dossier_id),)
        if as_of_turn is not None:
            sql += " AND turn<=?"
            params = (int(dossier_id), int(as_of_turn))
        rows = self._conn.execute(sql + " ORDER BY turn, id", params).fetchall()
        return [
            {
                "id": int(r["id"]),
                "dossier_id": int(r["dossier_id"]),
                "turn": int(r["turn"]),
                "auditor_name": str(r["auditor_name"] or ""),
                "audit_dossier_id": int(r["audit_dossier_id"]),
                "relation_type": str(r["relation_type"] or ""),
                "present": bool(r["present"]),
            }
            for r in rows
        ]

    def exposure_rows(
        self, dossier_id: int, *, as_of_turn: Optional[int] = None,
    ) -> list[dict[str, object]]:
        sql = (
            "SELECT id, dossier_id, turn, action_type, execution_form "
            "FROM dossier_loophole_exposures WHERE dossier_id=?"
        )
        params: list[object] = [int(dossier_id)]
        if as_of_turn is not None:
            sql += " AND turn<=?"
            params.append(int(as_of_turn))
        rows = self._conn.execute(
            sql + " ORDER BY turn, id", tuple(params),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "dossier_id": int(r["dossier_id"]),
                "turn": int(r["turn"]),
                "action_type": str(r["action_type"] or ""),
                "execution_form": str(r["execution_form"] or ""),
            }
            for r in rows
        ]

    def directives_with_dossiers(self, turn: int) -> list[dict[str, object]]:
        """Draft directives whose dossier creation succeeded."""
        rows = self._conn.execute(
            """SELECT td.* FROM turn_directives td
               WHERE td.turn<=? AND td.status='draft'
                 AND EXISTS (SELECT 1 FROM decree_dossiers d WHERE d.directive_id=td.id)
               ORDER BY td.id""",
            (int(turn),),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_reconciliation(
        self, dossier_id: int, turn: int, *, ordered: int, arrived: int,
        escorted: bool, escort_source_dossier_id: Optional[int],
        relation_type: str, note: str,
    ) -> None:
        """One reconciliation row per (dossier, turn); re-run overwrites in place."""
        self._conn.execute(
            """
            INSERT INTO decree_dossier_reconciliations
                (dossier_id, turn, ordered_amount, arrived_amount, loss_amount,
                 escorted, escort_source_dossier_id, relation_type, note)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(dossier_id, turn) DO UPDATE SET
                ordered_amount=excluded.ordered_amount,
                arrived_amount=excluded.arrived_amount,
                loss_amount=excluded.loss_amount,
                escorted=excluded.escorted,
                escort_source_dossier_id=excluded.escort_source_dossier_id,
                relation_type=excluded.relation_type,
                note=excluded.note
            """,
            (
                int(dossier_id), int(turn), int(ordered), int(arrived),
                int(ordered) - int(arrived), 1 if escorted else 0,
                None if escort_source_dossier_id is None else int(escort_source_dossier_id),
                relation_type, note,
            ),
        )

    def has_reconciliation(self, dossier_id: int, turn: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM decree_dossier_reconciliations "
            "WHERE dossier_id=? AND turn=? LIMIT 1",
            (int(dossier_id), int(turn)),
        ).fetchone() is not None

    def upsert_presence(
        self, dossier_id: int, turn: int, *, auditor_name: str,
        audit_dossier_id: int, relation_type: str,
    ) -> None:
        """Idempotent per (dossier, turn, auditor); never double-counts a month."""
        self._conn.execute(
            """
            INSERT INTO dossier_supervision_presence
                (dossier_id, turn, auditor_name, audit_dossier_id,
                 relation_type, present)
            VALUES (?,?,?,?,?,1)
            ON CONFLICT(dossier_id, turn, auditor_name) DO UPDATE SET
                audit_dossier_id=excluded.audit_dossier_id,
                relation_type=excluded.relation_type,
                present=1
            """,
            (
                int(dossier_id), int(turn), auditor_name,
                int(audit_dossier_id), relation_type,
            ),
        )

    def record_loophole_exposure(
        self,
        dossier_id: int,
        turn: int,
        action_type: str,
        execution_form: str,
        *,
        commit: bool = True,
    ) -> bool:
        """逐次暴露一行；同 (dossier,turn,action_type,execution_form) 幂等。

        True when this call wrote the row (existence of the rail is the key).
        """
        owns = self._owns()
        form = str(execution_form or "").strip()
        if form not in DOSSIER_EXECUTION_OUTCOMES:
            raise ValueError(f"空子暴露执行格形态非法：{form!r}")
        atype = str(action_type or "").strip()
        if not atype:
            raise ValueError("空子暴露 action_type 不能为空")
        if atype not in DOSSIER_ACTION_TYPES:
            raise ValueError(f"空子暴露 action_type 非法：{atype!r}")
        if self.get(int(dossier_id)) is None:
            raise ValueError("案卷不存在")
        cur = self._conn.execute(
            """
            INSERT INTO dossier_loophole_exposures
                (dossier_id, turn, action_type, execution_form)
            VALUES (?,?,?,?)
            ON CONFLICT(dossier_id, turn, action_type, execution_form) DO NOTHING
            """,
            (int(dossier_id), int(turn), atype, form),
        )
        wrote = int(cur.rowcount or 0) > 0
        self._commit(commit, owns)
        return wrote

    def upsert_reported_progress(
        self, dossier_id: int, turn: int, *, band: str, text: str, origin: str,
        is_terminal: bool,
    ) -> int:
        """General reported-progress rail. Non-terminal rows upsert per turn."""
        existing = None
        if not is_terminal:
            existing = self._conn.execute(
                """
                SELECT id FROM dossier_reported_progress
                WHERE dossier_id=? AND turn=? AND is_terminal=0
                ORDER BY id DESC LIMIT 1
                """,
                (int(dossier_id), int(turn)),
            ).fetchone()
        if existing is not None:
            report_id = int(existing["id"])
            self._conn.execute(
                """
                UPDATE dossier_reported_progress
                SET progress_band=?, memorial_text=?, origin=?
                WHERE id=?
                """,
                (band, text, origin, report_id),
            )
            return report_id
        cur = self._conn.execute(
            """
            INSERT INTO dossier_reported_progress
                (dossier_id, turn, progress_band, memorial_text, is_terminal, origin)
            VALUES (?,?,?,?,?,?)
            """,
            (int(dossier_id), int(turn), band, text, 1 if is_terminal else 0, origin),
        )
        return int(cur.lastrowid)

    @staticmethod
    def normalize_report_origin(origin: object, *, is_terminal: bool = False) -> str:
        """Normalize reported-progress origin; empty defaults by terminal flag."""
        raw = str(origin or "").strip()
        if not raw:
            return (
                DOSSIER_REPORT_ORIGIN_VERDICT
                if is_terminal
                else DOSSIER_REPORT_ORIGIN_MONTHLY
            )
        prefix = DOSSIER_REPORT_ORIGIN_NS
        if not raw.startswith(prefix) or not raw[len(prefix):].strip():
            raise ValueError("奏报 origin 须带 dossier-report 命名空间前缀")
        return raw

    @classmethod
    def coerce_progress_row(
        cls, item: Mapping[str, object], *, dossier_id: int,
    ) -> dict[str, object]:
        """Assemble one durable progress member; corrupt rows are read-seam faults."""
        try:
            if not isinstance(item, Mapping):
                raise StoredDocumentError("dossier_progress 成员须为对象")
            is_terminal = bool(item.get("is_terminal"))
            origin = cls.normalize_report_origin(
                item.get("origin"), is_terminal=is_terminal,
            )
            raw_did = item.get("dossier_id")
            if raw_did is None or raw_did == "":
                resolved_did = int(dossier_id)
            else:
                resolved_did = durable_int(
                    raw_did, label="dossier_progress.dossier_id", blank=None,
                )
            return {
                "id": durable_int(
                    item["id"], label="dossier_progress.id", blank=None,
                ),
                "dossier_id": resolved_did,
                "turn": durable_int(
                    item["turn"], label="dossier_progress.turn", blank=None,
                ),
                "progress_band": str(item["progress_band"]),
                "memorial_text": str(item["memorial_text"]),
                "is_terminal": is_terminal,
                "origin": origin,
            }
        except StoredDocumentError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise StoredDocumentError(
                f"dossier_progress 损坏：{exc}",
            ) from exc

    def record_dossier_progress(
        self,
        dossier_id: int,
        turn: int,
        progress_band: str,
        memorial_text: str,
        *,
        is_terminal: bool = False,
        origin: str = "",
        commit: bool = True,
    ) -> int:
        """Append one reported-progress entry; write path splits by physical track.

        Secret-order dossiers stay on secret_orders.dossier_progress_json (#566),
        owned by CharacterKnowledgeStore. Non-secret execution-surface dossiers use
        dossier_reported_progress (#619). Reported rows never enter apply (ADR 0073).
        """
        from ming_sim.entities.character_knowledge.store import CharacterKnowledgeStore

        owns = self._owns()
        dossier = self.get(int(dossier_id))
        band = str(progress_band or "").strip()
        text = str(memorial_text or "")
        if dossier is None:
            raise ValueError("案卷不存在")
        # 终值旁路行只载定性 band，引擎不自造密奏（decree_vocabulary.terminal_report_facade）。
        if not band or (not text.strip() and not is_terminal):
            raise ValueError("进展档和密奏均不能为空")
        origin_norm = self.normalize_report_origin(
            origin, is_terminal=bool(is_terminal),
        )
        secret_order_id = dossier.get("secret_order_id")
        if secret_order_id:
            report_id = CharacterKnowledgeStore(self._conn).record_secret_dossier_progress(
                int(secret_order_id), int(dossier_id), int(turn), band, text,
                is_terminal=bool(is_terminal), origin=origin_norm,
            )
            self._commit(commit, owns)
            return report_id
        # get() already hydrated payload; do not re-parse or silent-fallback empty.
        if not has_execution_surface(dossier.get("action_type"), dossier["payload"]):
            raise ValueError("非执行面案卷不可挂奏报")
        report_id = self.upsert_reported_progress(
            int(dossier_id), int(turn), band=band, text=text, origin=origin_norm,
            is_terminal=bool(is_terminal),
        )
        self._commit(commit, owns)
        return report_id

    def list_dossier_progress(self, dossier_id: int) -> list[dict[str, object]]:
        """Unified read seam over secret private rail and general reported rail."""
        from ming_sim.entities.character_knowledge.store import CharacterKnowledgeStore

        dossier = self.get(int(dossier_id))
        if dossier is None:
            return []
        if dossier.get("secret_order_id"):
            return [
                self.coerce_progress_row(item, dossier_id=int(dossier_id))
                for item in CharacterKnowledgeStore(self._conn).list_secret_dossier_progress_items(
                    int(dossier["secret_order_id"]),
                )
            ]
        return [
            self.coerce_progress_row(dict(row), dossier_id=int(dossier_id))
            for row in self.reported_progress_rows(int(dossier_id))
        ]

    def record_cost_event(
        self, dossier_id: int, turn: int, cost_kind: str, target_kind: str,
        target_id: str, delta: int, reason: str, cost_identity: str,
    ) -> bool:
        """ADR 0056: the row's existence is the idempotency key."""
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO decree_cost_events
               (dossier_id,turn,cost_kind,target_kind,target_id,delta,reason,cost_identity)
               VALUES (?,?,?,?,?,?,?,?)""",
            (int(dossier_id), int(turn), cost_kind, target_kind, str(target_id),
             int(delta), str(reason), str(cost_identity)),
        )
        return int(cur.rowcount or 0) == 1

    def prohibition_dossiers(self, action_type: str, target_dossier_id: int) -> list[Any]:
        return self._conn.execute(
            """SELECT * FROM decree_dossiers
               WHERE action_type=? AND target_kind='dossier' AND target_id=?
                 AND status IN ('promulgated','closed')
               ORDER BY id""",
            (str(action_type), str(int(target_dossier_id))),
        ).fetchall()

    def army_pay_row(self, dossier_id: int) -> Any:
        return self._conn.execute(
            """SELECT d.target_id army_id,a.arrears,a.consecutive_pay_shortfall_months
               FROM decree_dossiers d JOIN armies a ON a.id=d.target_id
               WHERE d.id=? AND d.target_kind='army'""",
            (int(dossier_id),),
        ).fetchone()

    def rejection_this_turn(self, dossier_id: int, turn: int) -> Optional[tuple[int, str]]:
        row = self._conn.execute(
            "SELECT turn, rescript_action FROM decree_dossier_decisions "
            "WHERE dossier_id=? AND decision='rejected' ORDER BY id DESC LIMIT 1",
            (int(dossier_id),),
        ).fetchone()
        return None if row is None else (int(row["turn"] or 0), str(row["rescript_action"] or ""))

    def rescript_history_rows(self) -> list[Any]:
        """中旨/强颁 durable markers joined to their dossier payload mode."""
        return self._conn.execute(
            "SELECT d.dossier_id,d.turn,d.decision,d.rescript_action,x.payload_json "
            "FROM decree_dossier_decisions d JOIN decree_dossiers x ON x.id=d.dossier_id "
            "ORDER BY d.turn,d.dossier_id,d.id"
        ).fetchall()

    def transformed_rows_between(self, low_turn: int, high_turn: int) -> list[Any]:
        return self._conn.execute(
            "SELECT id,closed_turn,participant_roster,decree_text,execution_note,"
            "execution_outcome FROM decree_dossiers "
            "WHERE execution_outcome='transformed' AND closed_turn BETWEEN ? AND ? ORDER BY id",
            (max(0, int(low_turn)), int(high_turn)),
        ).fetchall()

    def grant_allocation_rows(self) -> list[Any]:
        return self._conn.execute(
            "SELECT id, status, target_kind, target_id, payload_json, "
            "execution_outcome, closed_turn FROM decree_dossiers "
            "WHERE action_type='grant_allocation' ORDER BY id"
        ).fetchall()

    def due_grant_rows(self, turn: int) -> list[Any]:
        return self._conn.execute(
            "SELECT id, decree_text, payload_json, due_turn, execution_outcome, status "
            "FROM decree_dossiers WHERE status='executing' "
            "AND action_type='grant_allocation' AND due_turn > 0 AND due_turn <= ? "
            "ORDER BY id",
            (int(turn),),
        ).fetchall()

    def committed_directive_candidates(self, night_id: int) -> list[Any]:
        return self._conn.execute(
            """SELECT td.id AS directive_id, td.actor, td.text, MIN(d.id) AS dossier_id
               FROM pending_actions pa
               JOIN turn_directives td ON td.id = pa.committed_directive_id
               JOIN decree_dossiers d ON d.pending_action_id = pa.id
               WHERE pa.night_id = ? AND pa.kind = 'directive'
                 AND pa.status = 'committed' AND pa.committed_directive_id > 0
               GROUP BY td.id, td.actor, td.text ORDER BY td.id""",
            (int(night_id),),
        ).fetchall()

    def secret_order_ids_for(self, dossier_ids: Iterable[int]) -> dict[int, int]:
        """Batch map dossier id -> its secret_order_id (0 when not a 密令案卷)."""
        ids = sorted({int(i) for i in dossier_ids if int(i) > 0})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, secret_order_id FROM decree_dossiers WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return {int(r["id"]): int(r["secret_order_id"] or 0) for r in rows}

    # ── 稽核链连接读（links × 两端案卷状态） ─────────────────────

    def audit_link_rows(self, relation_type: str) -> list[Any]:
        """稽核/护卫链两端案卷的状态，供在场扫描判定双方仍在执行面。"""
        return self._conn.execute(
            """
            SELECT l.source_dossier_id, l.target_dossier_id, l.relation_type,
                   s.status AS source_status, t.status AS target_status
            FROM decree_dossier_links l
            JOIN decree_dossiers s ON s.id = l.source_dossier_id
            JOIN decree_dossiers t ON t.id = l.target_dossier_id
            WHERE l.relation_type = ?
            ORDER BY l.id
            """,
            (str(relation_type),),
        ).fetchall()

    # ── 派系检举（ADR 0077 ID-12：独立载体，真伪在 origin mark） ────

    def denunciations(
        self, *, turn: Optional[int] = None,
        target_dossier_id: Optional[int] = None,
    ) -> list[Any]:
        clauses: list[str] = []
        params: list[object] = []
        if turn is not None:
            clauses.append("turn=?")
            params.append(int(turn))
        if target_dossier_id is not None:
            clauses.append("target_dossier_id=?")
            params.append(int(target_dossier_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""SELECT id, turn, accuser_name, accuser_faction, subject_name,
                       subject_faction, target_dossier_id, origin, payload_json,
                       memorial_text
                FROM {DENUNCIATION_TABLE} {where}
                ORDER BY turn, id""",
            tuple(params),
        ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            payload = load_stored_object(row["payload_json"], label="检举 payload_json")
            out.append({
                "id": int(row["id"]),
                "turn": int(row["turn"]),
                "accuser_name": str(row["accuser_name"] or ""),
                "accuser_faction": str(row["accuser_faction"] or ""),
                "subject_name": str(row["subject_name"] or ""),
                "subject_faction": str(row["subject_faction"] or ""),
                "target_dossier_id": int(row["target_dossier_id"]),
                "origin": str(row["origin"] or ""),
                "payload": payload,
                "memorial_text": str(row["memorial_text"] or ""),
            })
        return out

    def latest_denunciation_for(
        self, *, accuser_name: str, target_dossier_id: int, origin: str,
    ) -> Any:
        """去重键=检举人×案卷×真伪类（origin 含真伪 mark，不含 turn）。"""
        return self._conn.execute(
            f"""SELECT id, turn, payload_json FROM {DENUNCIATION_TABLE}
                WHERE accuser_name=? AND target_dossier_id=? AND origin=?
                ORDER BY id DESC LIMIT 1""",
            (str(accuser_name), int(target_dossier_id), str(origin)),
        ).fetchone()

    def insert_denunciation(
        self, *, turn: int, accuser_name: str, accuser_faction: str,
        subject_name: str, subject_faction: str, target_dossier_id: int,
        origin: str, payload: Mapping[str, object], memorial_text: str,
    ) -> int:
        cur = self._conn.execute(
            f"""INSERT INTO {DENUNCIATION_TABLE}
                    (turn, accuser_name, accuser_faction, subject_name,
                     subject_faction, target_dossier_id, origin,
                     payload_json, memorial_text)
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                int(turn), accuser_name, accuser_faction, subject_name,
                subject_faction, int(target_dossier_id), origin,
                json.dumps(dict(payload), ensure_ascii=False), memorial_text,
            ),
        )
        return int(cur.lastrowid)

    def denunciation_origins(self, target_dossier_id: int) -> list[str]:
        return [
            str(r["origin"]) for r in self._conn.execute(
                f"SELECT origin FROM {DENUNCIATION_TABLE} WHERE target_dossier_id=?",
                (int(target_dossier_id),),
            ).fetchall()
        ]

    # ── affair pointer seam (ADR 0154：事务指针由 AffairStore 编排，列读写在此) ──

    def affair_id_of(self, dossier_id: int) -> int:
        row = self._conn.execute(
            "SELECT affair_id FROM decree_dossiers WHERE id=?", (int(dossier_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        return int(row["affair_id"] or 0)

    def snapshot_rows(self, table: str) -> Any:
        sql = {
            "decree_dossiers": "SELECT * FROM decree_dossiers",
            "decree_dossier_decisions": "SELECT * FROM decree_dossier_decisions",
            "dossier_reported_progress": "SELECT * FROM dossier_reported_progress",
            "pending_actions": "SELECT * FROM pending_actions",
            "decree_dossier_links": "SELECT * FROM decree_dossier_links",
        }[table]
        return self._conn.execute(sql).fetchall()

    def set_affair_id_if_unbound(self, dossier_id: int, affair_id: int) -> int:
        from ming_sim.entities.column_write import bind_affair_once

        return bind_affair_once(self._conn, "decree_dossiers", int(dossier_id), affair_id)

    def rows_for_affair(self, affair_id: int) -> list[Any]:
        return self._conn.execute(
            "SELECT id, action_type, affair_id FROM decree_dossiers "
            "WHERE affair_id=? ORDER BY id",
            (int(affair_id),),
        ).fetchall()

    def cost_events(self, dossier_id: int) -> list[Any]:
        return self._conn.execute(
            "SELECT * FROM decree_cost_events WHERE dossier_id=? ORDER BY id",
            (int(dossier_id),),
        ).fetchall()

    def recent_reported_progress(self) -> list[Any]:
        return self._conn.execute(
            "SELECT id, turn, memorial_text, dossier_id FROM dossier_reported_progress "
            "ORDER BY turn DESC, id DESC"
        ).fetchall()

    def has_override_party_cost(self, dossier_id: int) -> bool:
        """Any reaction party cost already booked for this dossier's override."""
        return self._conn.execute(
            "SELECT 1 FROM decree_cost_events "
            "WHERE dossier_id=? AND cost_kind='satisfaction' AND cost_identity='override' "
            "LIMIT 1",
            (int(dossier_id),),
        ).fetchone() is not None

    def set_latest_decision_parties(
        self, dossier_id: int, affected_parties_json: str, midzhi_unpromulgatable: int,
    ) -> None:
        self._conn.execute(
            """UPDATE decree_dossier_decisions
               SET affected_parties_json=?, midzhi_unpromulgatable=?
               WHERE id=(SELECT MAX(id) FROM decree_dossier_decisions WHERE dossier_id=?)""",
            (affected_parties_json, int(midzhi_unpromulgatable), int(dossier_id)),
        )

    def latest_judge_parties_json(self, dossier_id: int, turn: int) -> Optional[str]:
        row = self._conn.execute(
            """SELECT affected_parties_json FROM decree_dossier_decisions
               WHERE dossier_id=? AND turn=? AND rescript_action=''
               ORDER BY id DESC LIMIT 1""",
            (int(dossier_id), int(turn)),
        ).fetchone()
        return None if row is None else str(row["affected_parties_json"] or "")

    def delete_endorsements_for_chat_turn(self, source_chat_turn_id: int) -> None:
        """#506 rollback: endorsements derive from a spoken turn, so undo it too."""
        self._conn.execute(
            "DELETE FROM decree_dossier_endorsements WHERE source_chat_turn_id = ?",
            (int(source_chat_turn_id),),
        )

    def record_actual_progress(
        self, dossier_id: int, turn: int, *, units: float, fidelity_state: str,
        floor_state: str, note: str = "", commit: bool = True,
    ) -> dict[str, object]:
        """#1504 实况轨月度进度（0073）。禁与 dossier_progress_json/sim_note 混写。"""
        owns = self._owns()
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
                str(note or ""),
                origin,
            ),
        )
        self._commit(commit, owns)
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
            "note": str(note or ""),
            "origin_ref": origin,
        }

    def restore_row(self, row: Mapping[str, object]) -> None:
        from ming_sim.entities.column_write import upsert_by_pk
        upsert_by_pk(
            self._conn, "decree_dossiers", row, pk="id",
            allowed=_DOSSIER_COLUMNS, what="decree_dossiers",
        )

    def restore_decision(self, row: Mapping[str, object]) -> None:
        from ming_sim.entities.column_write import upsert_by_pk
        upsert_by_pk(
            self._conn, "decree_dossier_decisions", row, pk="id",
            allowed=_DECISION_COLUMNS, what="decree_dossier_decisions",
        )

    def restore_reported_progress(self, row: Mapping[str, object]) -> None:
        from ming_sim.entities.column_write import upsert_by_pk
        upsert_by_pk(
            self._conn, "dossier_reported_progress", row, pk="id",
            allowed=_PROGRESS_COLUMNS, what="dossier_reported_progress",
        )

    def restore_pending_action(self, row: Mapping[str, object]) -> None:
        from ming_sim.entities.column_write import upsert_by_pk
        upsert_by_pk(
            self._conn, "pending_actions", row, pk="id",
            allowed=_PENDING_ACTION_COLUMNS, what="pending_actions",
        )

    def restore_link(self, row: Mapping[str, object]) -> None:
        from ming_sim.entities.column_write import upsert_by_pk
        upsert_by_pk(
            self._conn, "decree_dossier_links", row, pk="id",
            allowed=_LINK_COLUMNS, what="decree_dossier_links",
        )

    def delete_dossier(self, dossier_id: object) -> None:
        self._conn.execute("DELETE FROM decree_dossiers WHERE id=?", (dossier_id,))

    def delete_decision(self, decision_id: object) -> None:
        self._conn.execute(
            "DELETE FROM decree_dossier_decisions WHERE id=?", (decision_id,),
        )

    def delete_reported_progress(self, progress_id: object) -> None:
        self._conn.execute(
            "DELETE FROM dossier_reported_progress WHERE id=?", (progress_id,),
        )

    def delete_pending_action(self, action_id: object) -> None:
        self._conn.execute("DELETE FROM pending_actions WHERE id=?", (action_id,))

    def delete_link(self, link_id: object) -> None:
        self._conn.execute("DELETE FROM decree_dossier_links WHERE id=?", (link_id,))

    # ── pending_actions persistence primitives (fact owner) ─────────

    def pending_action_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT * FROM pending_actions WHERE id=?", (int(action_id),),
        ).fetchone()

    def pending_action_payload_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (int(action_id),),
        ).fetchone()

    def pending_action_payload_status(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT payload_json, status FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_directive_version_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT version FROM pending_actions WHERE id=? AND kind='directive'",
            (int(action_id),),
        ).fetchone()

    def pending_kind_version_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT kind, version FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_version_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT version FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_night_id_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT night_id FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_kind_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT kind FROM pending_actions WHERE id=?", (int(action_id),),
        ).fetchone()

    def pending_forecast_state_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT status,kind,action,night_approved,night_id,version "
            "FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_version_forecast_row(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT version, status, kind, action, night_approved, night_id "
            "FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_row_for_turn(self, action_id: int, turn: int) -> Any:
        return self._conn.execute(
            "SELECT id, night_id, status, payload_json FROM pending_actions "
            "WHERE id=? AND turn=?",
            (int(action_id), int(turn)),
        ).fetchone()

    def pending_decision_row(self, action_id: int, turn: int) -> Any:
        return self._conn.execute(
            "SELECT night_id, kind, action, minister_name, night_approved, payload_json "
            "FROM pending_actions WHERE id=? AND turn=? AND status='pending'",
            (int(action_id), int(turn)),
        ).fetchone()

    def pending_office_candidate_row(self, candidate_id: int) -> Any:
        return self._conn.execute(
            "SELECT id,payload_json,status FROM pending_actions "
            "WHERE id=? AND kind='office'",
            (int(candidate_id),),
        ).fetchone()

    def pending_directive_candidate_row(self, candidate_id: int) -> Any:
        return self._conn.execute(
            "SELECT id,payload_json,status,version FROM pending_actions "
            "WHERE id=? AND kind='directive'",
            (int(candidate_id),),
        ).fetchone()

    def pending_id_for_committed_directive(self, directive_id: int) -> Any:
        return self._conn.execute(
            "SELECT id FROM pending_actions WHERE committed_directive_id=? "
            "ORDER BY id DESC LIMIT 1",
            (int(directive_id),),
        ).fetchone()

    def pending_ids_for_turn(self, turn: int, *, status: str = "pending") -> list[int]:
        return [
            int(row["id"])
            for row in self._conn.execute(
                "SELECT id FROM pending_actions WHERE turn=? AND status=?",
                (int(turn), str(status)),
            ).fetchall()
        ]

    def night_approved_directive_ids(self, action_ids: Iterable[int]) -> list[int]:
        ids = sorted({int(i) for i in action_ids})
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            "SELECT id FROM pending_actions WHERE id IN (" + placeholders + ") "
            "AND kind='directive' AND action='拟旨' AND status='pending' "
            "AND night_approved=1 AND night_id>0",
            ids,
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def closed_nights_with_approved_pending(
        self, turn: int, closed_status: str,
    ) -> list[Any]:
        """Cross-entity projection: nights that still hold night-approved pending."""
        return self._conn.execute(
            "SELECT DISTINCT n.id FROM audience_nights n "
            "JOIN pending_actions pa ON pa.night_id=n.id "
            "WHERE n.turn=? AND n.status=? AND "
            "pa.status='pending' AND pa.night_approved=1 ORDER BY n.id",
            (int(turn), str(closed_status)),
        ).fetchall()

    def list_pending_actions(
        self, turn: int, status: str = "pending", minister_name: Optional[str] = None,
    ) -> list[dict[str, object]]:
        if minister_name is None:
            rows = self._conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
                "FROM pending_actions WHERE turn = ? AND status = ? ORDER BY id",
                (int(turn), str(status)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
                "FROM pending_actions WHERE turn = ? AND status = ? AND minister_name = ? "
                "ORDER BY id",
                (int(turn), str(status), str(minister_name)),
            ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "kind": r["kind"],
                "action": r["action"],
                "target_id": None if r["target_id"] is None else int(r["target_id"]),
                "minister_name": r["minister_name"],
                "payload_json": r["payload_json"],
                "status": r["status"],
            }
            for r in rows
        ]

    def list_failed_secret_order_actions(
        self, minister_name: Optional[str] = None,
    ) -> list[dict[str, object]]:
        sql = (
            "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
            "FROM pending_actions WHERE status='failed' AND kind='secret_order'"
        )
        params: tuple[object, ...] = ()
        if minister_name is not None:
            sql += " AND minister_name=?"
            params = (str(minister_name),)
        sql += " ORDER BY turn DESC, id"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "kind": r["kind"],
                "action": r["action"],
                "target_id": None if r["target_id"] is None else int(r["target_id"]),
                "minister_name": r["minister_name"],
                "payload_json": r["payload_json"],
                "status": r["status"],
            }
            for r in rows
        ]

    def list_night_approved_pending(
        self, night_id: int, *, kind: Optional[str] = None,
    ) -> list[dict[str, object]]:
        if kind is None:
            rows = self._conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, "
                "payload_json, status, night_id, night_approved "
                "FROM pending_actions "
                "WHERE night_id = ? AND night_approved = 1 AND status = 'pending' "
                "ORDER BY id",
                (int(night_id),),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, "
                "payload_json, status, night_id, night_approved "
                "FROM pending_actions "
                "WHERE night_id = ? AND night_approved = 1 AND status = 'pending' "
                "AND kind = ? ORDER BY id",
                (int(night_id), str(kind)),
            ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "kind": r["kind"],
                "action": r["action"],
                "target_id": r["target_id"],
                "minister_name": r["minister_name"],
                "payload_json": r["payload_json"],
                "status": r["status"],
                "night_id": int(r["night_id"] or 0),
                "night_approved": int(r["night_approved"] or 0),
            }
            for r in rows
        ]

    def list_pending_for_translate(
        self, turn: int, *, night_id: int = 0,
    ) -> list[Any]:
        params: list[object] = [int(turn)]
        sql = (
            "SELECT id, kind, action, payload_json, night_id, night_approved "
            "FROM pending_actions WHERE turn=? AND status='pending'"
        )
        if int(night_id or 0) > 0:
            sql += " AND night_id=?"
            params.append(int(night_id))
        sql += " ORDER BY id"
        return self._conn.execute(sql, tuple(params)).fetchall()

    def secret_order_pending_payloads(self) -> list[Any]:
        return self._conn.execute(
            "SELECT payload_json FROM pending_actions "
            "WHERE kind='secret_order' AND status IN ('pending','failed')"
        ).fetchall()

    def insert_pending_action(
        self,
        turn: int,
        kind: str,
        action: str,
        target_id: Optional[int],
        minister_name: str,
        payload_json: str,
        night_id: int,
        source_chat_turn_id: int = 0,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO pending_actions
               (turn, kind, action, target_id, minister_name, payload_json, status,
                night_id, night_approved, source_chat_turn_id)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?)""",
            (
                int(turn), str(kind), str(action),
                None if target_id is None else int(target_id),
                str(minister_name or ""),
                payload_json,
                int(night_id),
                int(source_chat_turn_id or 0),
            ),
        )
        return int(cur.lastrowid)

    def set_pending_payload(self, action_id: int, payload_json: str) -> None:
        self._conn.execute(
            "UPDATE pending_actions SET payload_json=? WHERE id=?",
            (payload_json, int(action_id)),
        )

    def set_pending_payload_clear_approval(
        self, action_id: int, payload_json: str,
    ) -> None:
        self._conn.execute(
            "UPDATE pending_actions SET payload_json=?, night_approved=0 WHERE id=?",
            (payload_json, int(action_id)),
        )

    def set_pending_payload_bump_version(
        self, action_id: int, payload_json: str,
    ) -> None:
        self._conn.execute(
            "UPDATE pending_actions SET payload_json=?, version=version+1 WHERE id=?",
            (payload_json, int(action_id)),
        )

    def rehome_pending_payload(
        self,
        action_id: int,
        payload_json: str,
        night_id: int,
        *,
        bump_version: bool = False,
    ) -> None:
        if bump_version:
            self._conn.execute(
                "UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0, "
                "version=version+1 WHERE id=?",
                (payload_json, int(night_id), int(action_id)),
            )
        else:
            self._conn.execute(
                "UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0 "
                "WHERE id=?",
                (payload_json, int(night_id), int(action_id)),
            )

    def set_pending_status(self, action_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE pending_actions SET status=? WHERE id=?",
            (str(status), int(action_id)),
        )

    def set_committed_directive_id(
        self, action_id: int, directive_id: int,
    ) -> None:
        self._conn.execute(
            "UPDATE pending_actions SET committed_directive_id=? WHERE id=?",
            (int(directive_id), int(action_id)),
        )

    def carry_pending_to_turn(self, action_id: int, turn: int) -> None:
        self._conn.execute(
            "UPDATE pending_actions "
            "SET turn=?, night_id=0, night_approved=0 WHERE id=?",
            (int(turn), int(action_id)),
        )

    def mark_pending_night_approved(
        self, action_ids: Iterable[int], *, night_id: Optional[int] = None,
    ) -> int:
        ids = [int(i) for i in action_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        params: list[Any] = list(ids)
        extra = ""
        if night_id is not None:
            extra = " AND night_id = ?"
            params.append(int(night_id))
        cur = self._conn.execute(
            f"UPDATE pending_actions SET night_approved = 1 "
            f"WHERE id IN ({placeholders}) AND status = 'pending'{extra}",
            params,
        )
        return int(cur.rowcount or 0)

    def hold_over_pending_actions(
        self,
        turn: int,
        minister_name: str,
        action_ids: Optional[Iterable[int]] = None,
        *,
        commit: bool = True,
    ) -> int:
        """#525 留中：点名候选移出 status=pending 活跃集，同表 durable 留中档。

        不删行；commit_pending_actions 只读 pending，故默认提交自然跳过、不成案。
        返回更新条数。action_ids 非空=只留中指定 id（#502 点名粒度）。
        """
        owns = self._owns()
        params: list[object] = [int(turn), str(minister_name)]
        where = "turn=? AND minister_name=? AND status='pending'"
        if action_ids is not None:
            allowed_ids = [int(action_id) for action_id in action_ids]
            if not allowed_ids:
                return 0
            placeholders = ",".join("?" for _ in allowed_ids)
            where += f" AND id IN ({placeholders})"
            params.extend(allowed_ids)
        cur = self._conn.execute(
            f"UPDATE pending_actions SET status='held_over', night_approved=0 "
            f"WHERE {where}",
            tuple(params),
        )
        updated = int(cur.rowcount or 0)
        if updated:
            self._commit(commit, owns)
        return updated

    def withdraw_pending_action_row(self, action_id: int, turn: int) -> Any:
        return self._conn.execute(
            "SELECT id, kind, version FROM pending_actions "
            "WHERE id=? AND turn=? AND status='pending'",
            (int(action_id), int(turn)),
        ).fetchone()

    def delete_pending_if_pending(self, action_id: int, turn: int) -> int:
        cur = self._conn.execute(
            "DELETE FROM pending_actions WHERE id=? AND turn=? AND status='pending'",
            (int(action_id), int(turn)),
        )
        return int(cur.rowcount or 0)

    def delete_failed_secret_order_intents(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM pending_actions WHERE status='failed' AND kind='secret_order'"
        )
        return int(cur.rowcount or 0)

    def actual_progress_units(self, dossier_id: int) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS total FROM dossier_actual_progress "
            "WHERE dossier_id=?",
            (int(dossier_id),),
        ).fetchone()
        return float(row["total"] if row is not None else 0.0)

    def actual_progress_at(self, dossier_id: int, turn: int) -> Optional[dict[str, object]]:
        row = self._conn.execute(
            "SELECT id, units FROM dossier_actual_progress "
            "WHERE dossier_id=? AND turn=? LIMIT 1",
            (int(dossier_id), int(turn)),
        ).fetchone()
        return dict(row) if row is not None else None

    def pending_source_status(self, action_id: int) -> Any:
        return self._conn.execute(
            "SELECT source_chat_turn_id, status FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()

    def pending_voidable_for_chat_turn(self, chat_turn_id: int) -> list[Any]:
        return self._conn.execute(
            "SELECT id, kind, version FROM pending_actions "
            "WHERE source_chat_turn_id = ? AND status = 'pending' ORDER BY id",
            (int(chat_turn_id),),
        ).fetchall()

    def pending_ids_for_chat_turn(self, chat_turn_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM pending_actions WHERE source_chat_turn_id = ? ORDER BY id",
            (int(chat_turn_id),),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def void_pending_if_pending(self, action_id: int) -> None:
        self._conn.execute(
            "UPDATE pending_actions SET status='voided', night_approved=0 "
            "WHERE id=? AND status='pending'",
            (int(action_id),),
        )
