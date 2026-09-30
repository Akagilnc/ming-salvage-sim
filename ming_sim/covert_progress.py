"""#1504 B 包：密令 covert 差务机械实进度 + 到期交付缺口对账。

真源：
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
from ming_sim.materials import secret_order_origin
from ming_sim.person_archive_contract import PERSON_ACTIONS, PERSON_LEGAL_REASON_CODES
from ming_sim.value_matrix import (
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
CANONICAL_UNITS = ("万两", "人犯", "万亩")
FACT_LANES_KEY = "fact_lanes"
INVESTIGATION_PROVENANCE_KEY = "investigation_provenance"
DEFAULT_SUBSTANTIATION_REASON = "依律"

# #1896 逐证难度：首版常数随 playtest（同 0011-4 D4-6 先例），本 ADR 不发明精确值。
# 真相底两类事实的基准难度不同：seed_guilt 是一条待坐实的罪谱，把柄边是已落库的
# 实物/证词边（结构化事件产），后者更难撬——ADR 0098 后出修订只保"实有罪证"与
# 逐证核算，不保任何统一阈值，故此处按事实分档而非一把尺。
_FACT_DIFFICULTY_SEED_GUILT = 1.0
_FACT_DIFFICULTY_EVIDENCE_EDGE = 1.4
_SEVERITY_MULTIPLIER = {"轻": 0.8, "中": 1.0, "重": 1.3}
_NETWORK_PER_EDGE = 0.05
_NETWORK_EDGE_CAP = 10
_TRAVEL_PER_UNIT = 0.08
_TRAVEL_TIME_CAP = 12.0
_ABILITY_REFERENCE = 60.0
_SPOILED_HARDER_MULTIPLIER = 1.5
_MIN_DIFFICULTY = 0.1

# #1896 月度投入的引擎侧边界：人物只声明"下了多大劲"（0..1 的强度，人心的选择），
# 引擎按其真实状态折算本月实投并 clamp——P6「代码只做供事实、clamp、记账」。
# 模型不得直采一个裸浮点当月坐实任意罪证（深挖也不是无限深挖）。
_MONTHLY_EFFORT_CAP = 0.6
_CAPACITY_MIN = 0.3
_CAPACITY_MAX = 1.2
_ABILITY_CAPACITY_WEIGHT = 0.5
_ABILITY_CAPACITY_REFERENCE = 60.0
_TRANSIT_CAPACITY_PENALTY = 0.5   # 在途未到差
_BANDWIDTH_PER_ERRAND = 0.15      # 0092 带宽①：未结差务越多，本案可分到的越少
_BANDWIDTH_ERRAND_CAP = 3
# 坐实最低在查月数：堵"一月速坐实"，并保住 0100 毁证／惊蛇窗口（0098 轨级口径 iii）。
_MIN_MONTHS_UNDER_INVESTIGATION = 2

_DISTANCE_MATRIX: Any = None


def _distance_matrix() -> Any:
    """烘焙行程矩阵只读一次（进程内缓存）：难度按 lane 逐条核算，别每条重读文件。"""
    global _DISTANCE_MATRIX
    if _DISTANCE_MATRIX is None:
        from ming_sim.distance import DistanceMatrix
        from ming_sim.paths import bundled_path

        _DISTANCE_MATRIX = DistanceMatrix.from_file(
            bundled_path("content", "distance_matrix.json")
        )
    return _DISTANCE_MATRIX


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


def _is_issuance_turn(order: Mapping[str, object], turn: int) -> bool:
    return int(order.get("turn_issued") or 0) == int(turn)


def _identity_keys_for_unit(unit: str, *, effect_sign: int, purpose: object = None) -> tuple[str, ...]:
    if unit != "万两":
        return _IDENTITY_FOR_UNIT[unit]
    if int(effect_sign) > 0:
        return ("category", "account")
    keys = ("purpose", "category", "account")
    if str(purpose or "").strip() == "补饷":
        return keys + ("target_kind", "target_id")
    return keys


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
    target_kind = delivery.get("target_kind")
    if target_kind is None:
        target_kind = source.get("target_kind")
    if target_kind is None:
        target_kind = payload.get("target_kind")
    target_id = delivery.get("target_id")
    if target_id is None:
        target_id = source.get("target_id")
    if target_id is None:
        target_id = payload.get("target_id")
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
    if target_kind is not None:
        out["target_kind"] = target_kind
    if target_id is not None:
        out["target_id"] = target_id
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
    target_kind: object = None,
    target_id: object = None,
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
        if target_kind is None:
            target_kind = extracted.get("target_kind")
        if target_id is None:
            target_id = extracted.get("target_id")
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
        purpose_text = str(purpose or "").strip()
        if int(delivery["effect_sign"]) > 0:
            if purpose_text == "补饷":
                raise CovertContractError("密令确认收入不得指定补饷")
        else:
            delivery["purpose"] = canonicalize_economy_purpose(purpose)
            if delivery["purpose"] == "补饷":
                kind_text = str(target_kind or "").strip()
                id_text = str(target_id or "").strip()
                if kind_text != "army" or not id_text:
                    raise CovertContractError("密令确认补饷必须指定 target_kind=army 与有效 target_id")
                delivery["target_kind"] = kind_text
                delivery["target_id"] = id_text
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
    missing_identity = [
        key for key in _identity_keys_for_unit(
            unit,
            effect_sign=int(delivery["effect_sign"]),
            purpose=delivery.get("purpose"),
        )
        if not delivery.get(key)
    ]
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
    if any(
        not delivery.get(key)
        for key in _identity_keys_for_unit(
            str(unit),
            effect_sign=int(delivery.get("effect_sign") or 0),
            purpose=delivery.get("purpose"),
        )
    ):
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


def minister_eligible_for_monthly_covert(db: Any, minister_name: str) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM characters WHERE name=? AND status='active'",
        (str(minister_name or "").strip(),),
    ).fetchone()
    return row is not None


def _current_game_turn(db: Any, turn: object = None) -> int:
    if turn is not None:
        return int(turn)
    row = db.conn.execute("SELECT turn FROM game_state WHERE id=1").fetchone()
    if row is not None:
        return int(row["turn"])
    return 0


def build_secret_covert_effect_briefs(
    db: Any,
    orders: Sequence[Mapping[str, object]] | None = None,
    *,
    turn: object = None,
) -> List[Dict[str, object]]:
    """internal 档房私密输入：typed 合同 + origin，不含密令正文（#883）。"""
    rows = list(orders or [])
    if not rows:
        rows = list(db.list_secret_orders(status="active"))
    current_turn = _current_game_turn(db, turn)
    out: List[Dict[str, object]] = []
    for order in rows:
        if not isinstance(order, Mapping):
            continue
        if str(order.get("status") or "active") != "active":
            continue
        if _is_issuance_turn(order, current_turn):
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
        prior_units = float(db.sum_dossier_actual_progress_units(int(dossier["id"])))
        target_units = contract_target_units(contract)
        remaining_units = max(0.0, target_units - prior_units)
        out.append({
            "origin_ref": f"dossier:{int(dossier['id'])}",
            "order_id": oid,
            "kind": str(contract.get("kind") or ""),
            "axes": list(contract.get("axes") or []),
            "direction": int(contract.get("direction") or 1),
            "delivery": copy.deepcopy(dict(delivery)),
            "effect_owner": owner,
            "canonical_fields": fields,
            "prior_actual_units": prior_units,
            "remaining_units": remaining_units,
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
    if sign < 0:
        purpose = str(delivery.get("purpose") or "").strip()
        if str(item.get("purpose") or "").strip() != purpose:
            return False
        if purpose == "补饷":
            if str(item.get("target_kind") or "").strip() != str(delivery.get("target_kind") or "").strip():
                return False
            if str(item.get("target_id") or "").strip() != str(delivery.get("target_id") or "").strip():
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
    """真相底 live 集：seed_guilt（键=target）＋ evidence 边（键=边事件 id）。

    #1896：真相底本身不动（毁证只改可查性，不改"这条罪是否实有"），故本读口
    与 ADR 0098 后出修订同口径；被毁成 gone 的事实仍在本集内，只是查不出来。
    """
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


def _is_seed_guilt_fact_key(target: str, fact_key: str) -> bool:
    """seed_guilt lane 的稳定键＝(target)；其余 live 键＝边事件 id（ADR 0098 键口径）。"""
    return str(fact_key) == str(target)


def _seed_guilt_severity(db: Any, target: str) -> str:
    row = db.conn.execute(
        "SELECT seed_guilt FROM characters WHERE name=?",
        (str(target),),
    ).fetchone()
    if row is None:
        return ""
    raw = row["seed_guilt"]
    if isinstance(raw, Mapping):
        return str(raw.get("severity") or "").strip()
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return ""
    if isinstance(parsed, Mapping):
        return str(parsed.get("severity") or "").strip()
    return ""


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
                effort = float(item.get("effort") or 0.0)
            except (TypeError, ValueError):
                effort = 0.0
            try:
                difficulty = float(item.get("difficulty") or 0.0)
            except (TypeError, ValueError):
                difficulty = 0.0
            try:
                months = int(item.get("months") or 0)
            except (TypeError, ValueError):
                months = 0
            reason = str(item.get("reason_code") or "").strip()
            legal = reason in PERSON_LEGAL_REASON_CODES
            lanes.append({
                "fact_key": key,
                "effort": max(0.0, effort),
                "difficulty": max(0.0, difficulty),
                "months": max(0, months),
                "mastered": bool(item.get("mastered")),
                "used": bool(item.get("used")) and legal,
                "reason_code": reason if legal else "",
            })
    return lanes


def globally_used_fact_keys(db: Any, *, except_dossier_id: int = 0) -> set[str]:
    """已被别的案查获过的事实键（#1896 同一事实不重复查获）。

    键取"已掌握（mastered）"而非"已清算（used）"：#1896 把满阈自动写依律废了，
    掌握证据本身不再置 used，若仍按 used 去重，同一事实换个案就能重复查获、
    重复坐实——那正是本票要堵的漏。
    """
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
            if lane.get("mastered") or lane.get("used"):
                used.add(str(lane["fact_key"]))
    return used


def _write_fact_lanes(
    db: Any, dossier_id: int, lanes: Sequence[Mapping[str, object]], *, commit: bool = False,
) -> None:
    payload = _dossier_payload_map(db, dossier_id)
    payload[FACT_LANES_KEY] = [
        {
            "fact_key": str(lane["fact_key"]),
            "effort": float(lane.get("effort") or 0.0),
            "difficulty": float(lane.get("difficulty") or 0.0),
            "months": int(lane.get("months") or 0),
            "mastered": bool(lane.get("mastered")),
            "used": bool(lane.get("used")),
            "reason_code": str(lane.get("reason_code") or ""),
        }
        for lane in lanes
    ]
    db.update_decree_dossier_payload(int(dossier_id), payload, commit=commit)


def investigation_fact_difficulty(
    db: Any,
    *,
    target: str,
    fact_key: str,
    investigator: str,
) -> float:
    """#1896 逐证难度：引擎从实账核算"这条罪证有多难查"。

    四修正因子（ADR 0098 后出修订口径，全部读既有 substrate，不新立轴）：
    - 事实分档：seed_guilt 罪谱 vs 已落库 evidence 把柄边（后者更难撬）
    - 罪情轻重：seed_guilt 的 severity 档（越重越难查）
    - 关系网：目标 evidence 边越多，掩护越厚
    - 实际到差行程：承办人当前所在地 → 目标所在地 的烘焙行程时间

    毁证（#1896 / ADR 0100 后出修订）按 fact_key 抬难度或直接封死，且真源在
    (target, fact_key) 而非案卷——关案重开、另起新案都不恢复已毁事实。
    引擎只 clamp 不抽签：同一存档同一输入必得同一难度（restore 可复现）。
    """
    name = str(target or "").strip()
    key = str(fact_key or "").strip()
    if not name or not key:
        raise CovertContractError("查案难度核算缺少调查对象或事实键")

    if _is_seed_guilt_fact_key(name, key):
        difficulty = _FACT_DIFFICULTY_SEED_GUILT
        difficulty *= _SEVERITY_MULTIPLIER.get(_seed_guilt_severity(db, name), 1.0)
    else:
        difficulty = _FACT_DIFFICULTY_EVIDENCE_EDGE

    edges = db.get_relation_edge_events(person=name, evidence=True)
    difficulty *= 1.0 + _NETWORK_PER_EDGE * min(len(edges), _NETWORK_EDGE_CAP)

    worker = str(investigator or "").strip()
    if worker:
        row = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?",
            (worker,),
        ).fetchone()
        if row is not None:
            here = str(row["location"] or "").strip()
            target_row = db.conn.execute(
                "SELECT location FROM characters WHERE name=?", (name,),
            ).fetchone()
            there = str(
                target_row["location"] if target_row is not None else ""
            ).strip()
            # 在途（transit_to 非空）＝人未到差，行程按目的地计，难度更重。
            origin = here or there
            destination = str(row["transit_to"] or "").strip() or there
            if origin and destination:
                try:
                    travel = float(_distance_matrix().travel_time(origin, destination))
                except (KeyError, OSError, ValueError):
                    travel = 0.0
                difficulty *= 1.0 + _TRAVEL_PER_UNIT * min(
                    max(0.0, travel), _TRAVEL_TIME_CAP
                )
            ability_row = db.conn.execute(
                "SELECT ability FROM characters WHERE name=?", (worker,),
            ).fetchone()
            if ability_row is not None:
                try:
                    ability = float(ability_row["ability"])
                except (TypeError, ValueError):
                    ability = _ABILITY_REFERENCE
                if ability > 0.0:
                    # 办案人能力强 → 同样难度所需投入更少（难度按参考能力归一）。
                    difficulty *= _ABILITY_REFERENCE / ability

    for spoiled in db.list_investigation_spoiled_facts(name):
        if str(spoiled.get("fact_key") or "") != key:
            continue
        if str(spoiled.get("effect") or "") == "gone":
            return float("inf")
        difficulty *= _SPOILED_HARDER_MULTIPLIER
    return max(_MIN_DIFFICULTY, float(difficulty))


def investigation_monthly_capacity(
    db: Any, investigator: str, *, dossier_id: int = 0,
) -> float:
    """#1896 承办人本月能投多少查案的力气（引擎按实况折算，不采模型裸数）。

    0092 带宽①「在办差务数×能力」＋实际到差行程：人物只声明"下了多大劲"
    （0..1 强度，是人心的选择），能投多少由他的真实处境决定——
    - 能力：强能吏跑得动更多（按参考能力归一）
    - 在途（transit_to 非空）＝人尚未到差，投入打折
    - 带宽：手上未结差务越多，本案分到的越少
    返回值恒在 [_CAPACITY_MIN, _CAPACITY_MAX] 内，且不含任何模型输入。
    """
    worker = str(investigator or "").strip()
    if not worker:
        return _CAPACITY_MIN
    row = db.conn.execute(
        "SELECT ability, transit_to FROM characters WHERE name=?", (worker,),
    ).fetchone()
    capacity = 1.0
    if row is not None:
        try:
            ability = float(row["ability"])
        except (TypeError, ValueError):
            ability = _ABILITY_CAPACITY_REFERENCE
        if ability > 0.0:
            capacity *= 1.0 + _ABILITY_CAPACITY_WEIGHT * (
                (ability - _ABILITY_CAPACITY_REFERENCE) / _ABILITY_CAPACITY_REFERENCE
            )
        if str(row["transit_to"] or "").strip():
            capacity *= _TRANSIT_CAPACITY_PENALTY
    open_errands = 0
    for order in db.list_secret_orders(status="active"):
        if int(order.get("id") or 0) == int(dossier_id or 0):
            continue
        if str(order.get("minister_name") or "") == worker:
            open_errands += 1
    capacity *= max(
        _CAPACITY_MIN,
        1.0 - _BANDWIDTH_PER_ERRAND * min(open_errands, _BANDWIDTH_ERRAND_CAP),
    )
    return max(_CAPACITY_MIN, min(_CAPACITY_MAX, float(capacity)))


def seed_investigation_fact_lanes(
    db: Any,
    dossier_id: int,
    target: str,
    *,
    investigator: str = "",
    commit: bool = False,
) -> List[Dict[str, object]]:
    """开案铺 lane 集：目标当前全部可坐实事实逐条开 lane，并冻结各自难度。

    #1896：lane 集可为空＝合法（清白目标也照开、照占带宽、照走进展轨，月度推进
    对空集是确定性 no-op，永不产查获）；运行期新长事实入集即新 lane。
    难度只在开 lane 时冻结一次——毁证后由 investigation_fact_difficulty 实时重算，
    不靠改旧 lane 数字（真相底不动、可查性可变）。
    """
    payload = _dossier_payload_map(db, dossier_id)
    lanes = _lanes_from_payload(payload)
    seen = {str(lane["fact_key"]) for lane in lanes}
    for key in live_investigation_fact_keys(db, target):
        if key in seen:
            continue
        lanes.append({
            "fact_key": key,
            "effort": 0.0,
            "difficulty": investigation_fact_difficulty(
                db, target=target, fact_key=key, investigator=investigator,
            ),
            "mastered": False,
            "used": False,
            "reason_code": "",
        })
        seen.add(key)
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)
    return lanes


def _master_lane(lane: Dict[str, object]) -> None:
    """记"办案人已掌握此证"。

    #1896：掌握证据 ≠ 已经依法清算 ≠ 自动翻轴。故此处只落 mastered，不再顺手
    写依律 reason_code／used——清算沿其原有决定走（ADR 0098 后出修订明文）。
    """
    lane["mastered"] = True


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
            if bool(lane.get("mastered")) and code in PERSON_LEGAL_REASON_CODES:
                return code
    return ""


def mark_investigation_fact_used(
    db: Any, dossier_id: int, fact_key: str, *, commit: bool = False,
) -> None:
    """清算落账：显式依法坐实某条已掌握事实（唯一写 reason_code 的口）。

    #1896 把"满阈自动坐实并固定写依律"废了，故此函数不再被进度推进调用；
    它只服务后续清算自己的决定，reason_code 由调用方按真实清算给出。
    """
    key = str(fact_key)
    lanes = _lanes_from_payload(_dossier_payload_map(db, dossier_id))
    found = False
    for lane in lanes:
        if str(lane["fact_key"]) == key:
            lane["reason_code"] = DEFAULT_SUBSTANTIATION_REASON
            lane["used"] = DEFAULT_SUBSTANTIATION_REASON in PERSON_LEGAL_REASON_CODES
            found = True
            break
    if not found:
        lane = {
            "fact_key": key,
            "effort": 0.0,
            "difficulty": 0.0,
            "mastered": True,
            "used": DEFAULT_SUBSTANTIATION_REASON in PERSON_LEGAL_REASON_CODES,
            "reason_code": DEFAULT_SUBSTANTIATION_REASON,
        }
        lanes.append(lane)
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)


def investigation_lane_actual_units(db: Any, dossier_id: int) -> float:
    """本案已查获（已掌握）的事实条数——到期结案读的是它，不读奏报自称。"""
    return float(
        sum(1 for lane in _lanes_from_payload(_dossier_payload_map(db, dossier_id))
            if lane.get("mastered"))
    )


def apply_investigation_monthly_effort(
    db: Any,
    dossier_id: int,
    target: str,
    investigator: str,
    *,
    fact_key: str = "",
    intensity: float = 0.0,
    commit: bool = False,
) -> Dict[str, object]:
    """#1896 逐证核算：人物声明"下了多大劲"，引擎核出本月实投再记到该条事实上。

    与旧轨的分别（ADR 0098 后出修订取代项）：
    - 投入不是模型直采的裸浮点：声明值只作**强度**（0..1，clamp），本月实投由
      引擎按承办人真实状态折算（investigation_monthly_capacity：能力／在途／
      0092 带宽）并硬顶 _MONTHLY_EFFORT_CAP——深挖也不是无限深挖（P6 clamp）；
    - 每条事实有自己的难度（investigation_fact_difficulty），累计实投达到该条
      难度、且该条已在查满 _MIN_MONTHS_UNDER_INVESTIGATION 个月，才记 mastered
      ——既无统一阈值，也不许"一月速坐实"（并保住 0100 毁证／惊蛇窗口）；
    - 敷衍／停办（intensity<=0）就是本月零投入，不产查获、也不改实证；
    - 奏报自称成功不入本函数（P6：呈现层与实况分轨，谎奏不造罪不抹证）。
    """
    lanes = seed_investigation_fact_lanes(
        db, dossier_id, target, investigator=investigator, commit=False,
    )
    try:
        declared = float(intensity or 0.0)
    except (TypeError, ValueError):
        declared = 0.0
    # clamp：声明只是强度，负归零、超 1 归 1；实投另由引擎按实况折算并硬顶。
    declared = max(0.0, min(1.0, declared))
    if declared <= 0.0:
        # 敷衍／停办：确定零投入，不必去算他的带宽与行程。
        _write_fact_lanes(db, dossier_id, lanes, commit=commit)
        return {"bound_fact_key": "", "effort_applied": 0.0, "declared_intensity": 0.0,
                "capacity": 0.0, "mastered": [], "units": 0.0}
    live = set(live_investigation_fact_keys(db, target))
    blocked = globally_used_fact_keys(db, except_dossier_id=int(dossier_id))
    capacity = investigation_monthly_capacity(
        db, investigator, dossier_id=int(dossier_id),
    )
    amount = min(_MONTHLY_EFFORT_CAP, declared * capacity)

    if not lanes or amount <= 0.0:
        _write_fact_lanes(db, dossier_id, lanes, commit=commit)
        return {"bound_fact_key": "", "effort_applied": 0.0, "mastered": [], "units": 0.0}

    bound = str(fact_key or "").strip()
    if bound and (bound not in live or bound in blocked):
        # 线索只助其所指实有证据：指向不存在/已被别案查获的事实 → 确定性丢弃。
        _write_fact_lanes(db, dossier_id, lanes, commit=commit)
        return {
            "bound_fact_key": "", "effort_applied": 0.0, "mastered": [],
            "units": 0.0, "dropped_fact_key": bound,
        }
    if bound:
        already = next(
            (lane for lane in lanes
             if str(lane["fact_key"]) == bound and lane.get("mastered")),
            None,
        )
        if already is not None:
            # 本案已掌握该证：不重复投入、也不重复计数。
            _write_fact_lanes(db, dossier_id, lanes, commit=commit)
            return {
                "bound_fact_key": bound, "effort_applied": 0.0, "mastered": [],
                "units": investigation_lane_actual_units(db, int(dossier_id)),
            }
    if not bound:
        # 未指明事实 → 按 fact_key 稳定序（seed 罪谱优先，边事件 id 升序）取首条
        # 可查 lane（ADR 0098 确定性兜底路由口径：只在既有 lane 内移动、不造真相）。
        for lane in lanes:
            key = str(lane["fact_key"])
            if key in live and key not in blocked and not lane.get("mastered"):
                bound = key
                break

    mastered_now: List[str] = []
    if bound:
        for lane in lanes:
            key = str(lane["fact_key"])
            if key != bound:
                continue
            difficulty = investigation_fact_difficulty(
                db, target=target, fact_key=key, investigator=investigator,
            )
            lane["difficulty"] = difficulty
            if difficulty == float("inf"):
                # 已被毁成 gone：投入无处可施，不得靠重开案/再投入把它查回来。
                _write_fact_lanes(db, dossier_id, lanes, commit=commit)
                return {
                    "bound_fact_key": key, "effort_applied": 0.0, "mastered": [],
                    "units": 0.0, "dropped_fact_key": key,
                }
            lane["effort"] = float(lane.get("effort") or 0.0) + amount
            lane["months"] = int(lane.get("months") or 0) + 1
            if (
                not lane.get("mastered")
                and float(lane["effort"]) >= float(difficulty)
                and int(lane["months"]) >= _MIN_MONTHS_UNDER_INVESTIGATION
            ):
                _master_lane(lane)
            if lane.get("mastered"):
                mastered_now.append(key)
            break
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)
    return {
        "bound_fact_key": bound,
        "effort_applied": amount,
        "declared_intensity": declared,
        "capacity": capacity,
        "mastered": mastered_now,
        "units": investigation_lane_actual_units(db, int(dossier_id)),
    }


def _investigation_knowledge_known(db: Any, target: str, source: str) -> bool:
    """被查者是否真知自己被查：须有真实关系网来源（ADR 0034 非全知 / #1896 未知情不毁证）。

    开案本身不等于目标知情——那是"开案即全知"的漏洞。通风报信人也必须是账本里
    与该目标真有关系边的人物（0081 有向边，任意方向皆可：庇护、连坐、亲党皆算
    有可能递话）。查无此人／无此边 → 确定性判未知情，毁证声明被拒。
    """
    who = str(source or "").strip()
    name = str(target or "").strip()
    if not who or not name:
        return False
    if who == name:
        return False  # 不作自己的信息来源
    if not db.conn.execute(
        "SELECT 1 FROM characters WHERE name=?", (who,),
    ).fetchone():
        return False
    return any(
        str(edge["source"]) == who or str(edge["target"]) == who
        for edge in db.get_relation_edge_events(person=name)
    )


def apply_investigation_spoliation(
    db: Any,
    *,
    target: str,
    fact_key: str,
    effect: str = "harder",
    knowledge_source: str = "",
    origin_ref: str = "",
    turn: Optional[int] = None,
    commit: bool = False,
) -> Dict[str, object]:
    """毁证落账口：按对应事实改可查性，不团灭、不改真相底。

    知情与反应归人物（P6）：本函数只处理其**真实选择**的后果，并且要求人物确实
    经真实关系网知情（knowledge_source）——未知情不替其毁证，知情也不强制毁证。
    'gone' 之后该事实永不可查——关案重开、另起新案都不恢复（真源在 (target, fact_key)）。
    """
    name = str(target or "").strip()
    key = str(fact_key or "").strip()
    if not name or not key:
        raise CovertContractError("毁证落账缺少调查对象或事实键")
    if not _investigation_knowledge_known(db, name, knowledge_source):
        # fail-closed：无真实知情来源就不毁证，也不改任何实证。
        return {"target": name, "fact_key": key, "applied": False,
                "reason": "无真实关系网知情来源，不代其毁证"}
    if key not in live_investigation_fact_keys(db, name):
        # 只毁真实存在的事实；不得凭空毁一条不存在的罪（也无从"恢复"）。
        return {"target": name, "fact_key": key, "applied": False,
                "reason": "该事实不在真相底 live 集内"}
    row = db.record_investigation_spoiled_fact(
        target_name=name, fact_key=key, turn=turn, effect=effect,
        origin_ref=origin_ref, commit=False,
    )
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return {"target": name, "fact_key": key, "applied": True, "effect": str(effect),
            "knowledge_source": str(knowledge_source or "").strip(),
            "row_id": row.get("id")}


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


def _investigation_declaration(sel: Mapping[str, object]) -> Dict[str, object]:
    """#1896 4a 对查案密令的声明读口：查法/投入强度/所查事实/知情反应。

    形状（ADR 0120 后出查案修订）——按人物当月真实办事声明，不读自由文本：
    - effort:   0..1 的**投入强度**（敷衍/停办 → 0）。只是"下了多大劲"，
                引擎另按承办人真实状态折算本月实投并硬顶，故此值填多大都
                不会当月坐实任意罪证。
    - fact_key: str，本月下手的罪证（缺省 → 引擎按稳定序兜底路由）
    - spoliation: {effect, fact_key, knowledge_source}，被查者知情后的毁证选择

    奏报（memorial_text）不在此读口内：谎奏不造罪、不抹证（P6 实况/奏报分轨）。
    """
    out: Dict[str, object] = {}
    raw_effort = sel.get("effort", sel.get("投入"))
    if raw_effort is not None:
        try:
            out["intensity"] = max(0.0, min(1.0, float(raw_effort)))
        except (TypeError, ValueError):
            pass
    fact = str(sel.get("fact_key", sel.get("所查事实")) or "").strip()
    if fact:
        out["fact_key"] = fact
    spoil = sel.get("spoliation", sel.get("毁证"))
    if isinstance(spoil, Mapping):
        effect = str(spoil.get("effect") or "harder").strip()
        if effect in ("harder", "gone"):
            out["spoliation"] = {
                "effect": effect,
                "fact_key": str(spoil.get("fact_key") or fact or "").strip(),
                "knowledge_source": str(
                    spoil.get("knowledge_source", spoil.get("知情来源")) or ""
                ).strip(),
            }
    return out


def apply_monthly_covert_actual_progress(
    db: Any,
    state: Any,
    *,
    selections: object = None,
    commit: bool = False,
    only_supplied: bool = False,
) -> List[Dict[str, object]]:
    """当月实况轨落笔：推演者声明的真实投入/效果 → dossier_actual_progress。

    不发明人物/钱粮/地区固定套餐；奏报永不入 apply。
    ``only_supplied``：过月分段只落本段交代的执行态，不把其余未提及的在办密令误判为缺执行态。

    #1896：查案密令改走逐证核算——4a 声明的 effort 记到指定事实，累计到该证难度
    才记已掌握；不再由执行态折固定增量、满统一阈自动坐实。执行态枚举对查案
    不再是必填（#1895 同批废旧查案的意愿底档），缺省只落事实投入。
    """
    orders = list(db.list_secret_orders(status="active"))
    by_sel = _selection_map(selections)
    applied: List[Dict[str, object]] = []
    turn = int(state.turn)
    for order in orders:
        oid = int(order["id"])
        if _is_issuance_turn(order, turn):
            continue
        if only_supplied and oid not in by_sel:
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
        sel = by_sel.get(oid) or {}
        inv_target = _investigation_target_of(contract)
        if inv_target:
            applied.append(
                _apply_investigation_selection(
                    db, state, order=order, dossier=dossier, sel=sel,
                    target=inv_target, investigator=minister, turn=turn,
                )
            )
            continue
        selected = sel.get("fidelity", sel.get("执行态", sel.get("state")))
        fidelity = normalize_fidelity_state(selected)
        if fidelity is None:
            applied.append({
                "order_id": oid,
                "rejected": True,
                "category": "invalid_enum",
                "report_section": "covert_exec_selections",
                "reason": f"密令 {oid} 缺少有效执行态",
                "item": sel or {"order_id": oid},
            })
            continue
        originated = originated_quantity_this_turn(db, did, turn, contract)
        units = monthly_actual_units(
            fidelity=fidelity, originated_quantity=originated,
        )
        note = str(sel.get("note") or sel.get("备注") or "").strip()
        if not note:
            note = (
                f"月度实进度：执行态{fidelity}（{units:g}）"
                f"；origin_effects={originated}"
            )
        row = db.record_dossier_actual_progress(
            did,
            turn,
            units=units,
            fidelity_state=fidelity,
            floor_state="",
            note=note,
            commit=False,
        )
        db.mark_secret_order_in_progress(oid, commit=False)
        applied.append({
            "order_id": oid,
            "dossier_id": did,
            "units": units,
            "fidelity": fidelity,
            "row_id": row.get("id"),
            "originated_quantity": originated,
            "target_units": contract_target_units(contract),
            "contract_kind": contract.get("kind"),
            "contract_axes": list(contract.get("axes") or []),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return applied


def _apply_investigation_selection(
    db: Any,
    state: Any,
    *,
    order: Mapping[str, object],
    dossier: Mapping[str, object],
    sel: Mapping[str, object],
    target: str,
    investigator: str,
    turn: int,
) -> Dict[str, object]:
    """查案密令的逐证落账（#1896）。幂等键＝(dossier, turn)，重开只续未成核算。"""
    did = int(dossier["id"])
    oid = int(order["id"])
    # 同月重入不重复施加投入：实况轨已有本月行即说明本月已核算过。lane 累加本身
    # 不带幂等键，若不在此拦一道，同一 turn 内被扫两次就会把力气算两遍。
    existing = db.conn.execute(
        "SELECT id, units FROM dossier_actual_progress "
        "WHERE dossier_id=? AND turn=? LIMIT 1",
        (did, int(turn)),
    ).fetchone()
    if existing is not None:
        return {
            "order_id": oid,
            "dossier_id": did,
            "units": float(existing["units"] or 0.0),
            "row_id": existing["id"],
            "fact_key": "",
            "effort_applied": 0.0,
            "mastered_facts": [],
            "originated_quantity": 0.0,
            "already_applied": True,
        }
    declaration = _investigation_declaration(sel)
    result = apply_investigation_monthly_effort(
        db, did, target, investigator,
        fact_key=str(declaration.get("fact_key") or ""),
        intensity=float(declaration.get("intensity") or 0.0),
        commit=False,
    )
    spoliation = declaration.get("spoliation")
    spoiled_result: Dict[str, object] = {}
    if isinstance(spoliation, Mapping):
        spoil_key = str(spoliation.get("fact_key") or "").strip()
        if spoil_key:
            spoiled_result = apply_investigation_spoliation(
                db, target=target, fact_key=spoil_key,
                effect=str(spoliation.get("effect") or "harder"),
                knowledge_source=str(spoliation.get("knowledge_source") or ""),
                origin_ref=f"dossier:{did}", turn=turn, commit=False,
            )
    units = float(result.get("units") or 0.0)
    note = str(sel.get("note") or sel.get("备注") or "").strip()
    if not note:
        note = f"查案实况：本月投入 {result.get('effort_applied', 0.0):g}，已掌握 {units:g} 条"
    row = db.record_dossier_actual_progress(
        did, turn, units=units, fidelity_state="", floor_state="",
        note=note, commit=False,
    )
    db.mark_secret_order_in_progress(oid, commit=False)
    applied: Dict[str, object] = {
        "order_id": oid,
        "dossier_id": did,
        "units": units,
        "row_id": row.get("id"),
        "fact_key": str(result.get("bound_fact_key") or ""),
        "effort_applied": float(result.get("effort_applied") or 0.0),
        "mastered_facts": list(result.get("mastered") or []),
        "originated_quantity": 0.0,
    }
    if result.get("dropped_fact_key"):
        applied["dropped_fact_key"] = str(result["dropped_fact_key"])
    if spoiled_result:
        applied["spoliation"] = spoiled_result
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
        inv_target = _investigation_target_of(contract)
        if inv_target:
            # #1896：到期结案读真实查获——已掌握多少条罪证，对密令约定的取证条数。
            # 不再拿"期限月数"当固定配额（那是旧轨满统一阈的残影），也不看奏报自称。
            actual = investigation_lane_actual_units(db, did)
            target = contract_target_units(contract)
        else:
            actual = float(db.sum_dossier_actual_progress_units(did))
            target = contract_target_units(contract)
        reports = list(db.list_dossier_progress(did))
        verdict = decide_secret_order_settlement({
            "actual_units": actual,
            "target_units": target,
            "criterion_text": str(order.get("title") or order.get("content") or "密令"),
            "has_reports": bool(reports),
            "origin_context": secret_order_origin(oid),
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
