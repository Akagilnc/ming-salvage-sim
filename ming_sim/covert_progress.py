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
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ming_sim.constants import ECONOMY_ACCOUNTS, REGION_FIELD_ALIASES
from ming_sim.centrifuge_ledger import CENTRIFUGE_AXES
from ming_sim.materials import secret_order_origin
from ming_sim.person_archive_contract import PERSON_ACTIONS
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
# #1896 4a 声明的领域落账（同一案卷 payload，无第二写口）：
#   tips   真实通风报信声明（递话人 + 回合）——知情唯一来源
#   clues  汇案并入的真实线索（各源助对应实证，消费一次）
#   acts   查法／压案等人物当月真实行动声明（落账事实，不代人物决定后果）
INVESTIGATION_TIPS_KEY = "investigation_tips"
INVESTIGATION_CLUES_KEY = "investigation_clues"
INVESTIGATION_ACTS_KEY = "investigation_acts"

# #1896 逐证难度：首版常数随 playtest（同 0011-4 D4-6 先例），本 ADR 不发明精确值。
# 真相底两类事实的基准难度不同：seed_guilt 是一条待坐实的罪谱，把柄边是已落库的
# 实物/证词边（结构化事件产），后者更难撬——ADR 0098 后出修订只保"实有罪证"与
# 逐证核算，不保任何统一阈值，故此处按事实分档而非一把尺。
_FACT_DIFFICULTY_SEED_GUILT = 1.0
_FACT_DIFFICULTY_EVIDENCE_EDGE = 1.4
_SEVERITY_MULTIPLIER = {"轻": 0.8, "中": 1.0, "重": 1.3}
# 关系网只读 0081 有向边里结构化 evidence 标记的把柄边（ADR 0098 机读判据），
# 按对手去重计。**不**按 event_kind 自由类目计庇护——ADR 0098:15 明文九类自由
# 类目不驱动任何机械分支（判官误标类目不该改变查案难度，大理寺 R4）。
_NETWORK_PER_EDGE = 0.05
_NETWORK_EDGE_CAP = 10
# 目标遮掩（ADR 0108 阴谋能力，已准设计「被查的人越会遮掩、关系网越深，越难查」）：
# 同等条件下目标越会遮掩越难查。基准 50＝不乘不除（缺省/未列者即中性），
# 乘子按参考值归一，随 playtest 校准（0011-4 D4-6 先例，不在此发明精确值）。
# clamp 下界 1：人物无阴谋能力不是"负遮掩"，按最易查的边缘处理而非把难度压到零。
_INTRIGUE_REFERENCE = 50.0
_INTRIGUE_MIN = 1.0
# 行程轴同样不落在难度里：未到差＝本月实投为零（_investigator_on_site）。
_ABILITY_REFERENCE = 60.0
_SPOILED_HARDER_MULTIPLIER = 1.5
_MIN_DIFFICULTY = 0.1

# #1896 月度投入：人物只声明"下了多大劲"（0..1 的强度，人心的选择），引擎按其
# 真实状态折算本月实投。**不设单月硬顶、不设最低在查月数 floor**——那是 ADR 0098
# 后出修订明文退役的旧轨门槛（#1896「旧单月加成上限、最低在查月数 floor 的退役」）；
# 上限由人物真实处境给出：未到差即零、能力/带宽自然封顶，不另加人为月闸。
# 强度本身 clamp 到 0..1，故单月坐实仍只取决于"当月实投 ≥ 该条难度"。
_CAPACITY_MIN = 0.0
_CAPACITY_MAX = 1.2
_ABILITY_CAPACITY_WEIGHT = 0.5
_ABILITY_CAPACITY_REFERENCE = 60.0
_BANDWIDTH_PER_ERRAND = 0.15      # 0092 带宽①：未结差务越多，本案可分到的越少
_BANDWIDTH_ERRAND_CAP = 3
# 真实线索（各源汇案）对所指实证的助力：只助它所指的那一条，一次性消费。
# 首版随 playtest（同逐证难度常数口径），不给整案加成。
_CLUE_ASSIST_EFFORT = 0.3

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


_DEBT_SEVERITIES = frozenset({"轻", "中", "重"})


def seed_guilt_counts_as_debt(seed_guilt: object) -> bool:
    """真相底只收结构化罪情。severity ∈ {轻, 中, 重} 才入罪谱。

    crime 是说明散文，不承重。解析失败、非对象、severity 为空或「无」，都不造罪。
    """
    if isinstance(seed_guilt, Mapping):
        guilt: object = seed_guilt
    else:
        text = str(seed_guilt or "").strip()
        if not text:
            return False
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(parsed, Mapping):
            return False
        guilt = parsed
    severity = str(guilt.get("severity") or "").strip()
    return severity in _DEBT_SEVERITIES



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
    investigation_fact = str(
        delivery.get("investigation_fact")
        or source.get("investigation_fact")
        or payload.get("investigation_fact")
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
    if investigation_fact:
        out["investigation_fact"] = investigation_fact
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
    investigation_fact: object = None,
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
        if investigation_fact is None:
            investigation_fact = extracted.get("investigation_fact")
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
        contract = {
            "version": CONTRACT_VERSION,
            "action_type": str(action_type or "secret_order"),
            "kind": resolved_kind,
            "axes": axis_list,
            "direction": direction_i,
            "investigation_target": inv_target,
            "delivery": delivery,
        }
        inv_fact = str(investigation_fact or "").strip()
        if inv_fact:
            # 线索所指事实：汇案时按它把真实线索绑到对应实证（J9）。
            contract["investigation_fact"] = inv_fact
            delivery["investigation_fact"] = inv_fact
        return contract
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


# 转译 prompt 里给模型的契约样例：每份都必须能被 build_covert_task_contract
# 收下，否则说明本身就在教模型交一份会被拒的载荷。
# 钱粮两种定向各给一份：符号语义（+1 收入 / -1 支出）正是手写说明曾写反之处，
# 光给人犯样例盖不住。
_CONTRACT_EXAMPLES: tuple[Dict[str, object], ...] = (
    {
        "kind": "查案",
        "axes": ["实务事功"],
        "direction": 1,
        "delivery": {
            "unit": "人犯",
            "target_units": 3,
            "person_action": "处置",
            "effect_sign": 1,
        },
    },
    {
        "kind": "查赃",
        "axes": ["礼法名节"],
        "direction": -1,
        "delivery": {
            "unit": "万两",
            "target_units": 5,
            "effect_sign": -1,
            "purpose": "其它",
            "category": "追赃",
            "account": "内库",
        },
    },
    {
        "kind": "查军饷",
        "axes": ["实务事功"],
        "direction": 1,
        "delivery": {
            "unit": "万两",
            "target_units": 8,
            "effect_sign": 1,
            "category": "军费",
            "account": "国库",
        },
    },
)


def describe_covert_task_contract() -> str:
    """本冻结契约的可消费定义（转译 prompt 的单一真源投影）。

    #1897：转译形状里只写 ``"covert_task": {}`` 等于没告诉模型要交什么，
    真实模型交不出 ``build_covert_task_contract`` 收的字段。这里从本模块的
    闭集常量与 identity 规则直接投影出必填字段，闭集不另抄一份。

    钱粮那段的「收款 / 支出」措辞与必需字段**由** ``_identity_keys_for_unit``
    投影（``effect_sign>0`` 即收入，只要 category/account；``<=0`` 即支出，
    另须 purpose，补饷再须 target_kind/target_id）——不再手写第二份规则：
    手写那份曾把符号写反，教模型交一份必被拒的载荷。

    样例取自 ``_CONTRACT_EXAMPLES``——每份样例本身必须能被
    ``build_covert_task_contract`` 收下，免得说明与实现分叉。
    """
    axes = "、".join(sorted(CENTRIFUGE_AXES))
    units = "、".join(CANONICAL_UNITS)
    actions = "、".join(PERSON_ACTIONS)
    accounts = "、".join(ECONOMY_ACCOUNTS)
    fields = "、".join(sorted(REGION_FIELD_ALIASES))
    income_keys = "、".join(
        _identity_keys_for_unit("万两", effect_sign=1),
    )
    spend_keys = "、".join(
        _identity_keys_for_unit("万两", effect_sign=-1, purpose="其它"),
    )
    subsidy_keys = "、".join(
        _identity_keys_for_unit("万两", effect_sign=-1, purpose="补饷"),
    )
    samples = "\n".join(
        f"    {json.dumps(sample, ensure_ascii=False)}"
        for sample in _CONTRACT_EXAMPLES
    )
    return (
        f"{samples}\n"
        f"    必填：kind（差务类型）、axes（六轴之一：{axes}）、direction（1 顺轴 / -1 逆轴）、"
        f"delivery.unit（{units}）、delivery.target_units（正数）、delivery.effect_sign（+1 / -1）。\n"
        f"    按 unit 另须给足交付身份：人犯 → person_action（{actions}）；"
        f"万亩 → region / field（{fields}）/ target。\n"
        f"    万两的 effect_sign 定向钱：+1 是收入（臣上交），只要 {income_keys}"
        f"（account 取 {accounts}）；"
        f"-1 是支出（皇帝拨出），须另给 {spend_keys}；"
        f"purpose=补饷 时还须 {subsidy_keys}（target_id 取军额 id）。"
        f"收入不得写 purpose=补饷。\n"
        "    查 investigative_target 的暗查则给 investigation_target（可数目标）+ target_units + effect_sign。\n"
        "    上述字段缺一即拒收该条密令；不得凭空编造闭集外的值。"
    )


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
    origin = str(review_input.get("origin_context") or "")

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
        "note": note,
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
    """结案给玩家的字就是账上的字。#1897：仅空白也是原文，不得因 strip 判空而改走兜底。"""
    existing = str(order.get("result") or "")
    if existing:
        return existing
    for item in reversed(list(reports or [])):
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("memorial_text") or "")
        if text:  # verbatim: whitespace-only memorial also counts
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
    """lane 集读口：投入累计、逐条难度、已掌握。

    #1896 后不再有 used／reason_code 字段——满阈自动写依律的旧清算轨已退役
    （ADR 0098 后出修订），掌握证据本身不等于依法清算；去重读口按 mastered 判。
    """
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
            lanes.append({
                "fact_key": key,
                "effort": max(0.0, effort),
                "difficulty": max(0.0, difficulty),
                "months": max(0, months),
                "mastered": bool(item.get("mastered")),
            })
    return lanes


def globally_used_fact_keys(db: Any, *, except_dossier_id: int = 0) -> set[str]:
    """已被别的案查获过的事实键（#1896 同一事实不重复查获）。

    键取"已掌握（mastered）"：掌握证据不再置 used，故去重也只看掌握。
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
            if lane.get("mastered"):
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
        }
        for lane in lanes
    ]
    db.update_decree_dossier_payload(int(dossier_id), payload, commit=commit)


def _append_investigation_log(
    db: Any, dossier_id: int, key: str, entry: Mapping[str, object],
) -> None:
    """把 4a 声明的真实行动／线索追加进案卷 payload（同一写口，无第二轨）。

    只追加已发生的声明事实，不由此派生任何机制后果——人物怎么办归人物（P6）。
    **不截断**：ADR 0155:8 撤除硬历史上限，#1896 要求完整历史实况供料；
    截尾会让跨月的知情／因果承接读不到上月记录（也是 R5 的一半病根）。
    """
    payload = _dossier_payload_map(db, dossier_id)
    raw = payload.get(key)
    items = list(raw) if isinstance(raw, list) else []
    items.append(dict(entry))
    payload[key] = items
    db.update_decree_dossier_payload(int(dossier_id), payload)


def investigation_fact_is_gone(db: Any, target: str, fact_key: str) -> bool:
    """这条罪证是否已被毁成 gone。唯一判据是 investigation_spoiled_facts。

    难度里的 inf 不是这个判据：能力为零也会把难度乘成 inf，不能冒充毁证。
    """
    name = str(target or "").strip()
    key = str(fact_key or "").strip()
    if not name or not key:
        return False
    return any(
        str(row.get("fact_key") or "") == key
        and str(row.get("effect") or "") == "gone"
        for row in db.list_investigation_spoiled_facts(name)
    )


def investigation_fact_difficulty(
    db: Any,
    *,
    target: str,
    fact_key: str,
    investigator: str,
) -> float:
    """#1896 逐证难度：引擎从实账核算"这条罪证有多难查"。

    修正因子（ADR 0098 后出修订口径，全部读既有 substrate，不新立轴）：
    - 事实分档：seed_guilt 罪谱 vs 已落库 evidence 把柄边（后者更难撬）
    - 罪情轻重：seed_guilt 的 severity 档（越重越难查）
    - 关系网：目标的 evidence 边（结构化把柄越多越难查，按对手去重）
    - 目标遮掩：ADR 0108 per-character 阴谋能力（已准设计「被查的人越会遮掩、
      关系网越深，越难查」；#1896 一并交付该列，本轴不再延期）
    - 办案人能力：能力强则同难度所需投入更少

    **到差不在此轴**：未到差不是"难度更高"，而是本月实投为零（见
    ``investigation_monthly_capacity``／``_investigator_on_site``）——没到当地
    就无从查起，这是"办案人得身在当地"的硬形状，不是一段行程折扣。

    庇护边不按 event_kind 自由类目计（ADR 0098:15）。**不**拿 characters.identity
    （党籍认同，CONTEXT.md 孤臣轴）冒充遮掩——遮掩的真源只有 `characters.intrigue`
    （ADR 0108:5,7／大理寺 R4）。查案对象不是真人物行（如「某类人」式题名）时
    该轴退化不参与，与所在地缺失同款处理：不假装他会遮掩，也不假装他不会。

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

    # 关系网（#1896「关系网」）：读 0081 有向边里**结构化 evidence 标记**的边
    # （ADR 0098 机读判据：只有结构化产出方才落 evidence，把柄越多越难查）。
    # 边按人去重计，不拿边数冒充庇护人数。
    #
    # ⚠️ 这里**不**按 event_kind 自由类目（站台/恩义/协作…）计庇护：ADR 0098:15
    # 明文「九类自由类目不驱动任何机械分支」，判官误标类目不该改变查案难度
    # （大理寺 R4：按类目改难度＝以自由类目替代真实庇护输入）。
    # ⚠️ 这里**不**拿 characters.identity 当目标遮掩：identity 是党籍认同
    # （CONTEXT.md 孤臣轴），不是掩人耳目之能。遮掩的真源只有 `characters.intrigue`
    # （ADR 0108 per-character 阴谋能力，#1896 一并交付该列）——见下。
    edges = 0
    seen_others: set[str] = set()
    for edge in db.get_relation_edge_events(person=name, evidence=True):
        other = str(edge["target"]) if str(edge["source"]) == name else str(edge["source"])
        other = str(other or "").strip()
        if not other or other == name or other in seen_others:
            continue
        seen_others.add(other)
        edges += 1
    difficulty *= 1.0 + _NETWORK_PER_EDGE * min(edges, _NETWORK_EDGE_CAP)

    # 目标遮掩（ADR 0108 阴谋能力）：已准设计原句「被查的人越会遮掩、关系网越深，
    # 越难查」。读目标自己在册的阴谋能力——静态 seed 能力轴，引擎只按参考值
    # 归一，不抽签（restore 可复现）。与办案人能力轴方向相反：那边能力强→易查
    # （除以能力），这边遮掩高→难查（除以参考值、乘以自身）。
    # 目标不在 characters 行里（题名式查案对象）时该轴退化不参与。
    #
    # 该列 NOT NULL INTEGER（content 侧 0–100 校验），故 int 直取、不设解析兜底；
    # 0 是合法值（0–100 闭集下端）且**必须**走 clamp——早前的 `if intrigue > 0`
    # 守卫会让最不会遮掩的人跳过乘子、落回参考值同难度，凭空造出一道非单调的台阶。
    target_row = db.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", (name,),
    ).fetchone()
    if target_row is not None:
        difficulty *= max(int(target_row["intrigue"]), _INTRIGUE_MIN) / _INTRIGUE_REFERENCE

    # 办案人能力（ADR 0092 带宽①同源）：能力强 → 同难度所需投入更少。
    worker = str(investigator or "").strip()
    if worker:
        ability_row = db.conn.execute(
            "SELECT ability FROM characters WHERE name=?", (worker,),
        ).fetchone()
        if ability_row is not None:
            try:
                ability = float(ability_row["ability"])
            except (TypeError, ValueError):
                ability = _ABILITY_REFERENCE
            # 零是合法能力，走同一公式（参考值/能力）。0 用 inf 表达除零，
            # 不另立「能力为零则拒绝」的闸，也不把前置因子覆盖成常数。
            # 解析失败或非有限值仍按参考能力（乘子为 1）。
            if math.isfinite(ability) and ability >= 0.0:
                difficulty *= (
                    math.inf if ability == 0.0 else _ABILITY_REFERENCE / ability
                )

    if investigation_fact_is_gone(db, name, key):
        return float("inf")
    for spoiled in db.list_investigation_spoiled_facts(name):
        if str(spoiled.get("fact_key") or "") != key:
            continue
        if str(spoiled.get("effect") or "") == "gone":
            continue
        difficulty *= _SPOILED_HARDER_MULTIPLIER
    return max(_MIN_DIFFICULTY, float(difficulty))


def _investigator_on_site(db: Any, worker_row: Any, target: str) -> bool:
    """承办人本月是否身在查案当地（已准设计「办案人得身在当地」）。

    两种"未到差"是同一类缺陷的两种形状，必须一并判：
    - 在途（transit_to 非空）：0097 明文，人在路上、差没开张；
    - **根本不在目标那一省**：只查 transit_to 会把它漏过去，于是异地之人
      照样把当地罪证查获——大理寺 R3 的反例正是这一形状。

    所在地缺失时按 0092/0097 同款退化：轴不参与（放行），不假装到差也不
    假装出差——人物无 location 是内容表稀疏，不是"他在外地"的证据。
    """
    if str(worker_row["transit_to"] or "").strip():
        return False
    who = str(worker_row["location"] or "").strip()
    name = str(target or "").strip()
    if not who or not name:
        return True  # 该轴不参与（退化）
    # 查案对象不是真人物（如「某类人」式题名）时无当地可核，按退化放行。
    target_row = db.conn.execute(
        "SELECT location FROM characters WHERE name=?", (name,),
    ).fetchone()
    if target_row is None:
        return True
    there = str(target_row["location"] or "").strip()
    if not there:
        return True  # 目标所在地未知：该轴不参与（退化），不假装出差
    return who == there


def investigation_monthly_capacity(
    db: Any, investigator: str, *, dossier_id: int = 0, target: str = "",
) -> float:
    """#1896 承办人本月能投多少查案的力气（引擎按实况折算，不采模型裸数）。

    0092 带宽①「在办差务数×能力」＋实际到差：人物只声明"下了多大劲"
    （0..1 强度，是人心的选择），能投多少由他的真实处境决定——
    - 能力：强能吏跑得动更多（按参考能力归一）
    - 到差：**须身在目标当地**才查得动当地的罪证。已准设计原句「办案人得
      身在当地」（ADR 0155 后出：人物只见自己身份下可及的材料——不在当地就
      拿不到那条罪证的实物）。判据按 0097：location 是最后已知地，在途
      （transit_to 非空）＝人未到差；两者皆空时该轴不参与（退化，不假装到差）。
      只查 transit_to 会漏掉「人根本不在这一省」这种形状，故所在地必须比。
    - 带宽：owner 绑定的未结差务（decree_dossiers 主办案卷，在办态）越多，
      本案分到的越少——真源是案卷主办人，不是密令表
    返回值恒在 [_CAPACITY_MIN, _CAPACITY_MAX] 内，且不含任何模型输入。
    """
    worker = str(investigator or "").strip()
    if not worker:
        return _CAPACITY_MIN
    row = db.conn.execute(
        "SELECT ability, location, transit_to FROM characters WHERE name=?",
        (worker,),
    ).fetchone()
    if row is not None and not _investigator_on_site(db, row, target):
        return _CAPACITY_MIN  # 未到差：无差可查，投入为零
    capacity = 1.0
    if row is not None:
        try:
            ability = float(row["ability"])
        except (TypeError, ValueError):
            ability = _ABILITY_CAPACITY_REFERENCE
        # 零参与同一带宽公式。解析失败或非有限值用参考能力。
        if math.isfinite(ability):
            capacity *= 1.0 + _ABILITY_CAPACITY_WEIGHT * (
                (ability - _ABILITY_CAPACITY_REFERENCE) / _ABILITY_CAPACITY_REFERENCE
            )
    open_errands = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE executor_kind='character' AND executor_id=? "
        "AND status IN ('promulgated','executing') AND id<>?",
        (worker, int(dossier_id or 0)),
    ).fetchone()
    capacity *= 1.0 - _BANDWIDTH_PER_ERRAND * min(
        int(open_errands["n"] or 0), _BANDWIDTH_ERRAND_CAP,
    )
    return max(_CAPACITY_MIN, min(_CAPACITY_MAX, float(capacity)))


def record_investigation_source_clue(
    db: Any, dossier_id: int, *, fact_key: str = "", turn: int = 0,
) -> None:
    """开案时把**带指针的本案来源**记成一条真实线索（#1896 R6）。

    汇案走 ``merge_investigation_confirmation`` 会留线索，但首次开案那条来源
    原先只在密令合同里存了个指针，案卷 ``investigation_clues`` 是空的——
    于是"开案时已带 investigation_fact 的首个来源"既不助它所指的实证、
    也和后来汇案的那条待遇不同（大理寺 R6：同一合同，先开案 clues=[]/effort=0，
    后汇案才拿到对应 clue）。两种来源走同一条接线。

    ⚠️ **只在合同真带 investigation_fact 时才写**：无指针的开案**不造线索**。
    ADR 0098:11 的「各源加成」与兜底路由都只作用于**真实存在的来源**（检举、
    证词、苦主这类确实带着案情而来的消息），不是给「开案」这个动作本身记一笔。
    凭空造一条空指针线索再让它走兜底路由，等于每道查案密令首月白送一次实投
    （台院 F1）——那既不是真实来源，也让「敷衍＝零投入」不成立。
    """
    key = str(fact_key or "").strip()
    if not key:
        return  # 无指针的开案不是一条来源线索，不造
    payload = _dossier_payload_map(db, int(dossier_id))
    clues = payload.get(INVESTIGATION_CLUES_KEY)
    if not isinstance(clues, list):
        clues = []
    clues.append({
        "pending_action_id": 0,
        "origin_chat_message_ids": [],
        "fact_key": key,
        "turn": int(turn or 0),
        "credited": False,
        "origin": "case_opening",
    })
    payload[INVESTIGATION_CLUES_KEY] = clues
    db.update_decree_dossier_payload(int(dossier_id), payload, commit=False)


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
        })
        seen.add(key)
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)
    return lanes


def investigation_lane_actual_units(db: Any, dossier_id: int) -> float:
    """本案已查获（已掌握）的事实条数——到期结案读的是它，不读奏报自称。"""
    return float(
        sum(1 for lane in _lanes_from_payload(_dossier_payload_map(db, dossier_id))
            if lane.get("mastered"))
    )


def investigation_clue_records(db: Any, dossier_id: int) -> List[Dict[str, object]]:
    """案卷已并入的真实线索（各源汇案），含是否已被本月核算消费。"""
    raw = _dossier_payload_map(db, dossier_id).get(INVESTIGATION_CLUES_KEY)
    return [dict(x) for x in raw if isinstance(x, Mapping)] if isinstance(raw, list) else []


def _route_pointerless_clue(lanes: List[Dict[str, object]], target: str) -> str:
    """无指针的通用线索该助哪条既有实证（ADR 0098:11 确定性兜底路由）。

    先归 seed_guilt lane；无 seed_guilt lane 而案内有其他活跃 lane（运行期把柄
    边）时按 fact_key 稳定序（边事件 id 升序）取首条；全案无 lane 返回空串。
    只在**既有 lane 内**移动，无从造真相，选序确定可复现（restore 同结果）。
    """
    if not lanes:
        return ""
    for lane in lanes:
        if _is_seed_guilt_fact_key(target, str(lane["fact_key"])):
            return str(lane["fact_key"])
    def _stable(lane: Dict[str, object]) -> tuple[int, int, str]:
        key = str(lane["fact_key"])
        return (0, int(key), "") if key.isdigit() else (1, 0, key)
    return str(min(lanes, key=_stable)["fact_key"])


def _consume_monthly_clues(
    db: Any,
    dossier_id: int,
    target: str,
    investigator: str,
    lanes: List[Dict[str, object]],
    *,
    live: set[str],
    blocked: set[str],
    capacity: float,
) -> float:
    """线索只助其所指实有实证：把并入本案的真实线索按所指 fact_key 记成实投。

    - 指向不存在/已被别案查获的罪 → 确定性丢弃（不造罪、不重复查获）；
    - 同一线索只消费一次（``credited``），重开重试不双计；
    - 线索把该条累计实投推过其难度时，同样按"达到难度即记已掌握"记查获。

    **无指针的真实来源线索走 ADR 0098:11 的确定性兜底路由**（该条路由是既有已准
    规则，不因本次人物行动裁决而废止；⚠️ 只作用于真实存在的来源，「开案」这个动作
    本身不是来源——无指针的开案不造线索，见 ``record_investigation_source_clue``）：
    先归 seed_guilt lane；目标无 seed_guilt lane 而案内有其他活跃 lane 时按
    fact_key 稳定序（边事件 id 升序）取首条；**全案无 lane 才丢弃**并留痕。
    路由只在既有 lane 内移动、从不造真相。

    ⚠️ 这与「人物本月下手」是两件事：本月 ``fact_key`` 省略是**人物没下手处**
    → 零投入、代码不代选（J4，大理寺已结清）；此处路由的是**来源线索该助哪条
    既有实证**，不替人物挑活干。
    """
    # 未到差与零带宽：线索也不加成。不标 credited，人到场后仍可一次性消费。
    if float(capacity) <= 0.0:
        return 0.0
    by_key = {str(lane["fact_key"]): lane for lane in lanes}
    clues = investigation_clue_records(db, dossier_id)
    if not clues:
        return 0.0
    credited = 0.0
    for clue in clues:
        if bool(clue.get("credited")):
            continue
        key = str(clue.get("fact_key") or "").strip()
        clue["credited"] = True
        if not key:
            key = _route_pointerless_clue(lanes, target)
            if key:
                clue["routed_fact_key"] = key  # ADR 0098:11 确定性兜底路由
            else:
                clue["dropped_no_lane"] = True  # 全案无 lane → 确定性丢弃
                continue
        lane = by_key.get(key)
        if lane is None or key not in live or key in blocked:
            clue["dropped_fact_key"] = key
            continue
        lane["effort"] = float(lane.get("effort") or 0.0) + _CLUE_ASSIST_EFFORT
        credited += _CLUE_ASSIST_EFFORT
        difficulty = investigation_fact_difficulty(
            db, target=target, fact_key=key, investigator=investigator,
        )
        lane["difficulty"] = difficulty
        if (
            not investigation_fact_is_gone(db, target, key)
            and float(lane["effort"]) >= difficulty
        ):
            lane["mastered"] = True
    payload = _dossier_payload_map(db, dossier_id)
    payload[INVESTIGATION_CLUES_KEY] = clues
    db.update_decree_dossier_payload(int(dossier_id), payload)
    return credited



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
    - 声明值只作**强度**（0..1，clamp），本月实投由引擎按承办人真实处境折算
      （investigation_monthly_capacity：能力／是否到差／0092 未结差务带宽）；
      **无单月硬顶、无最低在查月数 floor**——两者已随旧轨退役（#1896 明文），
      人物真下死力当月查出来就是查出来，不另加人为月闸；
    - 每条事实有自己的难度（investigation_fact_difficulty），累计实投达到该条
      难度即记 mastered——无统一阈值，也无"一月不许坐实"；
    - **fact_key 必填**：本月查哪条罪证是人物的选择，代码不代选（CLAUDE.md P6）；
      未指明即本月无下手处 → 零投入，不自动路由到任何 lane；
    - 敷衍／停办（intensity<=0）就是本月零投入，不产查获、也不改实证；
    - 奏报自称成功不入本函数（P6：呈现层与实况分轨，谎奏不造罪不抹证）。
    """
    lanes = seed_investigation_fact_lanes(
        db, dossier_id, target, investigator=investigator, commit=False,
    )
    declared = _declared_intensity(intensity)
    if declared is None:
        # 非有限／非数值不是"零投入"：调用方（4a 声明读口）已先拒收无效声明，
        # 这里再守一道，避免任何直调把 NaN/inf 当合法强度折算成实投。
        declared = 0.0
    live = set(live_investigation_fact_keys(db, target))
    blocked = globally_used_fact_keys(db, except_dossier_id=int(dossier_id))
    capacity = investigation_monthly_capacity(
        db, investigator, dossier_id=int(dossier_id), target=target,
    )
    amount = declared * capacity

    bound = str(fact_key or "").strip()
    if bound and (bound not in live or bound in blocked):
        # 线索只助其所指实有证据：指向不存在/已被别案查获的事实 → 确定性丢弃。
        _consume_monthly_clues(
            db, dossier_id, target, investigator, lanes,
            live=live, blocked=blocked, capacity=capacity,
        )
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
            # 本案已掌握该证：人物不再重复投入。独立新证线索仍按到差消费。
            credited = _consume_monthly_clues(
                db, dossier_id, target, investigator, lanes,
                live=live, blocked=blocked, capacity=capacity,
            )
            _write_fact_lanes(db, dossier_id, lanes, commit=commit)
            return {
                "bound_fact_key": bound, "effort_applied": 0.0,
                "clue_credited": credited, "mastered": [],
                "units": investigation_lane_actual_units(db, int(dossier_id)),
            }
    if not bound or amount <= 0.0 or not lanes:
        # 无下手处／敷衍停办／未到差（capacity=0）／空 lane 集：确定零投入。
        # 人已到差时，真实线索仍各自助它所指的实证（一次性）。
        credited = _consume_monthly_clues(
            db, dossier_id, target, investigator, lanes,
            live=live, blocked=blocked, capacity=capacity,
        )
        _write_fact_lanes(db, dossier_id, lanes, commit=commit)
        return {
            "bound_fact_key": bound, "effort_applied": 0.0,
            "declared_intensity": declared, "capacity": capacity,
            "clue_credited": credited, "mastered": [],
            "units": investigation_lane_actual_units(db, int(dossier_id)),
        }

    mastered_now: List[str] = []
    applied_amount = 0.0
    for lane in lanes:
        key = str(lane["fact_key"])
        if key != bound:
            continue
        difficulty = investigation_fact_difficulty(
            db, target=target, fact_key=key, investigator=investigator,
        )
        lane["difficulty"] = difficulty
        # 毁证只看 spoiled 账：已毁事实不再投入。能力为零的 inf 仍入账，
        # effort >= inf 为假所以不掌握。早退会跳过后面的独立来源消费。
        if not investigation_fact_is_gone(db, target, key):
            lane["effort"] = float(lane.get("effort") or 0.0) + amount
            lane["months"] = int(lane.get("months") or 0) + 1
            applied_amount = amount
            # 掌握证据 ≠ 已经依法清算 ≠ 自动翻轴：只落 mastered，不写依律/翻轴。
            if not lane.get("mastered") and float(lane["effort"]) >= float(difficulty):
                lane["mastered"] = True
            if lane.get("mastered"):
                mastered_now.append(key)
        break
    credited = _consume_monthly_clues(
        db, dossier_id, target, investigator, lanes,
        live=live, blocked=blocked, capacity=capacity,
    )
    _write_fact_lanes(db, dossier_id, lanes, commit=commit)
    return {
        "bound_fact_key": bound,
        "effort_applied": applied_amount,
        "declared_intensity": declared,
        "capacity": capacity,
        "clue_credited": credited,
        "mastered": mastered_now,
        "units": investigation_lane_actual_units(db, int(dossier_id)),
    }


def _resolve_investigation_knowledge(
    db: Any, target: str, declared_source: str = "", *, dossier_id: int = 0,
) -> str:
    """解出被查者的知情来源（真实传话声明 ∩ 真实关系边），解不出返回空串。

    判据沿 ``_investigation_knowledge_known``：须有案卷已声明的真实传话，且
    递话人在账本里确与该目标有 0081 关系边。声明里带了 knowledge_source 就
    优先按它核（人物指名了谁递的话）；没带则回本案已声明的传话记录里找——
    知情是**跨月持续**的事实，上月真递到的话本月照样成立，不该因为本次
    声明没重复附上来源就当作不知情。
    """
    who = str(declared_source or "").strip()
    if who and _investigation_knowledge_known(
        db, target, who, dossier_id=int(dossier_id or 0),
    ):
        return who
    for tip in _investigation_tips(db, int(dossier_id or 0), str(target or "").strip()):
        source = str(tip.get("source") or "").strip()
        if source and _investigation_knowledge_known(
            db, target, source, dossier_id=int(dossier_id or 0),
        ):
            return source
    return ""


def _investigation_knowledge_known(
    db: Any, target: str, source: str, *, dossier_id: int = 0,
) -> bool:
    """被查者是否真知自己被查：须有**真实传话声明**＋账本里真实可递话的关系。

    开案本身不等于目标知情（那是"开案即全知"的漏洞）；关系边存在也不等于
    话真递到了——两者都得有：①本案 4a 声明过此人经关系网把话递到（落
    ``investigation_tips``，真实声明）；②此人在账本里确与该目标有关系边
    （0081 有向边，任意方向皆可：庇护、连坐、亲党皆有可能递话）。
    无声明／查无此人／无此边 → 确定性判未知情，其毁证与压案声明被拒。
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
    # 传话记录与关系边必须是同一人。别人递过话，不能把未递话的关系人算成知情来源。
    if not any(
        str(tip.get("source") or "").strip() == who
        for tip in _investigation_tips(db, dossier_id, name)
    ):
        return False
    return any(
        str(edge["source"]) == who or str(edge["target"]) == who
        for edge in db.get_relation_edge_events(person=name)
    )


def _investigation_tips(db: Any, dossier_id: int, target: str) -> List[Dict[str, object]]:
    """本案已声明的通风报信（递话人 + 回合），知情判定的声明真源。"""
    return [
        tip for tip in _tip_records(db, dossier_id)
        if not target or str(tip.get("target") or target) == target
    ]


def _tip_records(db: Any, dossier_id: int) -> List[Dict[str, object]]:
    if not int(dossier_id or 0):
        return []
    raw = _dossier_payload_map(db, dossier_id).get(INVESTIGATION_TIPS_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, Mapping)]


def investigation_tip_records(db: Any, dossier_id: int) -> List[Dict[str, object]]:
    """4a 供料读口：本案已声明的真实通风报信。"""
    return _tip_records(db, dossier_id)


def investigation_action_records(db: Any, dossier_id: int) -> List[Dict[str, object]]:
    """4a 供料读口：本案已落账的人物真实行动声明（查法／压案）。"""
    if not int(dossier_id or 0):
        return []
    raw = _dossier_payload_map(db, dossier_id).get(INVESTIGATION_ACTS_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, Mapping)]


def apply_investigation_spoliation(
    db: Any,
    *,
    target: str,
    fact_key: str,
    effect: str = "harder",
    knowledge_source: str = "",
    dossier_id: int = 0,
    origin_ref: str = "",
    turn: Optional[int] = None,
    commit: bool = False,
) -> Dict[str, object]:
    """毁证落账口：按对应事实改可查性，不团灭、不改真相底。

    知情与反应归人物（P6）：本函数只处理其**真实选择**的后果，并且要求人物确实
    经真实传话声明知情（knowledge_source）——未知情不替其毁证，知情也不强制毁证。
    'gone' 之后该事实永不可查——关案重开、另起新案都不恢复（真源在 (target, fact_key)）。
    """
    name = str(target or "").strip()
    key = str(fact_key or "").strip()
    if not name or not key:
        raise CovertContractError("毁证落账缺少调查对象或事实键")
    if not _investigation_knowledge_known(
        db, name, knowledge_source, dossier_id=int(dossier_id or 0),
    ):
        # fail-closed：无真实传话声明就不毁证，也不改任何实证。
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


def _investigation_fact_of(contract: Mapping[str, object]) -> str:
    """密令合同自陈的线索所指事实（空＝不带指针，按 ADR 0098 兜底路由）。"""
    delivery = contract.get("delivery") if isinstance(contract.get("delivery"), Mapping) else {}
    return str(
        contract.get("investigation_fact") or delivery.get("investigation_fact") or ""
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
    fact_key: str = "",
    commit: bool = False,
) -> int:
    """同目标汇案：并案卷。只有带事实指针的来源才留下待消费线索。

    重复的无指针下令不是来源。pending_action_id 与聊天记录只是确认闸，
    不制造线索。已落库的空指针旧线索仍由月核算按 ADR 0098:11 消费。
    """
    dossier = db.get_dossier_for_secret_order(int(order_id))
    if dossier is None:
        raise CovertContractError("查案合流缺少案卷")
    did = int(dossier["id"])
    payload = _dossier_payload_map(db, did)
    turn = int(getattr(state, "turn", 0) or 0)
    sources = payload.get(INVESTIGATION_PROVENANCE_KEY)
    if not isinstance(sources, list):
        sources = []
    sources.append({
        "pending_action_id": int(pending_action_id or 0),
        "origin_chat_message_ids": [int(x) for x in origin_chat_message_ids],
        "turn": turn,
    })
    payload[INVESTIGATION_PROVENANCE_KEY] = sources
    key = str(fact_key or "").strip()
    if key:
        clues = payload.get(INVESTIGATION_CLUES_KEY)
        if not isinstance(clues, list):
            clues = []
        clues.append({
            "pending_action_id": int(pending_action_id or 0),
            "origin_chat_message_ids": [int(x) for x in origin_chat_message_ids],
            "fact_key": key,
            "turn": turn,
            "credited": False,
        })
        payload[INVESTIGATION_CLUES_KEY] = clues
    db.update_decree_dossier_payload(did, payload, commit=commit)
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


def _declared_intensity(raw: object) -> Optional[float]:
    """把人物声明的投入强度读成 0..1 的有限数字；读不出即 None（=无效声明）。

    合同是 DELTA_SCHEMA 的 0..1 有限数。``float()`` 单独不够：``float("NaN")``
    与 ``float("inf")`` 都成功，而 clamp 对 NaN 不动（min/max 遇 NaN 返回原值），
    于是 "NaN" 会被洗成满额投入、``inf`` 会被 clamp 成 1.0——两者都不是人物
    的声明，只是坏产物。故先验有限性再 clamp；越界仍按旧口径夹到 0..1
    （人物写 1.2 是"下了死力"，不是无效声明）。
    """
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return max(0.0, min(1.0, value))


def _investigation_declaration(
    sel: Mapping[str, object] | None,
) -> Dict[str, object]:
    """#1896 4a 对查案密令的声明读口：查法/投入强度/所查事实/传话/知情反应。

    形状（ADR 0120 后出查案修订）——按人物当月真实办事声明，不读自由文本：
    - effort:   0..1 的**投入强度**（敷衍/停办 → 0）。只是"下了多大劲"，
                引擎另按承办人真实处境（能力/是否到差/未结差务带宽）折算本月实投。
                缺声明或不是数字 = **无效声明**（invalid），不是合法的零投入——
                明确停办只有一种写法：effort: 0。
    - fact_key: str，本月下手的罪证；人物没下手处就不给，代码不代选。
    - method:   查法（人物本月怎么查，原样落账）
    - tip_off:  {source} 真实通风报信：确有人经关系网把话递到被查者
    - spoliation: {effect, fact_key} 被查者知情后的毁证选择
    - suppression: {form} 被查者知情后的压案（行贿说项之类）声明

    奏报（memorial_text）不在此读口内：谎奏不造罪、不抹证（P6 实况/奏报分轨）。
    """
    item = sel if isinstance(sel, Mapping) else {}
    out: Dict[str, object] = {}
    raw_effort = item.get("effort", item.get("投入"))
    if raw_effort is None:
        out["invalid"] = "查案密令缺少 effort 声明（敷衍/停办请显式给 0）"
    else:
        intensity = _declared_intensity(raw_effort)
        if intensity is None:
            out["invalid"] = "查案密令的 effort 不是 0..1 的有限数字"
        else:
            out["intensity"] = intensity
    fact = str(item.get("fact_key", item.get("所查事实")) or "").strip()
    if fact:
        out["fact_key"] = fact
    raw_method = item["method"] if "method" in item else item.get("查法")
    if raw_method is not None and not isinstance(raw_method, (Mapping, list)):
        method = str(raw_method)
        if method != "":
            out["method"] = method
    tip = item.get("tip_off", item.get("通风报信"))
    if isinstance(tip, Mapping):
        source = str(tip.get("source", tip.get("递话人")) or "").strip()
        if source:
            out["tip_off"] = {"source": source}
    spoil = item.get("spoliation", item.get("毁证"))
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
    suppress = item.get("suppression", item.get("压案"))
    if isinstance(suppress, Mapping):
        raw_form = suppress["form"] if "form" in suppress else suppress.get("方式")
        if raw_form is not None and not isinstance(raw_form, (Mapping, list)):
            form = str(raw_form)
            if form != "":
                out["suppression"] = {"form": form}
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
        if "note" in sel:
            raw_note = sel.get("note")
        elif "备注" in sel:
            raw_note = sel.get("备注")
        else:
            raw_note = None
        if raw_note is None or isinstance(raw_note, (Mapping, list)):
            # #1897：没有推演者给出的正文就不写说明。机器拼的执行态句子会占住同一 note。
            note = ""
        else:
            # 仅空白也是原文，原样写入，禁 strip 判空改成 ""。
            note = str(raw_note)
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
    sel: Mapping[str, object] | None,
    target: str,
    investigator: str,
    turn: int,
) -> Dict[str, object]:
    """查案密令的逐证落账（#1896）。幂等键＝(dossier, turn)，重开只续未成核算。

    无效声明（缺 effort／effort 非数字或非有限／只给了旧执行态）不是合法的
    零投入：拒收、不写实况行，由月链把本月 4a 产物标成 invalid 重来一次
    （#1846 失效与重起契约）。

    人物知情与反应按真实因果承接：知情来源解自案卷已落的传话记录（跨月持续），
    毁证与压案共用该判定，未知情不替其落账（见 ``_resolve_investigation_knowledge``）。
    """
    did = int(dossier["id"])
    oid = int(order["id"])
    rejected_reactions: List[Dict[str, object]] = []
    # 同月重入不重复施加投入：实况轨已有本月行即说明本月已核算过。lane 累加本身
    # 不带幂等键，若不在此拦一道，同一 turn 内被扫两次就会把力气算两遍。
    existing = db.conn.execute(
        "SELECT id, units FROM dossier_actual_progress "
        "WHERE dossier_id=? AND turn=? LIMIT 1",
        (did, int(turn)),
    ).fetchone()
    declaration = _investigation_declaration(sel)
    invalid = str(declaration.get("invalid") or "").strip()
    if invalid:
        return {
            "order_id": oid,
            "dossier_id": did,
            "rejected": True,
            "invalid": True,
            "category": "invalid_enum",
            "report_section": "covert_exec_selections",
            "reason": f"密令 {oid} 查案声明无效：{invalid}",
            "item": sel or {"order_id": oid},
        }
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
    # 真实传话声明先落账：知情判定的唯一来源就是它（关系边存在不算）。
    tip = declaration.get("tip_off")
    tip_source = str(tip.get("source") or "").strip() if isinstance(tip, Mapping) else ""
    if tip_source:
        _append_investigation_log(db, did, INVESTIGATION_TIPS_KEY, {
            "source": tip_source, "turn": int(turn), "target": target,
        })
    # 知情核算走案卷**已落**的真实传话记录（本月新落的也在内），而不是只取本次
    # 附带的那一个 source：知情是跨月持续的事实——上月真递到的话，本月照样知情。
    # 只读本次附带字段会让「先报信、次月毁证」这种真实因果承接落空
    # （大理寺 R5：报信真实、毁证声明合法，却因取不到来源而 spoiled=[]）。
    knowledge_source = _resolve_investigation_knowledge(
        db, target,
        str(
            (declaration["spoliation"].get("knowledge_source") or "")
            if isinstance(declaration.get("spoliation"), Mapping) else ""
        ),
        dossier_id=did,
    )
    known = bool(knowledge_source)
    acts = {
        key: declaration[key] for key in ("method",)
        if declaration.get(key)
    }
    suppression = declaration.get("suppression")
    if isinstance(suppression, Mapping) and suppression.get("form"):
        if known:
            acts["suppression"] = dict(suppression)
        else:
            # 未知情不替其压案：不落这项事实，也不改任何实证（P6 人物决定归人物，
            # 但引擎不替一个不知情的人记下他"压了案"）。
            rejected_reactions.append({
                "reaction": "suppression", "form": str(suppression.get("form") or ""),
                "reason": "无真实关系网知情来源，不承接压案声明",
            })
    if acts:
        _append_investigation_log(db, did, INVESTIGATION_ACTS_KEY, {
            "turn": int(turn), "investigator": investigator, **acts,
        })
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
            # 知情来源用上面解出的（跨月承接的）那个，不再只取本次附带字段：
            # 上月真报的信本月仍然成立，无须重复声明。
            spoiled_result = apply_investigation_spoliation(
                db, target=target, fact_key=spoil_key,
                effect=str(spoliation.get("effect") or "harder"),
                knowledge_source=knowledge_source,
                dossier_id=did,
                origin_ref=f"dossier:{did}", turn=turn, commit=False,
            )
    units = float(result.get("units") or 0.0)
    sel_map = sel if isinstance(sel, Mapping) else {}
    if "note" in sel_map:
        raw_note = sel_map.get("note")
    elif "备注" in sel_map:
        raw_note = sel_map.get("备注")
    else:
        raw_note = None
    if raw_note is None or isinstance(raw_note, (Mapping, list)) or str(raw_note) == "":
        note = f"查案实况：本月投入 {result.get('effort_applied', 0.0):g}，已掌握 {units:g} 条"
    else:
        note = str(raw_note)
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
    if rejected_reactions:
        applied["rejected_reactions"] = rejected_reactions
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
            execution_note=str(verdict.get("note") or ""),
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
