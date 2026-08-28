"""#1504 B 包：密令 covert 差务机械实进度 + 到期交付缺口对账。

真源：
- ADR 0116 意愿轴机械底档（loyalty + identity×0011-3 立场 + satisfaction/血债）
- ADR 0092 带内选态只准加重
- ADR 0073 实况轨（非 0058 奏报）
- ADR 0118 可数交付缺口；ADR 0120 done/failed 退役为到期对账派生
- Owner A：确认闸 typed covert-task contract → dossier payload；
  monthly typed actuals → dossier_actual_progress；无新表/第三轨/自由文本反解析

边界墙（本模块不做）：暴露累积器/逐档跳/成色轴 0108/透支账/谎报反噬纹理。
当月真实效果只经既有 extractor→applier＋origin 落库；本模块不发明固定后果套餐。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ming_sim.value_matrix import (
    mean_aligned_stance,
    normalize_axes,
    normalize_direction,
)

FIDELITY_STATES: tuple[str, ...] = ("忠实", "打折", "阳奉阴违", "反噬")
_FIDELITY_INDEX = {name: idx for idx, name in enumerate(FIDELITY_STATES)}

PROGRESS_UNITS: Dict[str, float] = {
    "忠实": 1.0,
    "打折": 0.5,
    "阳奉阴违": 0.0,
    "反噬": 0.0,
}

CONTRACT_KEY = "covert_task_contract"
CONTRACT_VERSION = 1
DEFAULT_KIND = "密令差务"
DEFAULT_AXES = ("实务事功",)
DEFAULT_UNIT = "countable_unit"
_STANCE_SCORE_SCALE = 18.0

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


def seed_guilt_counts_as_debt(seed_guilt: object) -> bool:
    if seed_guilt is None:
        return False
    if isinstance(seed_guilt, Mapping):
        guilt: object = seed_guilt
    else:
        text = str(seed_guilt).strip()
        if not text:
            return False
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return True
        if not isinstance(parsed, Mapping):
            return True
        guilt = parsed
    crime = str(guilt.get("crime") or "无").strip() or "无"
    severity = str(guilt.get("severity") or "无").strip() or "无"
    return not (crime == "无" and severity == "无")


def _int_axis(value: object, default: int = 50) -> int:
    if value is None:
        return int(default)
    return int(value)


def compute_willingness_floor(
    *,
    loyalty: int,
    identity: int,
    satisfaction: int,
    seed_guilt: object = "",
    faction: object = "",
    axes: object = None,
    direction: object = 1,
) -> str:
    loy = max(0, min(100, int(loyalty)))
    ident = max(0, min(100, int(identity)))
    sat = max(0, min(100, int(satisfaction)))
    axis_list = normalize_axes(axes)
    if not axis_list:
        axis_list = list(DEFAULT_AXES)
    direction_i = normalize_direction(direction, default=1)

    score = 0.55 * loy + 0.35 * sat
    aligned = mean_aligned_stance(faction, axis_list, direction=direction_i)
    score += (ident / 100.0) * aligned * _STANCE_SCORE_SCALE
    if ident >= 70 and loy < 55:
        score -= 18.0
    if seed_guilt_counts_as_debt(seed_guilt):
        score -= 12.0
    if score >= 70.0:
        return "忠实"
    if score >= 45.0:
        return "打折"
    if score >= 25.0:
        return "阳奉阴违"
    return "反噬"


def clamp_fidelity_to_floor(floor: object, selected: object) -> str:
    floor_name = normalize_fidelity_state(floor) or "反噬"
    selected_name = normalize_fidelity_state(selected)
    if selected_name is None:
        return floor_name
    if _FIDELITY_INDEX[selected_name] < _FIDELITY_INDEX[floor_name]:
        return floor_name
    return selected_name


def target_progress_units(*, deadline_span: int, due_turn: int, per_month: float = 1.0) -> float:
    if int(due_turn or 0) <= 0:
        return 0.0
    span = int(deadline_span or 0)
    months = float(max(span, 1))
    try:
        rate = float(per_month)
    except (TypeError, ValueError):
        rate = 1.0
    if rate <= 0.0:
        rate = 1.0
    return months * rate


def covert_task_from_payload(payload: object) -> Optional[Dict[str, object]]:
    """#1376 候选 payload → typed contract 字段；不读 tags / title / content。"""
    if not isinstance(payload, Mapping):
        return None
    nested = payload.get("covert_task")
    source: Mapping[str, object]
    if isinstance(nested, Mapping):
        source = nested
    else:
        source = payload
    kind = str(source.get("kind") or payload.get("kind") or "").strip()
    axes = source.get("axes")
    if axes is None:
        axes = payload.get("axes")
    delivery = source.get("delivery") if isinstance(source.get("delivery"), Mapping) else source
    unit = str(
        delivery.get("unit")
        or source.get("delivery_unit")
        or payload.get("delivery_unit")
        or ""
    ).strip()
    target = delivery.get("target_units")
    if target is None:
        target = source.get("delivery_target_units")
    if target is None:
        target = payload.get("delivery_target_units")
    direction = source.get("direction")
    if direction is None:
        direction = payload.get("direction")
    if not kind and not unit and target is None and not normalize_axes(axes):
        return None
    out: Dict[str, object] = {}
    if kind:
        out["kind"] = kind
    if axes is not None:
        out["axes"] = axes
    if direction is not None:
        out["direction"] = direction
    if unit:
        out["delivery_unit"] = unit
    if target is not None:
        out["delivery_target_units"] = target
    return out or None


def refresh_contract_target_units(
    prior: Mapping[str, object] | None,
    *,
    deadline_span: int,
    due_turn: int,
) -> float:
    """期限接缝：保已冻结可数目标；无期限保持 0；新到期且无目标则至少 1。"""
    frozen = 0.0
    if isinstance(prior, Mapping):
        delivery = prior.get("delivery")
        if isinstance(delivery, Mapping):
            try:
                frozen = float(delivery.get("target_units") or 0)
            except (TypeError, ValueError):
                frozen = 0.0
    due = int(due_turn or 0)
    if due <= 0:
        return frozen if frozen > 0.0 else 0.0
    if frozen > 0.0:
        return frozen
    return float(max(int(deadline_span or 0), 1))


def build_covert_task_contract(
    *,
    deadline_span: int,
    due_turn: int,
    tags: object = None,
    axes: object = None,
    direction: object = None,
    delivery_target_units: object = None,
    delivery_unit: object = None,
    action_type: str = "secret_order",
    kind: object = None,
    covert_task: object = None,
) -> Dict[str, object]:
    """确认闸一次生成的 typed covert-task contract（Owner A）。

    轴/方向/kind/可数交付只从候选显式字段或已冻结合同取，不解析 tags/title/content。
    """
    del tags  # 检索关键词，不是 kind 真源
    extracted = covert_task_from_payload({"covert_task": covert_task} if covert_task is not None else {})
    if extracted:
        kind = kind or extracted.get("kind")
        if axes is None:
            axes = extracted.get("axes")
        if direction is None:
            direction = extracted.get("direction")
        if delivery_unit is None:
            delivery_unit = extracted.get("delivery_unit")
        if delivery_target_units is None:
            delivery_target_units = extracted.get("delivery_target_units")
    resolved_kind = str(kind or "").strip() or DEFAULT_KIND
    axis_list = normalize_axes(axes)
    if not axis_list:
        axis_list = list(DEFAULT_AXES)
    direction_i = normalize_direction(direction, default=1)
    unit = str(delivery_unit or "").strip() or DEFAULT_UNIT
    due = int(due_turn or 0)
    if delivery_target_units is None:
        target = 0.0
    else:
        try:
            target = float(delivery_target_units)
        except (TypeError, ValueError):
            target = 0.0
        if target < 0.0:
            target = 0.0
    if due <= 0 and delivery_target_units is None:
        target = 0.0
    return {
        "version": CONTRACT_VERSION,
        "action_type": str(action_type or "secret_order"),
        "kind": resolved_kind,
        "axes": axis_list,
        "direction": direction_i,
        "delivery": {
            "unit": unit,
            "target_units": float(target),
            "target_per_month": 0.0,
        },
    }


def coerce_covert_task_contract(raw: object) -> Optional[Dict[str, object]]:
    if not isinstance(raw, Mapping):
        return None
    axes = normalize_axes(raw.get("axes"))
    if not axes:
        return None
    delivery = raw.get("delivery")
    if not isinstance(delivery, Mapping):
        return None
    try:
        target = float(delivery.get("target_units"))
    except (TypeError, ValueError):
        return None
    if target < 0.0:
        return None
    direction_i = normalize_direction(raw.get("direction"), default=1)
    unit = str(delivery.get("unit") or "progress_unit").strip() or "progress_unit"
    kind = str(raw.get("kind") or "").strip()
    if not kind:
        return None
    try:
        per_month = float(delivery.get("target_per_month") or 0)
    except (TypeError, ValueError):
        per_month = 0.0
    return {
        "version": int(raw.get("version") or CONTRACT_VERSION),
        "action_type": str(raw.get("action_type") or "secret_order"),
        "kind": kind,
        "axes": axes,
        "direction": direction_i,
        "delivery": {
            "unit": unit,
            "target_units": float(target),
            "target_per_month": per_month,
        },
    }


def read_covert_task_contract(dossier: Mapping[str, object] | None) -> Optional[Dict[str, object]]:
    if not isinstance(dossier, Mapping):
        return None
    payload = dossier.get("payload")
    if not isinstance(payload, Mapping):
        raw_json = dossier.get("payload_json")
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                loaded = json.loads(raw_json)
            except (TypeError, ValueError):
                loaded = None
            payload = loaded if isinstance(loaded, Mapping) else None
        else:
            payload = None
    if not isinstance(payload, Mapping):
        return None
    return coerce_covert_task_contract(payload.get(CONTRACT_KEY))


def contract_target_units(
    contract: Mapping[str, object] | None,
    *,
    deadline_span: int = 0,
    due_turn: int = 0,
) -> float:
    if isinstance(contract, Mapping):
        delivery = contract.get("delivery")
        if isinstance(delivery, Mapping):
            try:
                return float(delivery.get("target_units"))
            except (TypeError, ValueError):
                pass
    return target_progress_units(deadline_span=deadline_span, due_turn=due_turn)


def contract_axes_direction(
    contract: Mapping[str, object] | None,
) -> tuple[list[str], int]:
    if isinstance(contract, Mapping):
        axes = normalize_axes(contract.get("axes"))
        if axes:
            return axes, normalize_direction(contract.get("direction"), default=1)
    return list(DEFAULT_AXES), 1


def decide_secret_order_settlement(review_input: Mapping[str, object]) -> Dict[str, object]:
    actual = float(review_input.get("actual_units") or 0.0)
    target = float(review_input.get("target_units") or 0.0)
    has_reports = bool(review_input.get("has_reports"))
    origin = str(review_input.get("origin_context") or "").strip()

    delivered = target > 0.0 and actual + 1e-9 >= target
    if delivered:
        status = "done"
        outcome = "fulfilled"
        note = f"machine_settle delivered Σ={actual:g}/{target:g}"
    else:
        status = "failed"
        outcome = "failed"
        note = f"machine_settle gap Σ={actual:g}/{target:g}"
        if has_reports:
            note = f"{note};表报有之、不翻实账"
    if origin:
        note = f"{note} ({origin})"
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


def player_facing_secret_order_close_text(
    order: Mapping[str, object],
    reports: Sequence[Mapping[str, object]],
) -> str:
    existing = str(order.get("result") or "").strip()
    if existing:
        return existing
    for item in reversed(list(reports or [])):
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("memorial_text") or "").strip()
        if text:
            return text
    return ""


def build_minister_snapshot(db: Any, minister_name: str) -> Dict[str, object]:
    name = str(minister_name or "").strip()
    row = db.conn.execute(
        "SELECT loyalty, identity, faction, seed_guilt, status FROM characters WHERE name=?",
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
            "status": "",
            "present": False,
        }
    faction = str(row["faction"] or "")
    sat = 50
    if faction:
        try:
            sat = int(db.faction_satisfaction(faction))
        except Exception:
            sat = 50
    seed_raw: object = ""
    if "seed_guilt" in row.keys() and row["seed_guilt"] is not None:
        seed_raw = row["seed_guilt"]
    status = str(row["status"] or "") if "status" in row.keys() else ""
    return {
        "minister_name": name,
        "loyalty": _int_axis(row["loyalty"], 50),
        "identity": _int_axis(row["identity"], 50),
        "faction": faction,
        "satisfaction": int(sat),
        "seed_guilt": seed_raw,
        "status": status,
        "present": True,
    }


def minister_eligible_for_monthly_covert(db: Any, minister_name: str) -> bool:
    snap = build_minister_snapshot(db, minister_name)
    return bool(snap.get("present")) and str(snap.get("status") or "") == "active"


def compute_floor_for_minister(
    db: Any,
    minister_name: str,
    *,
    contract: Mapping[str, object] | None = None,
) -> str:
    snap = build_minister_snapshot(db, minister_name)
    axes, direction = contract_axes_direction(contract)
    return compute_willingness_floor(
        loyalty=int(snap["loyalty"]),
        identity=int(snap["identity"]),
        satisfaction=int(snap["satisfaction"]),
        seed_guilt=snap.get("seed_guilt") or "",
        faction=str(snap.get("faction") or ""),
        axes=axes,
        direction=direction,
    )


def _order_contract(db: Any, order: Mapping[str, object]) -> Optional[Dict[str, object]]:
    oid = int(order.get("id") or 0)
    dossier = db.get_dossier_for_secret_order(oid) if oid > 0 else None
    contract = read_covert_task_contract(dossier)
    if contract is not None:
        return contract
    return build_covert_task_contract(
        deadline_span=int(order.get("deadline_span") or 0),
        due_turn=int(order.get("due_turn") or 0),
    )


def build_secret_covert_effect_briefs(db: Any, orders: Sequence[Mapping[str, object]] | None = None) -> List[Dict[str, object]]:
    """internal 档房私密输入：typed 合同 + origin，不含密令正文（#883）。"""
    rows = list(orders or [])
    if not rows:
        rows = list(db.list_secret_orders(status="active"))
    out: List[Dict[str, object]] = []
    for order in rows:
        if not isinstance(order, Mapping):
            continue
        if str(order.get("status") or "active") != "active":
            continue
        oid = int(order.get("id") or 0)
        if oid <= 0:
            continue
        dossier = db.get_dossier_for_secret_order(oid)
        if dossier is None:
            continue
        contract = read_covert_task_contract(dossier) or build_covert_task_contract(
            deadline_span=int(order.get("deadline_span") or 0),
            due_turn=int(order.get("due_turn") or 0),
        )
        delivery = contract.get("delivery") if isinstance(contract.get("delivery"), Mapping) else {}
        unit = str(delivery.get("unit") or "")
        fields = canonical_fields_for_delivery(
            unit=unit, kind=str(contract.get("kind") or ""),
        )
        owner = "internal"
        if fields == ["人物变更"]:
            owner = "personnel_secret"
        out.append({
            "origin_ref": f"dossier:{int(dossier['id'])}",
            "order_id": oid,
            "kind": str(contract.get("kind") or ""),
            "axes": list(contract.get("axes") or []),
            "direction": int(contract.get("direction") or 1),
            "delivery": {
                "unit": unit,
                "target_units": float(delivery.get("target_units") or 0),
            },
            "effect_owner": owner,
            "canonical_fields": fields,
        })
    return out


def canonical_fields_for_delivery(*, unit: object = None, kind: object = None) -> List[str]:
    """差务可数单位 → 既有 extractor 字段/applier，不发明第三轨。"""
    del kind
    u = str(unit or "").strip()
    if u in {"两", "银两", "饷银"}:
        return ["economy_moves"]
    if u == "人犯":
        return ["人物变更"]
    if u == "亩":
        return ["region_delta"]
    return []


def originated_quantity_this_turn(
    db: Any,
    dossier_id: int,
    turn: int,
    contract: Mapping[str, object] | None,
) -> float:
    """当月 origin-linked canonical 效果的可数实物量（与合同 unit 同量纲）。"""
    did = int(dossier_id)
    current = int(turn)
    origin = f"dossier:{did}"
    delivery = contract.get("delivery") if isinstance(contract, Mapping) else None
    unit = ""
    if isinstance(delivery, Mapping):
        unit = str(delivery.get("unit") or "")
    kind = str((contract or {}).get("kind") or "") if isinstance(contract, Mapping) else ""
    fields = canonical_fields_for_delivery(unit=unit, kind=kind)
    qty = 0.0
    if "economy_moves" in fields:
        for item in db.list_economy_moves_for_dossier(did):
            if int(item.get("turn") or 0) == current:
                try:
                    qty += abs(float(item.get("delta") or 0))
                except (TypeError, ValueError):
                    continue
    if "fiscal_changes" in fields:
        for item in db.list_fiscal_effects_for_dossier(did):
            if int(item.get("turn") or 0) == current:
                try:
                    qty += abs(float(item.get("delta") or 0))
                except (TypeError, ValueError):
                    continue
    if "人物变更" in fields:
        rows = db.conn.execute(
            "SELECT id FROM person_logs WHERE origin_ref=? AND turn=?",
            (origin, current),
        ).fetchall()
        qty += float(len(rows))
    if "region_delta" in fields:
        rows = db.conn.execute(
            "SELECT delta FROM region_logs WHERE origin_ref=? AND turn=?",
            (origin, current),
        ).fetchall()
        for row in rows:
            try:
                qty += abs(float(row["delta"] or 0))
            except (TypeError, ValueError, KeyError):
                continue
    return qty


def monthly_actual_units(*, fidelity: object, originated_quantity: float) -> float:
    """实进度 = 执行格份额 × 当月 canonical 可数量。无 origin 实物则空转 0。"""
    try:
        quantity = float(originated_quantity or 0)
    except (TypeError, ValueError):
        quantity = 0.0
    if quantity <= 0.0:
        return 0.0
    return progress_units_for_state(fidelity) * quantity


def build_covert_floor_payload(db: Any, orders: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        oid = int(order.get("id") or 0)
        if oid <= 0:
            continue
        status = str(order.get("status") or "")
        if status != "active":
            continue
        minister = str(order.get("minister_name") or "")
        contract = _order_contract(db, order)
        floor = compute_floor_for_minister(db, minister, contract=contract)
        dossier = db.get_dossier_for_secret_order(oid)
        prior_units = 0.0
        target_units = contract_target_units(
            contract,
            deadline_span=int(order.get("deadline_span") or 0),
            due_turn=int(order.get("due_turn") or 0),
        )
        if dossier is not None:
            prior_units = float(db.sum_dossier_actual_progress_units(int(dossier["id"])))
        axes, direction = contract_axes_direction(contract)
        out.append({
            "order_id": oid,
            "minister_name": minister,
            "title": str(order.get("title") or ""),
            "floor": floor,
            "allowed_states": list(FIDELITY_STATES[_FIDELITY_INDEX[floor]:]),
            "prior_actual_units": prior_units,
            "target_units": target_units,
            "kind": str((contract or {}).get("kind") or ""),
            "axes": axes,
            "direction": direction,
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
    """当月实况轨落笔：clamp 执行态 + 当月 origin 真实效果 → dossier_actual_progress。

    不发明人物/钱粮/地区固定套餐；奏报永不入 apply。
    """
    orders = list(db.list_secret_orders(status="active"))
    by_sel = _selection_map(selections)
    applied: List[Dict[str, object]] = []
    turn = int(state.turn)
    for order in orders:
        oid = int(order["id"])
        if int(order.get("turn_issued") or 0) == turn:
            continue
        minister = str(order.get("minister_name") or "")
        if not minister_eligible_for_monthly_covert(db, minister):
            applied.append({
                "order_id": oid,
                "skipped": True,
                "reason": "承办人不在场或非 active",
            })
            continue
        dossier = db.get_dossier_for_secret_order(oid)
        if dossier is None:
            applied.append({
                "order_id": oid, "rejected": True, "reason": "密令缺少案卷",
            })
            continue
        if str(dossier.get("status") or "") == "closed":
            continue
        did = int(dossier["id"])
        contract = read_covert_task_contract(dossier) or build_covert_task_contract(
            deadline_span=int(order.get("deadline_span") or 0),
            due_turn=int(order.get("due_turn") or 0),
        )
        floor = compute_floor_for_minister(db, minister, contract=contract)
        sel = by_sel.get(oid) or {}
        selected = sel.get("fidelity", sel.get("执行态", sel.get("state")))
        fidelity = clamp_fidelity_to_floor(floor, selected)
        originated = originated_quantity_this_turn(db, did, turn, contract)
        units = monthly_actual_units(
            fidelity=fidelity, originated_quantity=originated,
        )
        note = str(sel.get("note") or sel.get("备注") or "").strip()
        if not note:
            note = (
                f"机械实进度：底档{floor}→落态{fidelity}（{units:g}）"
                f"；origin_effects={originated}"
            )
        row = db.record_dossier_actual_progress(
            did,
            turn,
            units=units,
            fidelity_state=fidelity,
            floor_state=floor,
            note=note,
            commit=False,
        )
        db.mark_secret_order_in_progress(oid, commit=False)
        applied.append({
            "order_id": oid,
            "dossier_id": did,
            "units": units,
            "fidelity": fidelity,
            "floor": floor,
            "row_id": row.get("id"),
            "originated_quantity": originated,
            "target_units": contract_target_units(
                contract,
                deadline_span=int(order.get("deadline_span") or 0),
                due_turn=int(order.get("due_turn") or 0),
            ),
            "contract_kind": contract.get("kind"),
            "contract_axes": list(contract.get("axes") or []),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return applied


def list_due_secret_orders_for_settlement(db: Any, state: Any) -> List[Dict[str, object]]:
    turn = int(state.turn)
    due: List[Dict[str, object]] = []
    for order in db.list_secret_orders(status="active"):
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
        span = int(order.get("deadline_span") or 0)
        if span <= 0:
            row = db.conn.execute(
                "SELECT deadline_span, due_turn FROM secret_orders WHERE id=?",
                (oid,),
            ).fetchone()
            if row is not None:
                span = int(row["deadline_span"] or 0)
        contract = read_covert_task_contract(dossier) or build_covert_task_contract(
            deadline_span=span,
            due_turn=int(order.get("due_turn") or 0),
        )
        target = contract_target_units(
            contract,
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
        player_text = player_facing_secret_order_close_text(order, reports)
        db.close_secret_order(
            oid,
            str(verdict["status"]),
            player_text,
            int(state.turn),
            commit=False,
        )
        results.append({
            "order_id": oid,
            "dossier_id": did,
            "status": verdict["status"],
            "outcome": verdict["outcome"],
            "result": player_text,
            "note": verdict["note"],
            "actual_units": actual,
            "target_units": target,
            "delivered": bool(verdict["delivered"]),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return results


def parse_covert_exec_selections(extracted: Mapping[str, object] | None) -> List[Dict[str, object]]:
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
