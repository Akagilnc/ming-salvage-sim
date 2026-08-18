"""#624 / ADR 0078 催双刃拉杆＋反催谏言。

催＝承诺/案卷层催办事实 → build_due_review_input.urge_history。
真加速写口按对象类唯一：
- 密令：secret_orders.due_turn（既有 rush_secret_order）
- 分段承诺：issues.stages_json[].due_turn（本模块 rush_staged_commitment_stage）
失真倾向＝读时派生定性档（零新持久数值列）。
反催谏/求宽限走 next_audience_todos 新 entry_kind，真伪底仅 payload_json。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
    normalize_commitment_stages,
    stages_to_json,
)

# pending_actions 史源 kind（committed 行；DELETE 仅清 pending）
URGE_PENDING_KIND_COMMITMENT = "commitment"
URGE_PENDING_ACTION = "催办"

# 人身 archetype 阈值（characters.integrity 0-100）
_INTEGRITY_GUDU = 75  # 孤直
_INTEGRITY_FUSHI = 40  # 低于此 → 附势；中间庸吏

# 期限离谱：压缩比 ≤ 此阈值，或剩余月数过短
_UNREASONABLE_RATIO = 0.34
_UNREASONABLE_REMAIN_CAP = 3

# 敢言：courage - 皇威压制（0068 高皇威负向）
_DARE_SPEAK_FLOOR = 35

# 可乘之利：流水绝对额合计
_OPPORTUNITY_HIGH_ABS = 4000

_DISTORTION_RANK = ("不歪", "微歪", "易歪", "必歪")


def person_integrity_archetype(integrity: object) -> str:
    try:
        score = int(integrity)
    except (TypeError, ValueError):
        score = 50
    if score >= _INTEGRITY_GUDU:
        return "孤直"
    if score < _INTEGRITY_FUSHI:
        return "附势"
    return "庸吏"


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


def _clamp_band_index(idx: int) -> int:
    return max(0, min(int(idx), len(_DISTORTION_RANK) - 1))


def derive_distortion_tendency(
    *,
    integrity: object = 50,
    urge_count: int = 0,
    urge_tightness: int = 0,
    supervision_history: object = None,
    opportunity_band: str = "none",
) -> Dict[str, object]:
    """读时派生失真定性档。零持久数值；纯函数可复现。"""
    archetype = person_integrity_archetype(integrity)
    try:
        count = max(0, int(urge_count or 0))
    except (TypeError, ValueError):
        count = 0
    try:
        tightness = max(0, int(urge_tightness or 0))
    except (TypeError, ValueError):
        tightness = 0
    supervision = list(supervision_history or [])
    opp = str(opportunity_band or "none")

    if count <= 0 and tightness <= 0:
        return {
            "band": "不歪",
            "archetype": archetype,
            "note": "未催",
            "urge_count": 0,
            "urge_tightness": 0,
        }

    # 基础压力：次数 + 催紧月数
    pressure = count + (1 if tightness >= 6 else 0) + (1 if tightness >= 18 else 0)

    if archetype == "孤直":
        # 催孤直不歪——宁抗命
        idx = 0 if pressure < 4 else 1
        note = "孤直承催，宁抗不歪"
    elif archetype == "附势":
        # 附势必歪倾向：压力抬一档，可乘之利再抬（避免未触顶前被 clamp 抹平差分）
        idx = min(1 + pressure, 2)  # 微 / 易
        if opp == "high":
            idx += 1  # → 必歪
        elif opp == "low" and pressure >= 3:
            idx = min(idx + 1, 3)
        note = "附势承催，失真易涨"
    else:
        # 庸吏：看监督
        idx = min(pressure, 2)
        idx = max(1, idx) if pressure else 0
        if supervision:
            idx = max(0, idx - 1)
            note = "庸吏有监督在场，歪办受制"
        else:
            if opp == "high":
                idx += 1
            note = "庸吏无监督，承催易歪"

    idx = _clamp_band_index(idx)
    return {
        "band": _DISTORTION_RANK[idx],
        "archetype": archetype,
        "note": note,
        "urge_count": count,
        "urge_tightness": tightness,
    }


def dare_speak_score(courage: object, imperial_prestige: object) -> int:
    """敢言度＝胆识 − 皇威负向调制（0068）。"""
    try:
        c = int(courage)
    except (TypeError, ValueError):
        c = 50
    try:
        p = int(imperial_prestige)
    except (TypeError, ValueError):
        p = 50
    # 皇威以 50 为中性；高于中性压制敢言
    return int(c) - max(0, int(p) - 40)


def dare_speak_passes(courage: object, imperial_prestige: object) -> bool:
    return dare_speak_score(courage, imperial_prestige) >= _DARE_SPEAK_FLOOR


def is_deadline_unreasonable(
    *,
    old_due: int,
    new_due: int,
    current_turn: int,
) -> bool:
    """期限离谱判据（首版阈值，可 playtest 调）。"""
    try:
        old_r = max(0, int(old_due) - int(current_turn))
        new_r = max(0, int(new_due) - int(current_turn))
    except (TypeError, ValueError):
        return False
    if old_r <= 0:
        return False
    if new_r <= _UNREASONABLE_REMAIN_CAP and old_r > _UNREASONABLE_REMAIN_CAP * 2:
        return True
    if new_r <= int(old_r * _UNREASONABLE_RATIO):
        return True
    return False


def derive_grace_truth(
    *,
    unreasonable: bool,
    archetype: str,
    opportunity_band: str = "none",
) -> Dict[str, object]:
    """求宽限真伪底：引擎知底，不进玩家面。"""
    # 工期真不够：期限离谱且非附势借机
    if unreasonable and archetype != "附势":
        return {"truth": "genuine", "grace_fake": False}
    if (not unreasonable) and archetype == "附势":
        return {"truth": "pretextual", "grace_fake": True}
    if archetype == "附势" and opportunity_band == "high":
        return {"truth": "pretextual", "grace_fake": True}
    if unreasonable:
        return {"truth": "genuine", "grace_fake": False}
    # 附势轻催：借宽限拖磨
    if archetype == "附势":
        return {"truth": "pretextual", "grace_fake": True}
    return {"truth": "genuine", "grace_fake": False}


def _parse_payload(raw: object) -> Dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip() or "{}"
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


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


def summarize_urge_pressure(urge_history: object) -> Dict[str, int]:
    rows = list(urge_history or [])
    count = len(rows)
    tightness = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = int(row.get("tightness") or 0)
        if t <= 0:
            old_d = int(row.get("old_due") or 0)
            new_d = int(row.get("new_due") or 0)
            if old_d > 0 and new_d > 0 and old_d > new_d:
                t = old_d - new_d
        tightness += max(0, t)
    return {"urge_count": count, "urge_tightness": tightness}


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


def apply_distortion_to_verdict(
    verdict: Dict[str, object],
    distortion: Dict[str, object],
    *,
    has_effects: bool,
    has_reports: bool,
) -> Dict[str, object]:
    """失真档对确定性判词的可观察调制（不增 LLM 步）。"""
    if bool(verdict.get("mid_stage")):
        return verdict
    band = str((distortion or {}).get("band") or "不歪")
    outcome = str(verdict.get("outcome") or "")
    note = str(verdict.get("note") or "")
    out = dict(verdict)

    if band == "不歪":
        return out

    if outcome == "fulfilled":
        if band == "必歪":
            out["outcome"] = "transformed"
            out["note"] = (note + "；催办失真，事已变形")[:200]
        elif band in {"易歪", "微歪"}:
            out["outcome"] = "degraded"
            out["note"] = (note + "；催紧之下，实绩打折")[:200]
    elif outcome == "degraded":
        if band == "必歪":
            out["outcome"] = "failed" if not has_effects else "transformed"
            out["note"] = (note + "；催之愈急，愈见走样")[:200]
        elif band == "易歪" and not has_effects:
            out["outcome"] = "failed"
            out["note"] = (note + "；表报难掩亏空")[:200]
    elif outcome == "failed":
        # 已是最重终值；附注失真
        if band in {"易歪", "必歪"}:
            out["note"] = (note + "；催办之下终无实绩")[:200]
    return out


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
        "reason": str(reason or "")[:120],
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
) -> Dict[str, object]:
    """分段承诺真加速唯一写口：缩 issues.stages_json[].due_turn。

    不用 decree_dossiers.due_turn。同对象不得双真源。
    无 issue 承载 → ValueError（fail-closed 不产谏条、不伪造 issue）。
    """
    if not _issue_exists(db, commitment_ref):
        raise ValueError(f"承诺 issue#{int(commitment_ref)} 不存在，不能催办")

    row = db.conn.execute(
        "SELECT id, stages_json, end_turn, status, commitment_kind FROM issues WHERE id=?",
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
    old_max_due = max(int(s["due_turn"]) for s in stages)
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

    # end_turn 若为段派生展示，同步 max due（不另立期限列 / 不用 dossier.due_turn）
    try:
        end_turn = int(row["end_turn"] or 0)
    except (TypeError, ValueError):
        end_turn = 0
    new_max = max(int(s["due_turn"]) for s in stages)
    end_sql = ""
    end_params: list[object] = []
    if end_turn > 0 and end_turn == old_max_due:
        end_sql = ", end_turn=?"
        end_params.append(int(new_max))
    elif end_turn <= 0:
        end_sql = ", end_turn=?"
        end_params.append(int(new_max))

    db.conn.execute(
        f"""
        UPDATE issues
        SET stages_json=?{end_sql}, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (stages_blob, *end_params, int(commitment_ref)),
    )

    why = (reason or "").strip()[:120] or "奉旨加急"
    _record_commitment_urge(
        db, state,
        commitment_ref=int(commitment_ref),
        stage_idx=int(stage_idx),
        old_due=old_due,
        new_due=int(new_due),
        deadline_months=months,
        reason=why,
    )

    host = resolve_host_character(db, commitment_ref=int(commitment_ref), dossier_id=None)
    # try dossier host if issue linked
    origin_row = db.conn.execute(
        "SELECT origin_ref FROM issues WHERE id=?", (int(commitment_ref),),
    ).fetchone()
    dossier_id = None
    if origin_row is not None:
        ref = str(origin_row["origin_ref"] or "")
        if ref.startswith("dossier:"):
            try:
                dossier_id = int(ref.split(":", 1)[1])
            except (TypeError, ValueError):
                dossier_id = None
    if dossier_id is not None:
        host = resolve_host_character(
            db, commitment_ref=int(commitment_ref), dossier_id=dossier_id,
        )

    prestige = 50
    try:
        metrics = getattr(state, "metrics", None) or {}
        prestige = int(metrics.get("皇威", 50))
    except (TypeError, ValueError):
        prestige = 50

    unreasonable = is_deadline_unreasonable(
        old_due=old_due, new_due=int(new_due), current_turn=turn,
    )
    archetype = person_integrity_archetype(host["integrity"])
    opp = "none"
    if dossier_id is not None and hasattr(db, "list_economy_moves_for_dossier"):
        effects = list(db.list_economy_moves_for_dossier(int(dossier_id)))
        if hasattr(db, "list_fiscal_effects_for_dossier"):
            effects = effects + list(db.list_fiscal_effects_for_dossier(int(dossier_id)))
        opp = derive_opportunity_band(effects)

    remonstrance_written = False
    grace_written = False

    # 操之过急谏：期限离谱 + 敢言；UNIQUE 幂等
    if unreasonable and dare_speak_passes(host["courage"], prestige):
        payload = {
            "truth": "genuine",
            "grace_fake": False,
            "kind": "rush_remonstrance",
            "unreasonable": True,
        }
        created = db.insert_next_audience_todo(
            commitment_ref=int(commitment_ref),
            stage_idx=int(stage_idx),
            due_turn=int(new_due),
            criterion_text="期限过急，恐难如期",
            origin_context=why,
            status="pending",
            entry_kind=ENTRY_KIND_RUSH_REMONSTRANCE,
            created_turn=turn,
            payload_json=payload,
            commit=False,
        )
        remonstrance_written = bool(created)

    # 求宽限：催即可能顶出（与谏可并存，entry_kind 不同）；真伪底仅 payload
    grace_truth = derive_grace_truth(
        unreasonable=unreasonable,
        archetype=archetype,
        opportunity_band=opp,
    )
    # 轻催也给附势/离谱场景写宽限；孤直离谱已走谏时仍可求宽限
    should_grace = unreasonable or archetype == "附势" or months <= 6
    if should_grace:
        g_payload = {
            **grace_truth,
            "kind": "grace_plea",
            "unreasonable": bool(unreasonable),
        }
        g_created = db.insert_next_audience_todo(
            commitment_ref=int(commitment_ref),
            stage_idx=int(stage_idx),
            due_turn=int(new_due),
            criterion_text="乞恩宽限",
            origin_context=why,
            status="pending",
            entry_kind=ENTRY_KIND_GRACE_PLEA,
            created_turn=turn,
            payload_json=g_payload,
            commit=False,
        )
        grace_written = bool(g_created)

    if commit:
        db.conn.commit()

    return {
        "commitment_ref": int(commitment_ref),
        "stage_idx": int(stage_idx),
        "old_due": int(old_due),
        "due_turn": int(new_due),
        "deadline_months": months,
        "reason": why,
        "unreasonable": bool(unreasonable),
        "remonstrance_written": remonstrance_written,
        "grace_written": grace_written,
        "host": host,
        "archetype": archetype,
    }
