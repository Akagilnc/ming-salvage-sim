"""#624 / ADR 0078 催双刃拉杆＋反催谏言。

催＝承诺/案卷层催办事实 → build_due_review_input.urge_history。
真加速写口按对象类唯一：
- 密令：secret_orders.due_turn（既有 rush_secret_order）
- 分段承诺：issues.stages_json[].due_turn（本模块 rush_staged_commitment_stage）
反催谏/求宽限的记录能力仍是 next_audience_todos 的 entry_kind，真伪只活在 payload_json。
#1895：催办不再按胆识、皇威、操守或可乘之利代选谏言、求缓与真伪。
期限提前、催办史和已记录的谏言／求缓照留；人物说不说归既有人物 run。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    normalize_commitment_stages,
    stages_to_json,
)
from ming_sim.token_stats import tlog

# pending_actions 史源 kind（committed 行；DELETE 仅清 pending）
URGE_PENDING_KIND_COMMITMENT = "commitment"
URGE_PENDING_ACTION = "催办"

# 可乘之利：流水绝对额合计（到期复核供料，不代选人物行动）
_OPPORTUNITY_HIGH_ABS = 4000


def derive_opportunity_band(durable_effects: object) -> str:
    """由 economy/fiscal 流水派生可乘之利档（不依赖未落地 0119）。"""
    rows = list(durable_effects or [])
    if not rows:
        return "none"
    total_abs = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("delta", "amount", "new_value", "old_value"):
            if key in row and row.get(key) is not None:
                try:
                    if key == "old_value":
                        continue
                    total_abs += abs(int(row.get(key) or 0))
                except (TypeError, ValueError):
                    pass
                break
        else:
            # fiscal change: |new-old|
            try:
                nv = int(row.get("new_value") or 0)
                ov = int(row.get("old_value") or 0)
                total_abs += abs(nv - ov)
            except (TypeError, ValueError):
                pass
    if total_abs <= 0:
        return "none"
    if total_abs >= _OPPORTUNITY_HIGH_ABS:
        return "high"
    return "low"


def _parse_payload(raw: object) -> Dict[str, object]:
    """催办史 payload 读路：与 GameDB.parse_engine_payload_json 合一；腐坏响亮。"""
    from ming_sim.db import GameDB
    return GameDB.parse_engine_payload_json(
        raw, surface="pending_actions.payload_json",
    )


def collect_urge_history(
    db: Any,
    *,
    commitment_ref: int,
    dossier_id: Optional[int] = None,
) -> List[Dict[str, object]]:
    """催办史：committed pending_actions(action=催办)。缺源=[]。"""
    out: List[Dict[str, object]] = []
    # 承诺/案卷层
    rows = db.conn.execute(
        """
        SELECT id, turn, kind, action, target_id, payload_json, status
        FROM pending_actions
        WHERE status='committed' AND action=?
          AND kind=? AND target_id=?
        ORDER BY turn, id
        """,
        (URGE_PENDING_ACTION, URGE_PENDING_KIND_COMMITMENT, int(commitment_ref)),
    ).fetchall()
    for row in rows:
        payload = _parse_payload(row["payload_json"])
        out.append({
            "id": int(row["id"]),
            "turn": int(row["turn"] or 0),
            "kind": str(row["kind"] or ""),
            "target_id": int(row["target_id"] or 0),
            "old_due": int(payload.get("old_due") or 0),
            "new_due": int(payload.get("new_due") or 0),
            "deadline_months": int(payload.get("deadline_months") or 0),
            "tightness": int(payload.get("tightness") or 0),
            "stage_idx": int(payload.get("stage_idx") or 0),
            "reason": str(payload.get("reason") or ""),
            "source": "commitment",
        })

    # 密令路：案卷挂 secret_order_id 时并入史源
    if dossier_id is not None:
        dossier = db.get_decree_dossier(int(dossier_id)) if hasattr(db, "get_decree_dossier") else None
        so_id = 0
        if isinstance(dossier, dict):
            try:
                so_id = int(dossier.get("secret_order_id") or 0)
            except (TypeError, ValueError):
                so_id = 0
        if so_id > 0:
            so_rows = db.conn.execute(
                """
                SELECT id, turn, kind, action, target_id, payload_json, status
                FROM pending_actions
                WHERE status='committed' AND action=?
                  AND kind='secret_order' AND target_id=?
                ORDER BY turn, id
                """,
                (URGE_PENDING_ACTION, int(so_id)),
            ).fetchall()
            for row in so_rows:
                payload = _parse_payload(row["payload_json"])
                out.append({
                    "id": int(row["id"]),
                    "turn": int(row["turn"] or 0),
                    "kind": str(row["kind"] or ""),
                    "target_id": int(row["target_id"] or 0),
                    "old_due": int(payload.get("old_due") or 0),
                    "new_due": int(payload.get("new_due") or 0),
                    "deadline_months": int(
                        payload.get("deadline_months")
                        if payload.get("deadline_months") is not None
                        else 1
                    ),
                    "tightness": int(payload.get("tightness") or 0),
                    "stage_idx": -1,
                    "reason": str(payload.get("reason") or ""),
                    "source": "secret_order",
                })
    out.sort(key=lambda item: (int(item["turn"]), int(item["id"])))
    return out


def resolve_host_character(db: Any, *, commitment_ref: int, dossier_id: Optional[int]) -> Dict[str, object]:
    """承办人：案卷主办优先，否则 issue participants 首名；缺省中性档。"""
    name = ""
    if dossier_id is not None and hasattr(db, "get_decree_dossier"):
        dossier = db.get_decree_dossier(int(dossier_id))
        if isinstance(dossier, dict):
            roster = dossier.get("participant_roster") or []
            if isinstance(roster, str):
                try:
                    roster = json.loads(roster)
                except (TypeError, ValueError):
                    roster = []
            for item in roster or []:
                if isinstance(item, dict) and str(item.get("tier") or "") == "主办":
                    name = str(item.get("character_id") or "").strip()
                    if name:
                        break
    if not name:
        row = db.conn.execute(
            "SELECT participants, participant_roster FROM issues WHERE id=?",
            (int(commitment_ref),),
        ).fetchone()
        if row is not None:
            try:
                roster = json.loads(row["participant_roster"] or "[]")
            except (TypeError, ValueError):
                roster = []
            for item in roster or []:
                if isinstance(item, dict):
                    cand = str(item.get("character_id") or "").strip()
                    if cand:
                        name = cand
                        break
            if not name:
                try:
                    parts = json.loads(row["participants"] or "[]")
                except (TypeError, ValueError):
                    parts = []
                if parts:
                    name = str(parts[0]).strip()
    integrity, courage = 50, 50
    if name:
        crow = db.conn.execute(
            "SELECT integrity, courage FROM characters WHERE name=?",
            (name,),
        ).fetchone()
        if crow is not None:
            try:
                integrity = int(crow["integrity"])
            except (TypeError, ValueError):
                integrity = 50
            try:
                courage = int(crow["courage"])
            except (TypeError, ValueError):
                courage = 50
    return {"name": name, "integrity": integrity, "courage": courage}


def _record_commitment_urge(
    db: Any,
    state: Any,
    *,
    commitment_ref: int,
    stage_idx: int,
    old_due: int,
    new_due: int,
    deadline_months: int,
    reason: str,
) -> None:
    """committed 行作史源（不经 settle 批交；DELETE 仅清 pending）。"""
    tightness = max(0, int(old_due) - int(new_due))
    payload = {
        "stage_idx": int(stage_idx),
        "old_due": int(old_due),
        "new_due": int(new_due),
        "deadline_months": int(deadline_months),
        "tightness": tightness,
        "reason": str(reason or ""),
    }
    db.conn.execute(
        """
        INSERT INTO pending_actions
            (turn, kind, action, target_id, minister_name, payload_json, status)
        VALUES (?, ?, ?, ?, '', ?, 'committed')
        """,
        (
            int(getattr(state, "turn", 0) or 0),
            URGE_PENDING_KIND_COMMITMENT,
            URGE_PENDING_ACTION,
            int(commitment_ref),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ),
    )


def _issue_exists(db: Any, commitment_ref: int) -> bool:
    row = db.conn.execute(
        "SELECT id FROM issues WHERE id=?", (int(commitment_ref),),
    ).fetchone()
    return row is not None


def rush_staged_commitment_stage(
    db: Any,
    state: Any,
    *,
    commitment_ref: int,
    stage_idx: int,
    deadline_months: int = 1,
    reason: str = "",
    commit: bool = True,
    record_history: bool = True,
) -> Dict[str, object]:
    """分段承诺真加速唯一写口：缩 issues.stages_json[].due_turn。

    不用 decree_dossiers.due_turn。同对象不得双真源。
    不写 issues.end_turn（#620 段派生 end_turn 不落 DB；催办不得侧写第二时间线）。
    无 issue 承载 → ValueError（不伪造 issue）。催办不代选谏言、求缓或真伪。
    record_history=False：生产入口经 pending_actions 确认闸门落库时，由该 pending 行作史源，
    避免双插 committed 行。
    """
    if not _issue_exists(db, commitment_ref):
        raise ValueError(f"承诺 issue#{int(commitment_ref)} 不存在，不能催办")

    row = db.conn.execute(
        "SELECT id, stages_json, status, commitment_kind FROM issues WHERE id=?",
        (int(commitment_ref),),
    ).fetchone()
    if str(row["status"] or "") != "active":
        raise ValueError(f"承诺 issue#{int(commitment_ref)} 状态 {row['status']}，不能催办")

    stages = normalize_commitment_stages(row["stages_json"])
    if not stages:
        raise ValueError(f"承诺 issue#{int(commitment_ref)} 无分段，不能催办")

    target_stage = None
    target_i = -1
    for i, stage in enumerate(stages):
        if int(stage["stage_idx"]) == int(stage_idx):
            target_stage = stage
            target_i = i
            break
    if target_stage is None:
        raise ValueError(f"承诺 issue#{int(commitment_ref)} 无 stage_idx={stage_idx}")

    try:
        months = max(0, min(int(deadline_months if deadline_months is not None else 1), 36))
    except (TypeError, ValueError):
        months = 1

    turn = int(getattr(state, "turn", 0) or 0)
    old_due = int(target_stage["due_turn"])
    if months <= 0:
        new_due = turn
    else:
        target_turn = turn + months
        new_due = target_turn if old_due <= 0 else min(old_due, target_turn)

    stages[target_i] = {
        **target_stage,
        "due_turn": int(new_due),
    }
    stages_blob = stages_to_json(stages)

    # 唯一写口：stages_json[].due_turn。禁侧写 issues.end_turn（票面单口 + #620 不落 DB）。
    db.conn.execute(
        """
        UPDATE issues
        SET stages_json=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (stages_blob, int(commitment_ref)),
    )

    why = reason if str(reason or "").strip() else "奉旨加急"
    if record_history:
        _record_commitment_urge(
            db, state,
            commitment_ref=int(commitment_ref),
            stage_idx=int(stage_idx),
            old_due=old_due,
            new_due=int(new_due),
            deadline_months=months,
            reason=why,
        )

    if commit:
        db.conn.commit()

    return {
        "commitment_ref": int(commitment_ref),
        "stage_idx": int(stage_idx),
        "old_due": int(old_due),
        "due_turn": int(new_due),
        "deadline_months": months,
        "reason": why,
    }


_URGE_AUDIENCE_KINDS = frozenset({
    ENTRY_KIND_RUSH_REMONSTRANCE,
    ENTRY_KIND_GRACE_PLEA,
})


def is_urge_audience_entry_kind(entry_kind: object) -> bool:
    return str(entry_kind or "").strip() in _URGE_AUDIENCE_KINDS


def project_urge_audience_scene(todo: Dict[str, object]) -> Dict[str, object]:
    """谏/宽限召对顶出投影：P4 定性措辞；永不读 payload_json（真伪底禁泄）。"""
    kind = str(todo.get("entry_kind") or "").strip()
    criterion = str(todo.get("criterion_text") or "")
    origin = str(todo.get("origin_context") or "")
    label = "rush_remonstrance" if kind == ENTRY_KIND_RUSH_REMONSTRANCE else "grace_plea"
    return {
        "kind": label,
        "entry_kind": kind,
        "todo_id": int(todo.get("id") or 0),
        "commitment_ref": int(todo.get("commitment_ref") or 0),
        "stage_idx": int(todo.get("stage_idx") or 0),
        "due_turn": int(todo.get("due_turn") or 0),
        "origin_context": origin,
        "criterion_text": criterion,
        # 故意不暴露 payload_json / truth / grace_fake
    }


def list_urge_audience_scenes(
    db: Any, state: Any = None, *, status: str = TODO_STATUS_PENDING,
) -> List[Dict[str, object]]:
    """次回合召对顶出：谏/宽限 pending（不进 due-review 白名单、不占接管窗）。"""
    todos = db.list_next_audience_todos(status=status)
    scenes: List[Dict[str, object]] = []
    for todo in todos:
        if not is_urge_audience_entry_kind(todo.get("entry_kind")):
            continue
        scenes.append(project_urge_audience_scene(todo))
    return scenes


def consume_pending_urge_audience_todos(
    db: Any, state: Any, *, commit: bool = False,
) -> List[Dict[str, object]]:
    """消费路径：经召对窗后的 settle 将 created_turn < 当前 turn 的谏/宽限标 consumed。

    与 due-review 三拍对称第 3 拍；不落执行格、不连坐、不进白名单 apply。
    闭环：写（rush）→ 顶出（open_night/list_urge_audience_scenes）→ 本函数离 pending。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    results: List[Dict[str, object]] = []
    for todo in db.list_next_audience_todos(status=TODO_STATUS_PENDING):
        if not is_urge_audience_entry_kind(todo.get("entry_kind")):
            continue
        if int(todo.get("created_turn") or 0) >= turn:
            continue
        ok = db.mark_next_audience_todo_status(
            int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
        )
        results.append({
            "todo_id": int(todo["id"]),
            "entry_kind": str(todo.get("entry_kind") or ""),
            "consumed": bool(ok),
        })
    if commit and results:
        db.conn.commit()
    return results
