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

import copy
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ming_sim.constants import ECONOMY_ACCOUNTS, REGION_FIELD_ALIASES
from ming_sim.person_archive_contract import PERSON_ACTIONS, PERSON_LEGAL_REASON_CODES
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
_STANCE_SCORE_SCALE = 18.0
CANONICAL_UNITS = ("万两", "人犯", "万亩")
FACT_LANES_KEY = "fact_lanes"
INVESTIGATION_PROVENANCE_KEY = "investigation_provenance"
DEFAULT_SUBSTANTIATION_REASON = "依律"
_FIELD_FOR_UNIT = {
    "万两": ["economy_moves"],
    "人犯": ["人物变更"],
    "万亩": ["region_delta"],
}
_IDENTITY_FOR_UNIT = {
    "万两": ("purpose", "category", "account"),
    "人犯": ("person_action",),
    "万亩": ("region", "field", "target"),
}


class CovertContractError(ValueError):
    """确认闸未冻结合同，或后续读端找不到可落库合同。"""

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
        axis_list = ["实务事功"]
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
    effect_sign = delivery.get("effect_sign")
    if effect_sign is None:
        effect_sign = source.get("effect_sign")
    purpose = delivery.get("purpose")
    if purpose is None:
        purpose = source.get("purpose")
    category = delivery.get("category")
    if category is None:
        category = source.get("category")
    account = delivery.get("account")
    if account is None:
        account = source.get("account")
    region = delivery.get("region")
    if region is None:
        region = source.get("region")
    field = delivery.get("field")
    if field is None:
        field = source.get("field")
    region_target = delivery.get("target")
    if region_target is None:
        region_target = source.get("target")
    person_action = delivery.get("person_action")
    if person_action is None:
        person_action = source.get("person_action")
    investigation_target = str(
        delivery.get("investigation_target")
        or source.get("investigation_target")
        or payload.get("investigation_target")
        or ""
    ).strip()
    if not kind and not unit and target is None and not normalize_axes(axes) and not investigation_target:
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
    if effect_sign is not None:
        out["effect_sign"] = effect_sign
    if purpose is not None:
        out["purpose"] = purpose
    if category is not None:
        out["category"] = category
    if account is not None:
        out["account"] = account
    if region is not None:
        out["region"] = region
    if field is not None:
        out["field"] = field
    if region_target is not None:
        out["target"] = region_target
    if person_action is not None:
        out["person_action"] = person_action
    if investigation_target:
        out["investigation_target"] = investigation_target
    return out or None


def canonicalize_delivery_unit(unit: object, target: object) -> tuple[str, float]:
    raw = str(unit or "").strip()
    try:
        qty = float(target)
    except (TypeError, ValueError):
        raise CovertContractError("密令确认缺少可数交付目标") from None
    if qty <= 0.0:
        raise CovertContractError("密令确认交付目标必须为正数")
    if raw not in CANONICAL_UNITS:
        raise CovertContractError("密令确认交付单位须为万两/人犯/万亩")
    return raw, float(qty)


def _require_effect_sign(raw: object) -> int:
    try:
        sign = int(raw)
    except (TypeError, ValueError):
        raise CovertContractError("密令确认缺少效果符号") from None
    if sign not in (-1, 1):
        raise CovertContractError("密令确认效果符号须为 +1 或 -1")
    return sign


def canonicalize_economy_purpose(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        raise CovertContractError("密令确认交付 identity 缺少：purpose")
    if text == "补饷":
        return "补饷"
    return "其它"


def build_covert_task_contract(
    *,
    deadline_span: int = 0,
    due_turn: int = 0,
    tags: object = None,
    axes: object = None,
    direction: object = None,
    delivery_target_units: object = None,
    delivery_unit: object = None,
    action_type: str = "secret_order",
    kind: object = None,
    covert_task: object = None,
    effect_sign: object = None,
    purpose: object = None,
    category: object = None,
    account: object = None,
    region: object = None,
    field: object = None,
    region_target: object = None,
    person_action: object = None,
    investigation_target: object = None,
) -> Dict[str, object]:
    """确认闸一次生成可被 canonical applier 接受的 typed contract。缺字段响亮失败。"""
    del tags, deadline_span, due_turn
    extracted = covert_task_from_payload(
        {"covert_task": covert_task} if covert_task is not None else {},
    )
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
        if effect_sign is None:
            effect_sign = extracted.get("effect_sign")
        if purpose is None:
            purpose = extracted.get("purpose")
        if category is None:
            category = extracted.get("category")
        if account is None:
            account = extracted.get("account")
        if region is None:
            region = extracted.get("region")
        if field is None:
            field = extracted.get("field")
        if region_target is None:
            region_target = extracted.get("target")
        if person_action is None:
            person_action = extracted.get("person_action")
        if investigation_target is None:
            investigation_target = extracted.get("investigation_target")
    resolved_kind = str(kind or "").strip()
    if not resolved_kind:
        raise CovertContractError("密令确认缺少差务类型")
    axis_list = normalize_axes(axes)
    if not axis_list:
        raise CovertContractError("密令确认缺少价值轴")
    direction_i = normalize_direction(direction, default=1)
    inv_target = str(investigation_target or "").strip()
    if inv_target:
        try:
            qty = float(delivery_target_units)
        except (TypeError, ValueError):
            raise CovertContractError("密令确认缺少可数交付目标") from None
        if qty <= 0.0:
            raise CovertContractError("密令确认交付目标必须为正数")
        delivery = {
            "target_units": float(qty),
            "effect_sign": _require_effect_sign(effect_sign),
            "canonical_fields": [],
            "investigation_target": inv_target,
        }
        return {
            "version": CONTRACT_VERSION,
            "action_type": str(action_type or "secret_order"),
            "kind": resolved_kind,
            "axes": axis_list,
            "direction": direction_i,
            "investigation_target": inv_target,
            "delivery": delivery,
        }
    unit, target = canonicalize_delivery_unit(delivery_unit, delivery_target_units)
    delivery: Dict[str, object] = {
        "unit": unit,
        "target_units": float(target),
        "effect_sign": _require_effect_sign(effect_sign),
        "canonical_fields": list(_FIELD_FOR_UNIT[unit]),
    }
    if unit == "万两":
        delivery["purpose"] = canonicalize_economy_purpose(purpose)
    category_text = str(category or "").strip()
    if category_text:
        delivery["category"] = category_text
    account_text = str(account or "").strip()
    if account_text:
        if account_text not in ECONOMY_ACCOUNTS:
            raise CovertContractError("密令确认钱粮账户须为国库或内库")
        delivery["account"] = account_text
    region_text = str(region or "").strip()
    if region_text:
        delivery["region"] = region_text
    field_text = str(field or "").strip()
    if field_text:
        canonical_field = REGION_FIELD_ALIASES.get(field_text)
        if not canonical_field:
            raise CovertContractError("密令确认地区字段不在闭集")
        delivery["field"] = canonical_field
    target_text = str(region_target or "").strip()
    if target_text:
        delivery["target"] = target_text
    action_text = str(person_action or "").strip()
    if action_text:
        if action_text not in PERSON_ACTIONS:
            raise CovertContractError("密令确认人物动作不在闭集")
        delivery["person_action"] = action_text
    missing_identity = [key for key in _IDENTITY_FOR_UNIT[unit] if not delivery.get(key)]
    if missing_identity:
        raise CovertContractError(
            f"密令确认交付 identity 缺少：{','.join(missing_identity)}"
        )
    return {
        "version": CONTRACT_VERSION,
        "action_type": str(action_type or "secret_order"),
        "kind": resolved_kind,
        "axes": axis_list,
        "direction": direction_i,
        "delivery": delivery,
    }


def coerce_covert_task_contract(raw: object) -> Optional[Dict[str, object]]:
    """Validate a frozen contract without rebuilding or supplying read-time defaults."""
    if not isinstance(raw, Mapping) or raw.get("version") != CONTRACT_VERSION:
        return None
    delivery = raw.get("delivery")
    if not isinstance(delivery, Mapping):
        return None
    if not str(raw.get("kind") or "").strip() or not normalize_axes(raw.get("axes")):
        return None
    if raw.get("direction") not in (-1, 1):
        return None
    inv_target = str(
        raw.get("investigation_target") or delivery.get("investigation_target") or ""
    ).strip()
    if inv_target:
        try:
            qty = float(delivery.get("target_units"))
        except (TypeError, ValueError):
            return None
        if qty <= 0.0:
            return None
        if delivery.get("effect_sign") not in (-1, 1):
            return None
        if list(delivery.get("canonical_fields") or []):
            return None
        if str(delivery.get("investigation_target") or "").strip() != inv_target:
            return None
        return copy.deepcopy(dict(raw))
    try:
        unit, target = canonicalize_delivery_unit(
            delivery.get("unit"), delivery.get("target_units"),
        )
    except CovertContractError:
        return None
    if delivery.get("effect_sign") not in (-1, 1):
        return None
    if list(delivery.get("canonical_fields") or []) != canonical_fields_for_delivery(unit=unit):
        return None
    if float(delivery.get("target_units")) != target:
        return None
    if any(not delivery.get(key) for key in _IDENTITY_FOR_UNIT[unit]):
        return None
    return copy.deepcopy(dict(raw))


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


def require_covert_task_contract(dossier: Mapping[str, object] | None) -> Dict[str, object]:
    contract = read_covert_task_contract(dossier)
    if contract is None:
        raise CovertContractError("密令案卷缺少完整 typed covert-task contract")
    return contract


def contract_target_units(contract: Mapping[str, object]) -> float:
    delivery = contract.get("delivery")
    if not isinstance(delivery, Mapping):
        raise CovertContractError("typed contract 缺少 delivery")
    try:
        target = float(delivery.get("target_units"))
    except (TypeError, ValueError) as exc:
        raise CovertContractError("typed contract 缺少可数目标") from exc
    if target <= 0.0:
        raise CovertContractError("typed contract 目标必须为正数")
    return target


def contract_axes_direction(
    contract: Mapping[str, object],
) -> tuple[list[str], int]:
    axes = normalize_axes(contract.get("axes"))
    if not axes:
        raise CovertContractError("typed contract 缺少价值轴")
    return axes, normalize_direction(contract.get("direction"), default=1)


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
    del order
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
    contract: Mapping[str, object],
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


def _order_contract(db: Any, order: Mapping[str, object]) -> Dict[str, object]:
    oid = int(order.get("id") or 0)
    dossier = db.get_dossier_for_secret_order(oid) if oid > 0 else None
    return require_covert_task_contract(dossier)


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
        contract = require_covert_task_contract(dossier)
        delivery = contract.get("delivery") if isinstance(contract.get("delivery"), Mapping) else {}
        unit = str(delivery.get("unit") or "")
        fields = canonical_fields_for_delivery(unit=unit)
        owner = "internal"
        if fields == ["人物变更"]:
            owner = "personnel_secret"
        out.append({
            "origin_ref": f"dossier:{int(dossier['id'])}",
            "order_id": oid,
            "kind": str(contract.get("kind") or ""),
            "axes": list(contract.get("axes") or []),
            "direction": int(contract.get("direction") or 1),
            "delivery": copy.deepcopy(dict(delivery)),
            "effect_owner": owner,
            "canonical_fields": fields,
        })
    return out


def canonical_fields_for_delivery(*, unit: object = None) -> List[str]:
    """差务可数单位 → 既有 extractor 字段/applier，不发明第三轨。"""
    return list(_FIELD_FOR_UNIT.get(str(unit or "").strip(), []))


def _delivery_matches_economy(item: Mapping[str, object], delivery: Mapping[str, object]) -> bool:
    try:
        delta = float(item.get("delta") or 0)
    except (TypeError, ValueError):
        return False
    sign = int(delivery.get("effect_sign") or 0)
    if sign < 0 and delta >= 0:
        return False
    if sign > 0 and delta <= 0:
        return False
    purpose = str(delivery.get("purpose") or "").strip()
    if str(item.get("purpose") or "").strip() != purpose:
        return False
    category = str(delivery.get("category") or "").strip()
    if str(item.get("category") or "").strip() != category:
        return False
    account = str(delivery.get("account") or "").strip()
    if str(item.get("account") or "").strip() != account:
        return False
    return True


def _delivery_matches_region(row: Mapping[str, object], delivery: Mapping[str, object]) -> bool:
    try:
        delta = float(row["delta"] or 0)
    except (TypeError, ValueError, KeyError):
        return False
    sign = int(delivery.get("effect_sign") or 0)
    return (
        ((sign < 0 and delta < 0) or (sign > 0 and delta > 0))
        and str(row["region_id"] or "") == str(delivery.get("region") or "")
        and str(row["field"] or "") == str(delivery.get("field") or "")
    )


def _dossier_payload_map(db: Any, dossier_id: int) -> Dict[str, object]:
    row = db.conn.execute(
        "SELECT payload_json FROM decree_dossiers WHERE id=?",
        (int(dossier_id),),
    ).fetchone()
    if row is None:
        return {}
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except (TypeError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def live_investigation_fact_keys(db: Any, target: str) -> List[str]:
    name = str(target or "").strip()
    if not name:
        return []
    keys: List[str] = []
    row = db.conn.execute(
        "SELECT seed_guilt FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    if row is not None and seed_guilt_counts_as_debt(row["seed_guilt"]):
        keys.append(name)
    for edge in db.get_relation_edge_events(person=name, evidence=True):
        keys.append(str(int(edge["id"])))
    return keys


def _lanes_from_payload(payload: Mapping[str, object]) -> List[Dict[str, object]]:
    raw = payload.get(FACT_LANES_KEY)
    lanes: List[Dict[str, object]] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("fact_key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                progress = float(item.get("progress") or 0.0)
            except (TypeError, ValueError):
                progress = 0.0
            reason = str(item.get("reason_code") or "").strip()
            legal = reason in PERSON_LEGAL_REASON_CODES
            lanes.append({
                "fact_key": key,
                "progress": max(0.0, progress),
                "used": bool(item.get("used")) and legal,
                "reason_code": reason if legal else "",
            })
    return lanes


def globally_used_fact_keys(db: Any, *, except_dossier_id: int = 0) -> set[str]:
    used: set[str] = set()
    rows = db.conn.execute(
        "SELECT id, payload_json FROM decree_dossiers",
    ).fetchall()
    skip = int(except_dossier_id or 0)
    for row in rows:
        if skip and int(row["id"] or 0) == skip:
            continue
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        for lane in _lanes_from_payload(payload):
            if lane.get("used"):
                used.add(str(lane["fact_key"]))
    return used


def _write_fact_lanes(
    db: Any, dossier_id: int, lanes: Sequence[Mapping[str, object]], *, commit: bool = False,
) -> None:
    payload = _dossier_payload_map(db, dossier_id)
    payload[FACT_LANES_KEY] = [
        {
            "fact_key": str(lane["fact_key"]),
            "progress": float(lane.get("progress") or 0.0),
            "used": bool(lane.get("used")),
            "reason_code": str(lane.get("reason_code") or ""),
        }
        for lane in lanes
    ]
    db.update_decree_dossier_payload(int(dossier_id), payload, commit=commit)


def seed_investigation_fact_lanes(
    db: Any, dossier_id: int, target: str, *, commit: bool = False,
) -> List[Dict[str, object]]:
    payload = _dossier_payload_map(db, dossier_id)
    lanes = _lanes_from_payload(payload)
    seen = {str(lane["fact_key"]) for lane in lanes}
    for key in live_investigation_fact_keys(db, target):
        if key in seen:
            continue
        lanes.append({"fact_key": key, "progress": 0.0, "used": False})
        seen.add(key)
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)
    return lanes


def _substantiate_lane(lane: Dict[str, object]) -> None:
    code = DEFAULT_SUBSTANTIATION_REASON if DEFAULT_SUBSTANTIATION_REASON in PERSON_LEGAL_REASON_CODES else ""
    lane["progress"] = 1.0
    lane["reason_code"] = code
    lane["used"] = bool(code)


def read_substantiated_legal_reason_code(
    db: Any, target: str, fact_key: str,
) -> str:
    """D4-4 consumption: legal-set reason_code for a substantiated fact lane."""
    name = str(target or "").strip()
    key = str(fact_key or "").strip()
    if not name or not key:
        return ""
    rows = db.conn.execute("SELECT id, payload_json FROM decree_dossiers").fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        contract = payload.get(CONTRACT_KEY) if isinstance(payload.get(CONTRACT_KEY), Mapping) else {}
        if _investigation_target_of(contract) != name:
            continue
        for lane in _lanes_from_payload(payload):
            if str(lane["fact_key"]) != key:
                continue
            code = str(lane.get("reason_code") or "").strip()
            if float(lane.get("progress") or 0.0) >= 1.0 and code in PERSON_LEGAL_REASON_CODES:
                return code
    return ""


def mark_investigation_fact_used(
    db: Any, dossier_id: int, fact_key: str, *, commit: bool = False,
) -> None:
    key = str(fact_key)
    lanes = _lanes_from_payload(_dossier_payload_map(db, dossier_id))
    found = False
    for lane in lanes:
        if str(lane["fact_key"]) == key:
            _substantiate_lane(lane)
            found = True
            break
    if not found:
        lane = {"fact_key": key}
        _substantiate_lane(lane)
        lanes.append(lane)
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)


def investigation_lane_actual_units(db: Any, dossier_id: int) -> float:
    return float(
        sum(1 for lane in _lanes_from_payload(_dossier_payload_map(db, dossier_id)) if lane.get("used"))
    )


def advance_investigation_lanes(
    db: Any,
    dossier_id: int,
    target: str,
    fidelity: object,
    *,
    commit: bool = False,
) -> tuple[float, str]:
    increment = progress_units_for_state(fidelity)
    lanes = seed_investigation_fact_lanes(db, dossier_id, target, commit=False)
    if increment <= 0.0:
        return 0.0, ""
    blocked = globally_used_fact_keys(db, except_dossier_id=int(dossier_id))
    bound = ""
    units = 0.0
    for lane in lanes:
        key = str(lane["fact_key"])
        if lane.get("used") or key in blocked:
            continue
        if key not in live_investigation_fact_keys(db, target):
            continue
        progress = float(lane.get("progress") or 0.0) + increment
        if progress >= 1.0:
            _substantiate_lane(lane)
        else:
            lane["progress"] = progress
        bound = key
        units = increment
        break
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)
    return units, bound


def _investigation_target_of(contract: Mapping[str, object]) -> str:
    delivery = contract.get("delivery") if isinstance(contract.get("delivery"), Mapping) else {}
    return str(
        contract.get("investigation_target") or delivery.get("investigation_target") or ""
    ).strip()


def find_active_investigation_order_id(db: Any, target: str) -> int:
    name = str(target or "").strip()
    if not name:
        return 0
    for order in db.list_secret_orders(status="active"):
        dossier = db.get_dossier_for_secret_order(int(order["id"]))
        if dossier is None:
            continue
        contract = read_covert_task_contract(dossier)
        if not contract:
            continue
        if _investigation_target_of(contract) == name:
            return int(order["id"])
    return 0


def merge_investigation_confirmation(
    db: Any,
    state: Any,
    order_id: int,
    *,
    pending_action_id: int = 0,
    origin_chat_message_ids: Sequence[int] = (),
    commit: bool = False,
) -> int:
    dossier = db.get_dossier_for_secret_order(int(order_id))
    if dossier is None:
        raise CovertContractError("查案合流缺少案卷")
    payload = _dossier_payload_map(db, int(dossier["id"]))
    sources = payload.get(INVESTIGATION_PROVENANCE_KEY)
    if not isinstance(sources, list):
        sources = []
    sources.append({
        "pending_action_id": int(pending_action_id or 0),
        "origin_chat_message_ids": [int(x) for x in origin_chat_message_ids],
        "turn": int(getattr(state, "turn", 0) or 0),
    })
    payload[INVESTIGATION_PROVENANCE_KEY] = sources
    db.update_decree_dossier_payload(int(dossier["id"]), payload, commit=commit)
    return int(order_id)


def originated_quantity_this_turn(
    db: Any,
    dossier_id: int,
    turn: int,
    contract: Mapping[str, object],
) -> float:
    """当月 origin-linked canonical 效果的可数实物量（与合同 unit 同量纲）。"""
    did = int(dossier_id)
    current = int(turn)
    origin = f"dossier:{did}"
    delivery = contract.get("delivery") if isinstance(contract.get("delivery"), Mapping) else {}
    unit = str(delivery.get("unit") or "")
    fields = canonical_fields_for_delivery(unit=unit)
    qty = 0.0
    if "economy_moves" in fields:
        for item in db.list_economy_moves_for_dossier(did):
            if int(item.get("turn") or 0) != current:
                continue
            if not _delivery_matches_economy(item, delivery):
                continue
            try:
                qty += abs(float(item.get("delta") or 0))
            except (TypeError, ValueError):
                continue
    if "人物变更" in fields:
        action = str(delivery.get("person_action") or "").strip()
        rows = db.conn.execute(
            "SELECT id FROM person_logs WHERE origin_ref=? AND turn=? AND action=?",
            (origin, current, action),
        ).fetchall()
        qty += float(len(rows))
    if "region_delta" in fields:
        rows = db.conn.execute(
            "SELECT region_id, field, new_value, delta FROM region_logs "
            "WHERE origin_ref=? AND turn=?",
            (origin, current),
        ).fetchall()
        for row in rows:
            if _delivery_matches_region(row, delivery):
                qty += abs(float(row["delta"] or 0))
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
        target_units = contract_target_units(contract)
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
        contract = require_covert_task_contract(dossier)
        floor = compute_floor_for_minister(db, minister, contract=contract)
        sel = by_sel.get(oid) or {}
        selected = sel.get("fidelity", sel.get("执行态", sel.get("state")))
        fidelity = clamp_fidelity_to_floor(floor, selected)
        inv_target = _investigation_target_of(contract)
        bound_key = ""
        if inv_target:
            seed_investigation_fact_lanes(db, did, inv_target, commit=False)
            units, bound_key = advance_investigation_lanes(
                db, did, inv_target, fidelity, commit=False,
            )
            originated = 1.0 if units > 0.0 else 0.0
        else:
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
            "target_units": contract_target_units(contract),
            "contract_kind": contract.get("kind"),
            "contract_axes": list(contract.get("axes") or []),
            "fact_key": bound_key,
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
        contract = require_covert_task_contract(dossier)
        if _investigation_target_of(contract):
            actual = investigation_lane_actual_units(db, did)
        else:
            actual = float(db.sum_dossier_actual_progress_units(did))
        target = contract_target_units(contract)
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
