"""急务分拣＋票拟生成（#656 / ADR 0093 前半）：DECISION 待核议通道的邸报头版。

分拣人唯一规则（票面 F3.1，纯确定性读取现有 office/faction、不新增中立排序器）：
  1. 主分拣人＝内阁首辅（active 明臣 office LIKE '%首辅%'）；
  2. 缺位顶补＝司礼监掌印（office LIKE '%司礼监掌印%'；r2 裁决 B1：`%掌印%`
     会误吞御马监掌印等无关衙门掌印，角色破面——收窄为司礼监掌印）；
  3. 多行命中按 gatekeeper 先例 ORDER BY office_type,office,name 取第一；
  4. 双双缺位＝本月无分拣、无头版（全量邸报照旧可读）；
  5. 首辅与掌印同时在位时首辅分拣、掌印不参与。

产文保护（票面 F3.3 / ADR 0142/0143）：LLM 自由文本**原样落库**——本模块对输出只做
shape 校验（顶层合法／必需字段在），零 regex、零词表、零裁剪、零改写、零奏疏模板；
奏疏体零数值只在输入侧以正向措辞落实（prompt＋定性盘面投影）。

载体（票面 F2）：复用既有 pending_decisions 表，kind='rescript_draft' 行；只投影既有
issue 盘面事实，不新建 issue。event_id 绑定走 bind_decisions_to_candidate_events 同款
纪律——权威快照（喂给 LLM 的 issue 盘面投影）为准，不信 LLM 回显；无对应 issue 的
急务用确定性合成 id `urgent:{turn}:{idx}`。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from openai import APIConnectionError, APIStatusError, APITimeoutError

from ming_sim.agents import run_agent_text
from ming_sim.assets import strip_json_fence
from ming_sim.llm_model import llm_unavailable_from_error
from ming_sim.db import GameDB
from ming_sim.decree_vocabulary import (
    RESCRIPT_ROUTABLE_ACTION_TYPES,
    TARGET_KINDS,
    _DRAFT_CAPABILITY_KEYS,
    derive_draft_capability,
)
from ming_sim.error_pack import error_packs_root
from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.models import GameState, reign_period_label
from ming_sim.token_stats import tlog

MAX_RESCRIPT_DRAFTS = 5

# #657 C.3 层 A option 必填键（缺一 shape 失败）；draft_capability 由服务端派生写入。
# #1624 / PR#1719：required/present/action-conditional 为 typed 单源——
# layer_a_option_shape / normalize / 初拟·改票 prompt renderer 共用；
# 禁 agents 手抄、禁 markdown 平行键表、禁只列 capability 后用「按需填写」代规则。
_LAYER_A_REQUIRED_KEYS = (
    "label", "hint", "action_type", "target_kind", "target_id", "locality_scope",
)
_LAYER_A_PRESENT_KEYS = (
    "assignee_name", "region_id", "transaction_category",
)
# locality 三值/别名唯一真源 = execution_pressure.normalize_locality_scope（#1624 删平行）

# 生成侧军饷类别；层 A 等值映射到内部 grant_action=协饷（禁同义词/散文）。
_GRANT_KIND_ARMY_PAY = "army_pay"

# 七类 action-conditional 必填/互斥/枚举/条件必填（纯 shape，无 DB grounding）。
# assignment 的 category|assignee 任一已由 structured_decree 组合闸承载；
# grant_kind↔grant_action 互斥与金额 shape 仍走下方 grant 专缝（同 shape 暴露）。
# optional_keys 仅供 renderer 列类相关可填键；validator 不因 optional 放宽必填。
# appoint/punish 枚举动态取 FieldSpec（−{无}），禁第三份字面量闭集。
_LAYER_A_ACTION_CONDITIONAL: Dict[str, Dict[str, object]] = {
    "assignment": {
        "optional_keys": (
            "deadline_months", "title", "commitment_kind", "stop_condition",
            "end_turn", "due_turn",
        ),
        "required_when": (
            ("commitment_kind", "until_stop", ("stop_condition",)),
        ),
    },
    "military_order": {
        "required_nonempty": ("assignee_name",),
        # 与 admission 同形：调驻可无期限；限期出战须 due/deadline；双缺拒收。
        "require_any_nonempty": (("station", "due_turn", "deadline_months"),),
        "target_kind_in": frozenset({"army"}),
        "optional_keys": ("station", "due_turn", "deadline_months", "office"),
    },
    "grant_allocation": {
        "optional_keys": (
            "grant_kind", "grant_action", "amount", "account", "purpose",
            "cadence", "execution_surface",
        ),
        "mutex_nonempty_pairs": (("grant_kind", "grant_action"),),
    },
    "appointment": {
        "required_nonempty": ("appoint_action",),
        "enum_in_dynamic": {"appoint_action": "appoint_actions_effective"},
        "required_when": (
            ("appoint_action", "任命", ("office",)),
        ),
        "target_kind_in": frozenset({"character"}),
        "optional_keys": ("office", "name", "appointment_tenure"),
    },
    "punishment": {
        "required_nonempty": ("punish_action",),
        "enum_in_dynamic": {"punish_action": "punish_actions_effective"},
        "positive_amount_when": ("punish_action", "罚俸"),
        "forbid_positive_amount_unless": ("punish_action", "罚俸"),
        "target_kind_in": frozenset({"character"}),
        "optional_keys": ("amount", "name"),
    },
    "authorization": {
        "require_any_nonempty": (("name", "assignee_name"),),
        "optional_keys": (
            "privilege", "summon_target", "name", "execution_surface",
        ),
    },
    "pacification": {
        "target_kind_in": frozenset({"character"}),
        "optional_keys": ("name", "deadline_months"),
    },
}
assert frozenset(_LAYER_A_ACTION_CONDITIONAL) == RESCRIPT_ROUTABLE_ACTION_TYPES

# 层 A 允许键 = C.3 必填/须在 + C.4 闭集 + draft_capability（服务端覆盖，LLM 自带不准）
# grant_kind：生成侧 machine discriminator（#1620）；层 A 映射后不落库。
_LAYER_A_ALLOWED_KEYS = frozenset(
    list(_LAYER_A_REQUIRED_KEYS)
    + list(_LAYER_A_PRESENT_KEYS)
    + [key for key, _default in _DRAFT_CAPABILITY_KEYS]
    + ["draft_capability", "grant_kind"]
)

# capability 闭集中的 str 透传键 / int 键（唯一派生；禁 normalize 再手抄一份）
_LAYER_A_CAPABILITY_STR_KEYS = tuple(
    key for key, default in _DRAFT_CAPABILITY_KEYS
    if isinstance(default, str)
    and key not in _LAYER_A_REQUIRED_KEYS
    and key not in _LAYER_A_PRESENT_KEYS
)
_LAYER_A_CAPABILITY_INT_KEYS = tuple(
    key for key, default in _DRAFT_CAPABILITY_KEYS if isinstance(default, int)
)


def _layer_a_resolve_enum_in(rule: Mapping[str, object]) -> Dict[str, frozenset]:
    """静态 enum_in + 动态 enum 源 → 统一 frozenset 映射。"""
    enums: Dict[str, frozenset] = {}
    static = rule.get("enum_in") or {}
    if isinstance(static, Mapping):
        for key, allowed in static.items():
            enums[str(key)] = frozenset(allowed)  # type: ignore[arg-type]
    dynamic = rule.get("enum_in_dynamic") or {}
    if isinstance(dynamic, Mapping):
        from ming_sim.action_materialize import (
            appoint_actions_effective,
            punish_actions_effective,
        )

        for key, source in dynamic.items():
            if source == "punish_actions_effective":
                enums[str(key)] = frozenset(punish_actions_effective())
            elif source == "appoint_actions_effective":
                enums[str(key)] = frozenset(appoint_actions_effective())
            else:
                raise RuntimeError(f"未知 layer-A dynamic enum 源：{source!r}")
    return enums


def _layer_a_action_conditional_view() -> Dict[str, Dict[str, object]]:
    """七类条件契约的 typed 视图（shape/normalize/renderer 共用）。"""
    out: Dict[str, Dict[str, object]] = {}
    for action in sorted(RESCRIPT_ROUTABLE_ACTION_TYPES):
        rule = _LAYER_A_ACTION_CONDITIONAL[action]
        entry: Dict[str, object] = {
            "required_nonempty": tuple(rule.get("required_nonempty") or ()),
            "require_any_nonempty": tuple(rule.get("require_any_nonempty") or ()),
            "required_when": tuple(rule.get("required_when") or ()),
            "optional_keys": tuple(rule.get("optional_keys") or ()),
            "mutex_nonempty_pairs": tuple(rule.get("mutex_nonempty_pairs") or ()),
            "enum_in": {
                key: tuple(sorted(allowed))
                for key, allowed in _layer_a_resolve_enum_in(rule).items()
            },
        }
        tk = rule.get("target_kind_in")
        if tk is not None:
            entry["target_kind_in"] = tuple(sorted(tk))  # type: ignore[arg-type]
        else:
            entry["target_kind_in"] = None
        if rule.get("positive_amount_when") is not None:
            entry["positive_amount_when"] = rule["positive_amount_when"]
        else:
            entry["positive_amount_when"] = None
        if rule.get("forbid_positive_amount_unless") is not None:
            entry["forbid_positive_amount_unless"] = rule[
                "forbid_positive_amount_unless"
            ]
        else:
            entry["forbid_positive_amount_unless"] = None
        out[action] = entry
    return out


def layer_a_option_shape() -> Dict[str, object]:
    """层 A option 受理契约 typed 单源（required/present/action-conditional）。

    与 normalize_rescript_layer_a_option / rescript_layer_a_prompt_contract 共用；
    action_conditional 承载七类必填/互斥/枚举/条件必填，禁止入口平行手抄。
    """
    return {
        "required_keys": _LAYER_A_REQUIRED_KEYS,
        "present_keys": _LAYER_A_PRESENT_KEYS,
        "action_types": tuple(sorted(RESCRIPT_ROUTABLE_ACTION_TYPES)),
        "action_conditional": _layer_a_action_conditional_view(),
        "grant_kind_army_pay": _GRANT_KIND_ARMY_PAY,
        "server_only_keys": ("draft_capability",),
        "capability_str_keys": _LAYER_A_CAPABILITY_STR_KEYS,
        "capability_int_keys": _LAYER_A_CAPABILITY_INT_KEYS,
    }


def _render_action_conditional_contract(conditional: object) -> str:
    """由 typed action_conditional 渲染 prompt 段（禁手抄规则）。"""
    if not isinstance(conditional, Mapping):
        return ""
    parts: List[str] = []
    for action in sorted(conditional):
        rule = conditional[action]
        if not isinstance(rule, Mapping):
            continue
        bits: List[str] = []
        req = rule.get("required_nonempty") or ()
        if req:
            bits.append("必填" + "/".join(str(k) for k in req))  # type: ignore[union-attr]
        for group in rule.get("require_any_nonempty") or ():
            bits.append("须具其一" + "|".join(str(k) for k in group))  # type: ignore[union-attr]
        enums = rule.get("enum_in") or {}
        if isinstance(enums, Mapping):
            for key in sorted(enums):
                allowed = enums[key]
                bits.append(
                    f"{key}∈" + "|".join(str(v) for v in allowed)  # type: ignore[union-attr]
                )
        for item in rule.get("required_when") or ():
            if not item or len(item) < 3:  # type: ignore[arg-type]
                continue
            ctrl, cval, rks = item[0], item[1], item[2]  # type: ignore[index]
            bits.append(
                f"当{ctrl}={cval}必填" + "/".join(str(k) for k in rks)  # type: ignore[union-attr]
            )
        tk = rule.get("target_kind_in")
        if tk:
            bits.append("target_kind∈" + "|".join(str(k) for k in tk))  # type: ignore[union-attr]
        pos_when = rule.get("positive_amount_when")
        if pos_when and len(pos_when) >= 2:  # type: ignore[arg-type]
            bits.append(f"当{pos_when[0]}={pos_when[1]}须正amount")  # type: ignore[index]
        forbid = rule.get("forbid_positive_amount_unless")
        if forbid and len(forbid) >= 2:  # type: ignore[arg-type]
            bits.append(f"非{forbid[1]}禁正amount")  # type: ignore[index]
        for pair in rule.get("mutex_nonempty_pairs") or ():
            bits.append(
                "互斥不得并存" + "+".join(str(k) for k in pair)  # type: ignore[union-attr]
            )
        opt = rule.get("optional_keys") or ()
        if opt:
            bits.append("可填" + "/".join(str(k) for k in opt))  # type: ignore[union-attr]
        if bits:
            parts.append(f"{action}（" + "；".join(bits) + "）")
    if not parts:
        return ""
    return "action-conditional：" + "。".join(parts) + "。"


def rescript_layer_a_prompt_contract() -> str:
    """初拟/改票共用：由 layer_a_option_shape 渲染层 A 完整受理契约。

    structured_decree_prompt_contract 承目标/属地/承办子契约；本块补
    required/present/action_types/action-conditional/grant_kind。
    禁 agents 手抄；禁复述 grounding 规则；禁锁本函数措辞。
    """
    shape = layer_a_option_shape()
    required = "/".join(str(k) for k in shape["required_keys"])  # type: ignore[arg-type]
    present = "/".join(str(k) for k in shape["present_keys"])  # type: ignore[arg-type]
    actions = "|".join(str(a) for a in shape["action_types"])  # type: ignore[arg-type]
    grant_kind = str(shape["grant_kind_army_pay"])
    server_only = "/".join(str(k) for k in shape["server_only_keys"])  # type: ignore[arg-type]
    conditional = _render_action_conditional_contract(shape.get("action_conditional"))
    return (
        "票拟层 A option 受理契约（与 normalize_rescript_layer_a_option 共用 shape）："
        f"每项 options[] 必填非空 {required}；"
        f"action_type∈{actions}；"
        f"{present} 三键必须输出（值可空串）；"
        + conditional
        + f"grant_allocation 军饷用 grant_kind={grant_kind}"
        f"（禁直写 grant_action=协饷；kind 与 grant_action 不得并存）；"
        f"非 grant_allocation 不得带 grant_kind；"
        f"禁止输出 {server_only}（服务端派生）。"
    )


def _enforce_layer_a_action_conditional(
    out: Dict[str, object],
    raw: Mapping[str, object],
    *,
    shape: Mapping[str, object],
) -> None:
    """按 shape.action_conditional 强制七类必填/互斥/枚举（写回 out）。"""
    action = str(out["action_type"])
    conditional = shape.get("action_conditional") or {}
    if not isinstance(conditional, Mapping):
        return
    rules = conditional.get(action) or {}
    if not isinstance(rules, Mapping):
        return

    def _raw_or_out(key: str) -> object:
        if key in out and out[key] is not None:
            return out[key]
        if key in raw:
            return raw[key]
        return None

    def _nonempty_str(key: str) -> str:
        val = _raw_or_out(key)
        if val is None:
            return ""
        return str(val).strip()

    def _is_meaningful(key: str) -> bool:
        """require_any 在场判定：空串/0/"0" 不算；非数字字符串算在场。"""
        val = _raw_or_out(key)
        if val is None or isinstance(val, bool):
            return False
        if isinstance(val, (int, float)):
            return val > 0
        text = str(val).strip()
        if not text:
            return False
        try:
            return int(text) > 0
        except (TypeError, ValueError):
            return True

    tk_in = rules.get("target_kind_in")
    if tk_in:
        allowed_tk = frozenset(str(x) for x in tk_in)  # type: ignore[union-attr]
        got = str(out.get("target_kind") or "").strip()
        if got not in allowed_tk:
            raise ValueError(
                f"票拟 option.{action}.target_kind 须为"
                f"{'|'.join(sorted(allowed_tk))}，得 {got!r}"
            )

    for key in rules.get("required_nonempty") or ():
        key_s = str(key)
        val = _nonempty_str(key_s)
        if not val:
            raise ValueError(f"票拟 option.{action} 缺必填：{key_s}")
        src = _raw_or_out(key_s)
        out[key_s] = str(src) if src is not None else val

    for group in rules.get("require_any_nonempty") or ():
        keys = tuple(str(k) for k in group)  # type: ignore[union-attr]
        if not any(_is_meaningful(k) for k in keys):
            raise ValueError(
                f"票拟 option.{action} 须具备其一：{'/'.join(keys)}"
            )
        for key_s in keys:
            if not _is_meaningful(key_s) or key_s in out:
                continue
            src = _raw_or_out(key_s)
            if isinstance(src, (int, float)) and not isinstance(src, bool):
                out[key_s] = int(src) if float(src) == int(src) else src
            else:
                out[key_s] = str(src).strip() if src is not None else ""

    enums = rules.get("enum_in") or {}
    if isinstance(enums, Mapping):
        for key, allowed in enums.items():
            key_s = str(key)
            val = _nonempty_str(key_s)
            if not val:
                continue
            allowed_set = frozenset(str(x) for x in allowed)  # type: ignore[union-attr]
            if val not in allowed_set:
                raise ValueError(
                    f"票拟 option.{action}.{key_s} 非法：{val!r}"
                )
            out[key_s] = val

    for item in rules.get("required_when") or ():
        if not item or len(item) < 3:  # type: ignore[arg-type]
            continue
        ctrl, cval, rks = str(item[0]), str(item[1]), item[2]  # type: ignore[index]
        if _nonempty_str(ctrl) != cval:
            continue
        for rk in rks:  # type: ignore[union-attr]
            rk_s = str(rk)
            if not _nonempty_str(rk_s):
                raise ValueError(
                    f"票拟 option.{action} 当 {ctrl}={cval} 时缺 {rk_s}"
                )
            src = _raw_or_out(rk_s)
            out[rk_s] = str(src) if src is not None else _nonempty_str(rk_s)

    for pair in rules.get("mutex_nonempty_pairs") or ():
        keys = tuple(str(k) for k in pair)  # type: ignore[union-attr]
        present = [k for k in keys if _nonempty_str(k)]
        if len(present) > 1:
            raise ValueError(
                f"票拟 option.{action} 互斥键不得并存：{'/'.join(present)}"
            )

    pos_when = rules.get("positive_amount_when")
    if pos_when and len(pos_when) >= 2:  # type: ignore[arg-type]
        ctrl, cval = str(pos_when[0]), str(pos_when[1])  # type: ignore[index]
        if _nonempty_str(ctrl) == cval:
            amt_raw = _raw_or_out("amount")
            try:
                if isinstance(amt_raw, bool) or amt_raw is None or amt_raw == "":
                    raise ValueError
                amount = int(amt_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"票拟 option.{action} {cval} 须正 amount"
                ) from exc
            if amount <= 0:
                raise ValueError(
                    f"票拟 option.{action} {cval} 须正 amount"
                )
            out["amount"] = amount

    forbid = rules.get("forbid_positive_amount_unless")
    if forbid and len(forbid) >= 2:  # type: ignore[arg-type]
        ctrl, cval = str(forbid[0]), str(forbid[1])  # type: ignore[index]
        if _nonempty_str(ctrl) != cval:
            amt_raw = _raw_or_out("amount")
            try:
                amount = int(amt_raw) if amt_raw not in (None, "") else 0  # type: ignore[arg-type]
            except (TypeError, ValueError):
                amount = 0
            if isinstance(amt_raw, bool):
                amount = 0
            if amount > 0:
                raise ValueError(
                    f"票拟 option.{action} 非 {cval} 不得带正 amount"
                )


def normalize_stop_condition(raw: object) -> str:
    """stop_condition 唯一保真缝（C.6）：仅 str 原文；None/空白→""；dict/list/其它→ValueError。

    供层 A normalize / choice 规范化 / mapper 共用——禁止平行拷贝。
    非空不 strip 落库（strip 只可在 until_stop 判空临时用）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        if not raw.strip():
            return ""
        return raw
    raise ValueError(
        f"stop_condition 须为 str（C.6），拒 {type(raw).__name__}"
    )


def normalize_rescript_layer_a_option(
    raw: object,
    *,
    generation_admission: bool = False,
) -> Dict[str, object]:
    """#657 层 A option shape 校验 + 服务端写 draft_capability（生产票拟/改票单真源）。

    自由文本（label/hint 等）strip 只作判空临时值，落库原文；
    draft_capability 一律服务端重算覆盖，禁止 LLM 自带为准。
    generation_admission=True：生成批次拒绝无 kind 直写 grant_action=协饷；
    内部 canonical 二次归一保持默认 False。
    """
    if not isinstance(raw, dict):
        raise ValueError("票拟 option 非 object（层 A shape）")
    shape = layer_a_option_shape()
    required_keys = shape["required_keys"]  # type: ignore[assignment]
    present_keys = shape["present_keys"]  # type: ignore[assignment]
    action_types = frozenset(shape["action_types"])  # type: ignore[arg-type]
    grant_kind_army_pay = str(shape["grant_kind_army_pay"])
    capability_str_keys = shape["capability_str_keys"]  # type: ignore[assignment]
    capability_int_keys = shape["capability_int_keys"]  # type: ignore[assignment]
    unknown = set(raw) - _LAYER_A_ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"票拟 option 含未知字段（整批 shape 错，F2.5/F3.3）：{sorted(unknown)}"
        )
    out: Dict[str, object] = {}
    for key in required_keys:  # type: ignore[union-attr]
        value = raw.get(key)
        if not isinstance(value, str) or not str(value).strip():
            raise ValueError(f"票拟 option 缺层 A 必填键或为空白：{key}")
        out[key] = str(value)  # 原文；strip 仅判空
    action_type = str(out["action_type"]).strip()
    if action_type not in action_types:
        raise ValueError(f"票拟 option.action_type 非七类 routable：{action_type!r}")
    out["action_type"] = action_type
    # #1620：grant_kind 仅 grant_allocation 合法；非 grant 不得因 allowed 白名单静默丢键。
    # 内部 canonical（无 grant_kind、grant_action=协饷）仍可二次归一——本闸只咬显式 kind。
    if action_type != "grant_allocation":
        raw_kind = raw.get("grant_kind") if "grant_kind" in raw else None
        if raw_kind is not None and str(raw_kind).strip():
            raise ValueError(
                f"非 grant_allocation 不得带 grant_kind：{raw_kind!r}"
            )
    target_kind = str(out["target_kind"]).strip()
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"票拟 option.target_kind 非法：{target_kind!r}")
    out["target_kind"] = target_kind
    # #1624：locality 归一唯一真源；禁止平行别名表，禁止按 target_kind 覆盖
    from ming_sim.execution_pressure import normalize_locality_scope
    out["locality_scope"] = normalize_locality_scope(out["locality_scope"])
    # C.3：三键必须在且为 str（可 ""）；禁缺键补全 / None→"" / str(value) 洗值
    for key in present_keys:  # type: ignore[union-attr]
        if key not in raw:
            raise ValueError(f"票拟 option 缺层 A 须在键：{key}")
        value = raw[key]
        if not isinstance(value, str):
            raise ValueError(
                f"票拟 option.{key} 须为 str（可空串），拒 {type(value).__name__}"
            )
        out[key] = value
    # 七类 action-conditional（与 shape/renderer 同真源；先于组合闸）
    _enforce_layer_a_action_conditional(out, raw, shape=shape)
    # #1624：层 A 即走共同组合校验（动作×目标×属地×承办），落库前不再另写平行闸
    from ming_sim.structured_decree import validate_structured_decree_combination
    validate_structured_decree_combination(out)
    # 其余 capability 闭集字段透传（有则规范化，无则由 derive 填默认）
    for key in capability_str_keys:  # type: ignore[union-attr]
        if key == "stop_condition":
            continue
        if key in raw and raw[key] is not None:
            out[key] = str(raw[key])
    if "stop_condition" in raw and raw["stop_condition"] is not None:
        out["stop_condition"] = normalize_stop_condition(raw["stop_condition"])
    # #1620：grant amount 不走通用 int()——由 require_grant_allocation_shape 独掌
    # （strict_int 拒 bool/float）；非 grant 整数字段维持既有 int()。
    int_keys = tuple(
        k for k in capability_int_keys  # type: ignore[union-attr]
        if k != "amount" or action_type != "grant_allocation"
    )
    for key in int_keys:
        if key in raw and raw[key] is not None and raw[key] != "":
            try:
                out[key] = int(raw[key])  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"票拟 option.{key} 非法：{raw[key]!r}") from exc
    # #1620：grant 金额/account 走 require_grant_allocation_shape 唯一权威（与 mapper 同缝），
    # 禁残缺 option 上桌；空 account 不回写默认，免 draft_capability 漂移；
    # 非空 account 回写 shape 返回的 canonical（太仓→国库），与显式国库同 capability。
    # amount 传 raw 原值；用返回值写 out["amount"]（honorific 无则不写）。
    # grant_kind=army_pay → 内部 grant_action=协饷；kind 与显式 action 不得并存；
    # 生成批次禁无 kind 直写协饷；内部 canonical 二次归一仍可（generation_admission=False）；
    # 协饷五字段复用 require_explicit_xiexang_fields，不补 purpose/target。
    if action_type == "grant_allocation":
        from ming_sim.action_materialize import (
            require_explicit_xiexang_fields,
            require_grant_allocation_shape,
        )

        grant_kind = ""
        if "grant_kind" in raw and raw["grant_kind"] is not None:
            grant_kind = str(raw["grant_kind"]).strip()
        raw_ga = ""
        if "grant_action" in raw and raw["grant_action"] is not None:
            raw_ga = str(raw["grant_action"]).strip()
        if grant_kind:
            if grant_kind != grant_kind_army_pay:
                raise ValueError(f"grant 非法 grant_kind：{grant_kind!r}")
            if raw_ga:
                raise ValueError(
                    f"grant_kind=army_pay 不得同时显式给 grant_action：{raw_ga!r}"
                )
            out["grant_action"] = "协饷"
        elif generation_admission and raw_ga == "协饷":
            raise ValueError(
                "生成侧军饷须用 grant_kind=army_pay，不得直接 grant_action=协饷"
            )
        input_account = str(out.get("account") or "").strip()
        shaped = require_grant_allocation_shape(
            grant_action=out.get("grant_action"),
            amount=raw.get("amount") if "amount" in raw else None,
            account=out.get("account"),
        )
        if "amount" in shaped:
            out["amount"] = shaped["amount"]
        if input_account:
            out["account"] = shaped["account"]
        if str(out.get("grant_action") or "").strip() == "协饷":
            explicit = require_explicit_xiexang_fields(
                amount=out.get("amount", 0),
                account=str(out.get("account") or ""),
                purpose=str(out.get("purpose") or ""),
                target_kind=str(out.get("target_kind") or ""),
                target_id=str(out.get("target_id") or ""),
                cadence=str(out.get("cadence") or ""),
            )
            out["amount"] = explicit["amount"]
            out["account"] = explicit["account"]
            out["purpose"] = explicit["purpose"]
            out["target_kind"] = explicit["target_kind"]
            out["target_id"] = explicit["target_id"]
    out["draft_capability"] = derive_draft_capability(out)
    return out


def select_triage_actor(db: GameDB) -> Optional[Dict[str, str]]:
    """F3.1 唯一分拣人选择规则：首辅优先、司礼监掌印顶补、重复命中取第一、双双缺位回 None。

    r2 裁决 B1（票面 F3.1「司礼监掌印」明文＋P3 角色保真）：兜底不得用宽模式
    `%掌印%`——御马监掌印太监与票拟/批红职权无关，不得成为分拣 actor。
    """
    for office_pattern in ("%首辅%", "%司礼监掌印%"):
        row = db.conn.execute(
            "SELECT name,office,faction FROM characters "
            "WHERE status='active' AND power_id='ming' AND office LIKE ? "
            "ORDER BY office_type,office,name LIMIT 1",
            (office_pattern,),
        ).fetchone()
        if row is not None:
            return {
                "name": str(row["name"]),
                "office": str(row["office"]),
                "faction": str(row["faction"] or ""),
            }
    return None


_TOP_ALLOWED_KEYS = frozenset({"items"})
_ITEM_ALLOWED_KEYS = frozenset({"title", "context", "options", "issue_id"})


def _assert_utf8(s: str, field: str) -> None:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as exc:  # noqa: BLE001
        raise ValueError(
            f"票拟字段含 SQLite 不可编码字符（整批 shape 错，F2.5）：{field} {exc}"
        ) from exc


def _parse_rescript_json_strict(raw: str) -> Dict[str, Any]:
    # r4 P1：围栏外 prose 必须走整批 shape 降级——容忍恰好覆盖全响应的单层围栏，
    # 围栏外任何非空白字符 → LLMContractError 整批降级；不得改 strip_json_fence 全局语义。
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if match:
        before = raw[: match.start()]
        after = raw[match.end() :]
        if before.strip() or after.strip():
            raise LLMContractError(
                f"急务票拟生成 输出含围栏外文字（整批 shape 错，F2.5）：围栏外含 prose，按票面应走整批降级\n原始输出：{raw[:800]}"
            )
        text = match.group(1).strip()
    else:
        text = raw.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMContractError(
            f"急务票拟生成 输出不是合法 JSON：{exc}\n原始输出：{raw[:800]}"
        ) from exc
    if not isinstance(data, dict):
        raise LLMContractError(
            f"急务票拟生成 输出不是合法 JSON：顶层必须是 JSON object\n原始输出：{raw[:800]}"
        )
    return data

_RESCRIPT_ISSUE_TEXT_FIELDS = ("title", "状态", "进度", "待办未解进度")


def _project_issue_qualitatively(issue: object) -> Optional[Dict[str, object]]:
    """单条 issue 的票拟输入侧定性投影（P4 / ADR 0142/0143 唯一通道）。

    字段白名单收窄（#656 A4 判词边界）：只携绑定所需 issue_id 与明确的定性/叙事
    文字字段；resolve_condition/fail_condition/stop_condition（含「结案条件」「失败
    条件」别名）等机器契约字段一律不进票拟输入——机器阈值串（如 seed_events 的
    public_support >60 / unrest <30）随所属字段整体消失，不做任何字符串内扫描/
    解析/替换。白名单外的未知字段（含任意嵌套结构）不透传——删除「任意字符串全
    透传」的根因。simulator 共用投影不动——只在票拟 payload 出口收窄。
    """
    if not isinstance(issue, dict):
        return None
    row: Dict[str, object] = {}
    if "issue_id" in issue:
        row["issue_id"] = issue["issue_id"]
    for field in _RESCRIPT_ISSUE_TEXT_FIELDS:
        value = issue.get(field)
        if isinstance(value, str) and value.strip():
            row[field] = value
    return row or None


def _project_region_targets(table: object) -> List[Dict[str, str]]:
    """Project the simulator's canonical typed region table into the target catalog."""
    return _project_board_targets(
        table,
        fields=("id", "name", "kind"),
        required=("id", "name", "kind"),
        label="region",
    )


def _project_army_targets(table: object) -> List[Dict[str, str]]:
    """Project Ming-controlled armies from the simulator's full army board."""
    armies = _project_board_targets(
        table,
        fields=("id", "name", "station", "owner_power"),
        required=("id", "name", "owner_power"),
        label="army",
    )
    return [
        {field: army[field] for field in ("id", "name", "station")}
        for army in armies
        if army["owner_power"] == "ming"
    ]


def _project_board_targets(
    table: object,
    *,
    fields: tuple[str, ...],
    required: tuple[str, ...],
    label: str,
) -> List[Dict[str, str]]:
    if table is None:
        return []
    try:
        cols = table["cols"]  # type: ignore[index]
        rows = table["rows"]  # type: ignore[index]
        indexes = {field: cols.index(field) for field in fields}
        targets = []
        for row in rows:
            if not isinstance(row, list):
                raise ValueError(f"canonical {label} target row 非 list：{row!r}")
            target = {}
            for field, index in indexes.items():
                value = row[index]
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"canonical {label} target {field} 非字符串：{value!r}"
                    )
                target[field] = (value or "").strip()
            targets.append(target)
        if any(not target[field] for target in targets for field in required):
            raise ValueError(f"canonical {label} target 含空 {'/'.join(required)}")
        return targets
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"canonical {label} target table 畸形") from exc


def build_rescript_draft_payload(
    state: GameState,
    narrative: str,
    simulator_payload: Dict[str, object],
    triage_actor: Dict[str, str],
) -> Dict[str, object]:
    """票拟生成 LLM 步的确定性输入（F1.3：零依赖 extractor 输出，只读盘面投影）。

    active_issues 取 simulator_payload 里已投影的一份再过票拟出口定性投影（0143
    输入侧投影唯一通道，issue_id 是权威绑定快照）；缺失时回空表并留痕（无盘面可
    投影＝无急务可选）。
    """
    raw_issues = simulator_payload.get("active_issues")
    if not isinstance(raw_issues, list):
        tlog("[rescript] simulator_payload 无 active_issues 投影，按空盘面处理。")
        raw_issues = []
    active_issues = [
        projected for projected in
        (_project_issue_qualitatively(issue) for issue in raw_issues)
        if projected is not None
    ]
    # #1620：非军饷 grant_action 闭集与 Layer-A 同源；军饷用 grant_kind=army_pay
    # （生成侧 machine discriminator），层 A 映射到内部 grant_action=协饷。
    from ming_sim.action_materialize import GRANT_ACTIONS

    return {
        "turn": {
            "year": state.year,
            "period": state.period,
            "turn": state.turn,
            "reign_period_label": reign_period_label(state.year, state.period),
        },
        "gazette": narrative,
        "triage_actor": dict(triage_actor),
        "active_issues": active_issues,
        "region_targets": _project_region_targets(simulator_payload.get("regions")),
        "army_targets": _project_army_targets(simulator_payload.get("armies")),
        "grant_actions": sorted(GRANT_ACTIONS - {"无", "协饷"}),
        "grant_kinds": [_GRANT_KIND_ARMY_PAY],
        "target": {"min_items": 3, "max_items": MAX_RESCRIPT_DRAFTS},
    }


def validate_rescript_draft_items(
    data: object,
    board_issue_ids: set[int],
) -> List[Dict[str, object]]:
    """shape 校验（F2.2/F2.5 整批响亮降级的判据面）＋权威快照绑定＋原样不变式（F3.3）。

    - 顶层非法（非 dict / 无 items list）→ raise ValueError（整批降级，本月无头版）；
    - 任一条目必需字段缺失或非法（title/context 非空字符串 / options 非 2-3 项 /
      option 须过层 A 单真源 normalize）→ raise ValueError 整批失败（F2.2/F2.5：
      不得保留合法项形成部分头版，不得把缺失洗成空串）；合法 `items=[]` 仍是
      「本月无急务」；
    - 自由文本零删改（CLAUDE.md P6 / F3.3）：strip 只作判空的临时值，落库一律原文；
    - option 经 normalize_rescript_layer_a_option：C.3 必填 + C.4 闭集；
      draft_capability 服务端重算；未知键响亮失败（不再接受仅 label/hint 两键）；
    - 处理条目前先校验 items 总数：超过 MAX_RESCRIPT_DRAFTS 即 raise ValueError
      整批响亮降级（#656 A1：不截断、不静默丢弃后项、不保留前五条，F2.5）；
    - item 层白名单外未知字段 → raise ValueError 整批失败（r2 B2）；
      issue_id 是唯一豁免的可选绑定键；
    - event_id 只采信出现在权威盘面里的 issue_id 回指（bind 同款纪律）；其余留给
      落库层合成 `urgent:{turn}:{idx}`。
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("票拟生成输出顶层非法：须为 {\"items\":[...]}")
    unknown_top = set(data) - _TOP_ALLOWED_KEYS
    if unknown_top:
        raise ValueError(
            f"票拟顶层含未知字段（整批 shape 错，F2.5/F3.3）：{sorted(unknown_top)}"
        )
    items = data["items"]
    if len(items) > MAX_RESCRIPT_DRAFTS:
        raise ValueError(
            f"票拟条目超上限：{len(items)} 条 > {MAX_RESCRIPT_DRAFTS}（整批失败，F2.5）"
        )

    def _required_text(item: Dict[str, object], field: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"票拟条目缺必需字段或为空白：{field}")
        _assert_utf8(value, field)
        return value  # 原样返回，零删改（F3.3）

    drafts: List[Dict[str, object]] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("票拟条目非 object（整批失败，F2.5）")
        unknown = set(raw) - _ITEM_ALLOWED_KEYS
        if unknown:
            raise ValueError(
                f"票拟条目含未知字段（整批 shape 错，F2.5/F3.3 零删改不静默省略）：{sorted(unknown)}"
            )
        title = _required_text(raw, "title")
        context = _required_text(raw, "context")
        raw_opts = raw.get("options")
        if not isinstance(raw_opts, list) or not (2 <= len(raw_opts) <= 3):
            raise ValueError(f"票拟条目 options 非 2-3 项（整批失败，F2.2）：{title!r}")
        options: List[Dict[str, object]] = []
        for opt in raw_opts:
            if not isinstance(opt, dict):
                raise ValueError(f"票拟 option 非 object（整批失败，F2.2）：{title!r}")
            # 层 A 单真源：完整 option + 服务端 draft_capability
            # 生成 admission：落实 grant_kind discriminator，拒直写协饷旁路
            try:
                normalized_opt = normalize_rescript_layer_a_option(
                    opt, generation_admission=True,
                )
            except ValueError as exc:
                raise ValueError(
                    f"票拟 option 层 A shape 失败（整批失败，F2.2/F2.5）：{title!r} {exc}"
                ) from exc
            # 自由文本 UTF-8 可编码性（label/hint 原文）
            _assert_utf8(str(normalized_opt.get("label") or ""), "label")
            _assert_utf8(str(normalized_opt.get("hint") or ""), "hint")
            options.append(normalized_opt)
        # options_json 序列化前再校验 ensure_ascii=False 场景的可编码性
        try:
            json.dumps(options, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError as exc:  # noqa: BLE001
            raise ValueError(
                f"票拟字段含 SQLite 不可编码字符（整批 shape 错，F2.5）：options {exc}"
            ) from exc
        draft: Dict[str, object] = {"title": title, "context": context, "options": options}
        # 权威快照为准：只认喂给 LLM 的 issue 盘面里真实存在的 issue_id（不信回显）。
        issue_id = raw.get("issue_id")
        if isinstance(issue_id, bool):
            issue_id = None
        elif isinstance(issue_id, int):
            pass
        elif isinstance(issue_id, str) and issue_id.strip().lstrip("-").isdigit():
            issue_id = int(issue_id.strip())
        else:
            issue_id = None
        if issue_id is not None and issue_id in board_issue_ids:
            draft["event_id"] = f"issue:{issue_id}"
        drafts.append(draft)
    return drafts


def _assert_region_targets_grounded(
    drafts: List[Dict[str, object]], region_target_ids: set[str]
) -> None:
    for draft in drafts:
        for option in draft["options"]:  # type: ignore[union-attr]
            if option["target_kind"] == "region" \
                    and option["target_id"] not in region_target_ids:
                raise ValueError(
                    f"票拟 option.target_id 不在同批 region_targets：{option['target_id']!r}"
                )


def _assert_army_targets_grounded(
    drafts: List[Dict[str, object]], army_target_ids: set[str]
) -> None:
    """仅 army target_id 对同批 army_targets 接地。

    military_order 的 target_kind/assignee_name 形状由层 A action-conditional
    单源在 normalize 强制；此处不平行复述。
    """
    for draft in drafts:
        for option in draft["options"]:  # type: ignore[union-attr]
            if option["target_kind"] == "army" \
                    and option["target_id"] not in army_target_ids:
                raise ValueError(
                    f"票拟 option.target_id 不在同批 army_targets：{option['target_id']!r}"
                )


def _board_issue_ids(active_issues: object) -> set[int]:
    ids: set[int] = set()
    if isinstance(active_issues, list):
        for item in active_issues:
            if isinstance(item, dict) and isinstance(item.get("issue_id"), int) \
                    and not isinstance(item.get("issue_id"), bool):
                ids.add(int(item["issue_id"]))
    return ids


def _write_degraded_note(turn: int, reason: str) -> None:
    """响亮降级的 error pack 附记：诊断目录留 JSON 注记（不写整包热备——结算未中止）。"""
    try:
        root = error_packs_root() / "rescript_draft_degraded"
        root.mkdir(parents=True, exist_ok=True)
        note = {
            "turn": int(turn),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (root / f"turn{int(turn)}.json").write_text(
            json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 — 附记是诊断旁路，任何异常不得拖垮结算
        tlog(f"[rescript] 降级附记写盘失败：{exc}")


def generate_rescript_draft(
    agent: Any,
    payload: Dict[str, object],
    turn: int,
) -> Optional[List[Dict[str, object]]]:
    """phase2 fan-out 第 N+1 路（N=同池 extractor 模块数）：跑一次票拟生成 LLM 调用并校验 shape。

    响亮降级契约（F2.5）按错误归属拆缝（r2 裁决 B3 / ADR 0005 / relation_brew 同款
    先例）：业务降级面只收声明类型——LLM 调用缝只收 typed LLMUnavailable；解析/shape
    校验缝只收 LLMContractError/ValueError。命中即 tlog 留痕＋诊断目录附记，返回 None，
    本月视作无头版。程序错（RuntimeError/KeyError/TypeError 等）**响亮上抛**——票拟
    业务降级 ≠ 代码故障降级，不再以「非承重支路」为由吞程序错误。
    """
    # payload 序列化是纯程序逻辑：其错误属代码侧错（ADR 0005），不在降级面内，响亮上抛。
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    tlog(f"[rescript] user payload total={len(payload_json)} chars (~{len(payload_json)//1.5:.0f} tok)")

    def _degrade(exc: Exception) -> None:
        tlog(f"[rescript] 票拟生成失败，本月视作无头版：{exc}")
        _write_degraded_note(turn, str(exc))

    try:
        raw = run_agent_text(agent, payload_json, tag="rescript-draft")
    except (APITimeoutError, APIConnectionError, APIStatusError) as error:  # 窄捕 provider 已知故障→译 typed（照抄 decree.py:1991 Z3 缝）
        _degrade(llm_unavailable_from_error(error, "急务票拟生成"))
        return None
    except LLMUnavailable as exc:  # LLM 调用缝：只收 typed 声明，程序错上抛
        _degrade(exc)
        return None
    try:
        data = _parse_rescript_json_strict(raw)
        region_targets = payload.get("region_targets")
        region_target_ids = {
            str(row["id"]) for row in region_targets
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        } if isinstance(region_targets, list) else set()
        army_targets = payload.get("army_targets")
        army_target_ids = {
            str(row["id"]) for row in army_targets
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        } if isinstance(army_targets, list) else set()
        drafts = validate_rescript_draft_items(
            data, _board_issue_ids(payload.get("active_issues"))
        )
        _assert_region_targets_grounded(drafts, region_target_ids)
        _assert_army_targets_grounded(drafts, army_target_ids)
    except (LLMContractError, ValueError) as exc:  # 解析/shape 缝：只收契约违约
        _degrade(exc)
        return None
    tlog(f"[rescript] 票拟生成 {len(drafts)} 条。")
    return drafts
