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
DOSSIER_REPORT_ORIGIN_MONTHLY = "dossier-report:monthly_errand"
DOSSIER_REPORT_ORIGIN_VERDICT = "dossier-report:execution_verdict"
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
CREATE TABLE IF NOT EXISTS pending_promulgation_verdicts (
    turn INTEGER NOT NULL,
    dossier_id INTEGER NOT NULL,
    verdict_json TEXT NOT NULL,
    PRIMARY KEY(turn, dossier_id),
    FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE
);
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
    """
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

    def _commit(self, commit: bool) -> None:
        """Commit unless an outer atomic/BEGIN owns the transaction."""
        if commit and not bool(getattr(self._conn, "_commit_suspended", False)) and int(
            getattr(self._conn, "_atomic_depth", 0) or 0
        ) == 0:
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

    def list_for_directive(self, directive_id: int) -> list[dict[str, Any]]:
        """#654：directive 名下全部子差务，ORDER BY region_id, id。"""
        rows = self._conn.execute(
            "SELECT * FROM decree_dossiers WHERE directive_id=? "
            "ORDER BY region_id, id",
            (int(directive_id),),
        ).fetchall()
        return [hydrate_dossier_row(r) for r in rows]

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

    def list_for_simulation(self, turn: int) -> list[dict[str, Any]]:
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

    def presence_turns_by_auditor(
        self, *, min_months: int, as_of_turn: Optional[int] = None,
    ) -> list[Any]:
        sql = (
            "SELECT auditor_name, dossier_id, turn FROM dossier_supervision_presence "
            "WHERE present=1"
        )
        params: tuple = ()
        if as_of_turn is not None:
            sql += " AND turn<=?"
            params = (int(as_of_turn),)
        return self._conn.execute(
            sql + " GROUP BY auditor_name, dossier_id, turn "
                  "ORDER BY auditor_name, dossier_id, turn",
            params,
        ).fetchall()

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
        self, dossier_id: int, turn: int, action_type: str, execution_form: str,
    ) -> bool:
        """True when this call wrote the row (existence of the rail is the key)."""
        cur = self._conn.execute(
            """
            INSERT INTO dossier_loophole_exposures
                (dossier_id, turn, action_type, execution_form)
            VALUES (?,?,?,?)
            ON CONFLICT(dossier_id, turn, action_type, execution_form) DO NOTHING
            """,
            (int(dossier_id), int(turn), action_type, execution_form),
        )
        return int(cur.rowcount or 0) > 0

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
            raw_payload = row["payload_json"]
            payload = json.loads("{}" if raw_payload is None or raw_payload == "" else raw_payload)
            if not isinstance(payload, dict):
                raise ValueError(f"检举载荷须为对象，得 {type(payload).__name__}")
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

    def set_affair_id_if_unbound(self, dossier_id: int, affair_id: int) -> int:
        """Bind once; same id is idempotent; a different id fails loud.

        Transaction ownership is read before the UPDATE. The write itself opens
        an implicit transaction, so a check afterwards would treat that
        transaction as an outer one and skip the commit.
        """
        from ming_sim.applier import connection_owns_transaction

        want = int(affair_id)
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "UPDATE decree_dossiers SET affair_id=? WHERE id=? AND affair_id=0",
            (want, int(dossier_id)),
        )
        if int(cur.rowcount or 0) == 1:
            if owns:
                self._conn.commit()
            return want
        current = self.affair_id_of(dossier_id)
        if current == want:
            if owns:
                self._conn.commit()
            return want
        if owns:
            self._conn.rollback()
        raise ValueError(f"案卷已指向事务 {current}，不能改指 {want}")

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

    def save_pending_promulgation_verdicts(
        self, turn: int, verdicts: Iterable[tuple[int, str]],
    ) -> None:
        """Replace one turn's whole batch (delete-then-insert, same transaction)."""
        self._conn.execute(
            "DELETE FROM pending_promulgation_verdicts WHERE turn=?", (int(turn),)
        )
        for dossier_id, verdict_json in verdicts:
            self._conn.execute(
                "INSERT INTO pending_promulgation_verdicts"
                "(turn,dossier_id,verdict_json) VALUES (?,?,?)",
                (int(turn), int(dossier_id), verdict_json),
            )

    def clear_pending_promulgation_verdicts(self, turn: int) -> None:
        self._conn.execute(
            "DELETE FROM pending_promulgation_verdicts WHERE turn=?", (int(turn),)
        )

    def pending_promulgation_verdicts(self, turn: int) -> list[str]:
        return [
            str(r["verdict_json"])
            for r in self._conn.execute(
                "SELECT verdict_json FROM pending_promulgation_verdicts "
                "WHERE turn=? ORDER BY dossier_id",
                (int(turn),),
            ).fetchall()
        ]

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

    def actual_progress_units(self, dossier_id: int) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS total FROM dossier_actual_progress "
            "WHERE dossier_id=?",
            (int(dossier_id),),
        ).fetchone()
        return float(row["total"] if row is not None else 0.0)

