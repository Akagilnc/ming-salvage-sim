"""#1504 B 包：密令 covert 差务机械实进度 + 到期交付缺口对账。

真源：
- ADR 0116 意愿轴机械底档 + 0092 带内选态只准加重
- ADR 0073 实况轨（非 0058 奏报）
- ADR 0120 done/failed 退役为到期对账派生
- SURVEY.md §4/§5 挂接点

边界墙（本模块不做）：暴露累积器/逐档跳/成色轴 0108/透支账/谎报反噬纹理。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# 四态：索引越大越重（只准加重 = 索引只增不减）
FIDELITY_STATES: tuple[str, ...] = ("忠实", "打折", "阳奉阴违", "反噬")
_FIDELITY_INDEX = {name: idx for idx, name in enumerate(FIDELITY_STATES)}

# 月度实进度单位（首版随 playtest；成色轴 0108 不读）
PROGRESS_UNITS: Dict[str, float] = {
    "忠实": 1.0,
    "打折": 0.5,
    "阳奉阴违": 0.0,
    "反噬": 0.0,
}

# 兼容 LLM 英文/旧词
_FIDELITY_ALIASES = {
    "faithful": "忠实",
    "fulfilled": "忠实",
    "discounted": "打折",
    "degraded": "打折",
    "surface": "阳奉阴违",
    "yangfeng": "阳奉阴违",
    "backlash": "反噬",
    "transformed": "反噬",
    "failed": "反噬",
}


def normalize_fidelity_state(raw: object) -> Optional[str]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in _FIDELITY_INDEX:
        return text
    return _FIDELITY_ALIASES.get(text.lower())


def progress_units_for_state(state: object) -> float:
    name = normalize_fidelity_state(state)
    if name is None:
        return 0.0
    return float(PROGRESS_UNITS[name])


def compute_willingness_floor(
    *,
    loyalty: int,
    identity: int,
    satisfaction: int,
    seed_guilt: str = "",
) -> str:
    """0116 意愿轴机械底档（纯函数，可 golden）。

    输入闭集：loyalty / identity / 派系 satisfaction / seed_guilt（血债代理）。
    不读 0058 奏报、不读 sim_note、不算成色 ability/阴谋。
    """
    loy = max(0, min(100, int(loyalty)))
    ident = max(0, min(100, int(identity)))
    sat = max(0, min(100, int(satisfaction)))
    # 忠诚与满意度为主臂；深度党附且不忠则下拉（能吏×不肯办的粗糙代理，非 0108）。
    score = 0.55 * loy + 0.35 * sat + 0.10 * (100 - ident)
    if ident >= 70 and loy < 55:
        score -= 18.0
    if str(seed_guilt or "").strip():
        score -= 12.0
    if score >= 70.0:
        return "忠实"
    if score >= 45.0:
        return "打折"
    if score >= 25.0:
        return "阳奉阴违"
    return "反噬"


def clamp_fidelity_to_floor(floor: object, selected: object) -> str:
    """0092：带内选态只准加重不准减轻。缺选/非法选 → 落在底档。"""
    floor_name = normalize_fidelity_state(floor) or "反噬"
    selected_name = normalize_fidelity_state(selected)
    if selected_name is None:
        return floor_name
    if _FIDELITY_INDEX[selected_name] < _FIDELITY_INDEX[floor_name]:
        return floor_name
    return selected_name


def target_progress_units(*, deadline_span: int, due_turn: int) -> float:
    """差务目标 Σ：有期限按月数（至少 1）；无 due 不进入到期对账。"""
    if int(due_turn or 0) <= 0:
        return 0.0
    span = int(deadline_span or 0)
    return float(max(span, 1))


def decide_secret_order_settlement(review_input: Mapping[str, object]) -> Dict[str, object]:
    """到期交付缺口对账——与 due_review.decide_due_review_verdict 同形精神：

    - 只读实况轨 Σ（actual_units），不读 progress_json / sim_note 作真源
    - 表报仅可入 note，不得翻实账归因
    - 交付缺口 → failed；已交付 → done
    """
    actual = float(review_input.get("actual_units") or 0.0)
    target = float(review_input.get("target_units") or 0.0)
    criterion = str(review_input.get("criterion_text") or "").strip() or "密令差务"
    has_reports = bool(review_input.get("has_reports"))
    origin = str(review_input.get("origin_context") or "").strip()

    delivered = target <= 0.0 or actual + 1e-9 >= target
    if delivered:
        status = "done"
        outcome = "fulfilled"
        note = f"到期对账：{criterion}实进度已交付（Σ={actual:g}/目标{target:g}）"
    else:
        status = "failed"
        outcome = "failed"
        note = f"到期对账：{criterion}交付缺口（Σ={actual:g}/目标{target:g}）"
        if has_reports:
            note = f"{note}；表报有之、不翻实账"
    if origin:
        note = f"{note}（{origin}）"
    return {
        "status": status,
        "outcome": outcome,
        "note": note[:200],
        "close": True,
        "is_terminal": True,
        "actual_units": actual,
        "target_units": target,
        "delivered": delivered,
    }


def build_minister_snapshot(db: Any, minister_name: str) -> Dict[str, object]:
    """读 DB 快照装配意愿轴输入（extractor 前可 golden）。"""
    name = str(minister_name or "").strip()
    row = db.conn.execute(
        "SELECT loyalty, identity, faction, seed_guilt FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    if row is None:
        return {
            "minister_name": name,
            "loyalty": 50,
            "identity": 50,
            "faction": "",
            "satisfaction": 50,
            "seed_guilt": "",
        }
    faction = str(row["faction"] or "")
    sat = 50
    if faction:
        try:
            sat = int(db.faction_satisfaction(faction))
        except Exception:
            sat = 50
    return {
        "minister_name": name,
        "loyalty": int(row["loyalty"] or 50),
        "identity": int(row["identity"] or 50),
        "faction": faction,
        "satisfaction": int(sat),
        "seed_guilt": str(row["seed_guilt"] or "") if "seed_guilt" in row.keys() else "",
    }


def compute_floor_for_minister(db: Any, minister_name: str) -> str:
    snap = build_minister_snapshot(db, minister_name)
    return compute_willingness_floor(
        loyalty=int(snap["loyalty"]),
        identity=int(snap["identity"]),
        satisfaction=int(snap["satisfaction"]),
        seed_guilt=str(snap.get("seed_guilt") or ""),
    )


def build_covert_floor_payload(db: Any, orders: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    """注入 personnel_secret 的机械底档带（只读快照，零 LLM）。"""
    out: List[Dict[str, object]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        oid = int(order.get("id") or 0)
        if oid <= 0:
            continue
        status = str(order.get("status") or "")
        if status not in {"active", "pending_review"}:
            continue
        minister = str(order.get("minister_name") or "")
        floor = compute_floor_for_minister(db, minister)
        dossier = db.get_dossier_for_secret_order(oid)
        prior_units = 0.0
        if dossier is not None:
            prior_units = float(db.sum_dossier_actual_progress_units(int(dossier["id"])))
        out.append({
            "order_id": oid,
            "minister_name": minister,
            "title": str(order.get("title") or ""),
            "floor": floor,
            "allowed_states": list(FIDELITY_STATES[_FIDELITY_INDEX[floor]:]),
            "prior_actual_units": prior_units,
            "due_turn": int(order.get("due_turn") or 0),
            "deadline_span": int(order.get("deadline_span") or 0),
        })
    return out


def _selection_map(raw_selections: object) -> Dict[int, Dict[str, object]]:
    mapping: Dict[int, Dict[str, object]] = {}
    for item in raw_selections or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("order_id", item.get("密令编号"))
        try:
            oid = int(raw_id)
        except (TypeError, ValueError):
            continue
        mapping[oid] = item
    return mapping


def apply_monthly_covert_actual_progress(
    db: Any,
    state: Any,
    *,
    selections: object = None,
    commit: bool = False,
) -> List[Dict[str, object]]:
    """当月实况轨落笔：底档 + 判官选态 clamp → actual_progress 行 + 在办迁移。

    与 apply_score_extraction 同 atomic 调用（commit=False）。
    不读/不写 dossier_progress_json；奏报仍走既有 0058 路径。
    """
    orders = list(db.list_secret_orders(status="active"))
    # 迁移窗：旧档 pending_review 仍可产当月实进度后对账
    orders.extend(db.list_secret_orders(status="pending_review"))
    by_sel = _selection_map(selections)
    applied: List[Dict[str, object]] = []
    turn = int(state.turn)
    for order in orders:
        oid = int(order["id"])
        dossier = db.get_dossier_for_secret_order(oid)
        if dossier is None:
            applied.append({
                "order_id": oid, "rejected": True, "reason": "密令缺少案卷",
            })
            continue
        # 已结案案卷不重复写月度实况
        if str(dossier.get("status") or "") == "closed":
            continue
        floor = compute_floor_for_minister(db, str(order.get("minister_name") or ""))
        sel = by_sel.get(oid) or {}
        selected = sel.get("fidelity", sel.get("执行态", sel.get("state")))
        fidelity = clamp_fidelity_to_floor(floor, selected)
        units = progress_units_for_state(fidelity)
        note = str(sel.get("note") or sel.get("备注") or "").strip()
        if not note:
            note = f"机械实进度：底档{floor}→落态{fidelity}（{units:g}）"
        row = db.record_dossier_actual_progress(
            int(dossier["id"]),
            turn,
            units=units,
            fidelity_state=fidelity,
            floor_state=floor,
            note=note,
            commit=False,
        )
        # 过程态：沿 mark_in_progress 既有特例进入 executing（不改 terminal policy 表）
        db.mark_secret_order_in_progress(oid, commit=False)
        applied.append({
            "order_id": oid,
            "dossier_id": int(dossier["id"]),
            "units": units,
            "fidelity": fidelity,
            "floor": floor,
            "row_id": row.get("id"),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return applied


def list_due_secret_orders_for_settlement(db: Any, state: Any) -> List[Dict[str, object]]:
    """可对账集：active|pending_review 且 due_turn∈(0, turn]。"""
    turn = int(state.turn)
    due: List[Dict[str, object]] = []
    for status in ("active", "pending_review"):
        for order in db.list_secret_orders(status=status):
            due_turn = int(order.get("due_turn") or 0)
            if due_turn > 0 and due_turn <= turn:
                due.append(order)
    due.sort(key=lambda o: int(o["id"]))
    return due


def settle_due_secret_orders(
    db: Any,
    state: Any,
    *,
    commit: bool = False,
) -> List[Dict[str, object]]:
    """settle_with_delta 尾部：当月实况已落后，只读实况轨对账并 close。"""
    results: List[Dict[str, object]] = []
    for order in list_due_secret_orders_for_settlement(db, state):
        oid = int(order["id"])
        dossier = db.get_dossier_for_secret_order(oid)
        if dossier is None:
            results.append({
                "order_id": oid, "rejected": True, "reason": "密令缺少案卷",
            })
            continue
        if str(order.get("status") or "") in {"done", "failed"}:
            continue
        did = int(dossier["id"])
        actual = float(db.sum_dossier_actual_progress_units(did))
        # deadline_span 优先；list 投影若无则回读
        span = int(order.get("deadline_span") or 0)
        if span <= 0:
            row = db.conn.execute(
                "SELECT deadline_span, due_turn FROM secret_orders WHERE id=?",
                (oid,),
            ).fetchone()
            if row is not None:
                span = int(row["deadline_span"] or 0)
        target = target_progress_units(
            deadline_span=span,
            due_turn=int(order.get("due_turn") or 0),
        )
        reports = list(db.list_dossier_progress(did))
        verdict = decide_secret_order_settlement({
            "actual_units": actual,
            "target_units": target,
            "criterion_text": str(order.get("title") or order.get("content") or "密令"),
            "has_reports": bool(reports),
            "origin_context": f"secret_order:{oid}",
        })
        db.close_secret_order(
            oid,
            str(verdict["status"]),
            str(verdict["note"]),
            int(state.turn),
            commit=False,
        )
        results.append({
            "order_id": oid,
            "dossier_id": did,
            "status": verdict["status"],
            "outcome": verdict["outcome"],
            "result": verdict["note"],
            "actual_units": actual,
            "target_units": target,
            "delivered": bool(verdict["delivered"]),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return results


def parse_covert_exec_selections(extracted: Mapping[str, object] | None) -> List[Dict[str, object]]:
    """从 extractor 合并产物取带内选态；兼容中英字段名。"""
    if not extracted:
        return []
    raw = (
        extracted.get("covert_exec_selections")
        or extracted.get("密令执行态")
        or []
    )
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, object]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out
