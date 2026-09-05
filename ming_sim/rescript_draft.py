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

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    combination_correction_feedback,
)
from ming_sim.token_stats import tlog

MAX_RESCRIPT_DRAFTS = 5
# #1624：月末首抽 typed 组合失败 → 共同纠错反馈有界重抽一次；耗尽仍 F2.5 整批降级。
RESCRIPT_COMBO_CORRECTION_RETRIES = 1
# #1746：单 option 契约失败字段（缺或错）→ 同一会话补交（不含首抽）；耗尽只剔该 option。
# decision: missing-field-heal-by-resume-not-drop / per-option-drop-after-heal-exhausted
# decision: heal-covers-illegal-values-too（不分缺失 vs 非法）
RESCRIPT_OPTION_FIELD_HEAL_RETRIES = 3


class RescriptOptionMissingFieldsError(ValueError):
    """可定位到单 option 的契约失败字段（#1746 补交分支）。

    缺字段、错值、任何不合契约的 option 字段均走同一补交回路
    （decision: heal-covers-illegal-values-too）；非组合错、非顶层/条目非法。
    """

    def __init__(
        self,
        message: str,
        *,
        missing_fields: Sequence[str],
        raw_option: object = None,
        field_reasons: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.missing_fields = tuple(str(f) for f in missing_fields)
        self.raw_option = raw_option
        self.field_reasons: Dict[str, str] = {
            str(k): str(v) for k, v in dict(field_reasons or {}).items()
        }
        super().__init__(message)


def _raise_option_missing_fields(
    message: str,
    *,
    missing_fields: Sequence[str],
    raw_option: object = None,
    field_reasons: Optional[Mapping[str, str]] = None,
) -> None:
    """抛可定位单 option 契约失败（#1746 heal-by-resume）。

    权威 shape/normalize 失败字段（缺或错）一律进本异常；不区分缺失 vs 非法。
    组合错误仍由 StructuredDecreeCombinationError 原样上抛。
    """
    raise RescriptOptionMissingFieldsError(
        message,
        missing_fields=missing_fields,
        raw_option=raw_option,
        field_reasons=field_reasons,
    )


def _note_failed(
    bucket: List[str],
    *fields: str,
    reasons: Optional[Dict[str, str]] = None,
    reason: str = "",
) -> None:
    """收集契约失败字段；去重且保序。可选写入结构化原因。"""
    for field in fields:
        key = str(field)
        if not key:
            continue
        if key not in bucket:
            bucket.append(key)
        if reasons is not None and reason and key not in reasons:
            reasons[key] = reason


# 兼容旧名（模块内历史调用点）
def _note_missing(bucket: List[str], *fields: str) -> None:
    _note_failed(bucket, *fields)


@dataclass(frozen=True)
class RescriptOptionMissingFailure:
    item_index: int
    option_index: int
    title: str
    missing_fields: Tuple[str, ...]  # 失败字段名（缺或错，同一补交列表）
    raw_option: object
    # 机面结构身份：补交请求显式携带、响应回指；不依赖 title/label 自由文。
    heal_id: str = ""
    field_reasons: Tuple[Tuple[str, str], ...] = ()


class RescriptOptionMissingFieldsBatch(ValueError):
    """一批 option 缺字段（validate isolate 模式一次收齐，供补交/剔除）。"""

    def __init__(self, failures: Sequence[RescriptOptionMissingFailure]) -> None:
        self.failures = list(failures)
        parts = [
            f"{f.title!r}#{f.option_index}:{','.join(f.missing_fields)}"
            for f in self.failures
        ]
        super().__init__("票拟 option 缺结构化字段：" + "; ".join(parts))

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
    missing_out: List[str],
    reasons_out: Optional[Dict[str, str]] = None,
) -> None:
    """按 shape.action_conditional 强制七类必填/互斥/枚举（写回 out）。

    字段契约失败（缺或错）写入 missing_out；不填占位值。
    互斥并存仍上抛 ValueError（非整单字段可补形态）。
    """
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

    def _fail(*fields: str, reason: str = "") -> None:
        _note_failed(missing_out, *fields, reasons=reasons_out, reason=reason)

    def _require_any_present(key: str) -> bool:
        """require_any 在场：通用非空串；due_turn/deadline_months 须正值。

        非空但不可解析为正整数 → 记该键失败（补交），不短路其它扫描。
        """
        if key in ("due_turn", "deadline_months"):
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
                _fail(key, reason=f"{action}.{key} 非法：{val!r}")
                return True  # 已记失败，不把该键当「未在场」再索 require_any 组
        return bool(_nonempty_str(key))

    tk_in = rules.get("target_kind_in")
    if tk_in:
        allowed_tk = frozenset(str(x) for x in tk_in)  # type: ignore[union-attr]
        got = str(out.get("target_kind") or "").strip()
        # target_kind 本身缺失时由 required 收集；已给出但不在闭集 → 补交
        if got and got not in allowed_tk:
            _fail(
                "target_kind",
                reason=(
                    f"{action}.target_kind 须为"
                    f"{'|'.join(sorted(allowed_tk))}，得 {got!r}"
                ),
            )

    for key in rules.get("required_nonempty") or ():
        key_s = str(key)
        val = _nonempty_str(key_s)
        if not val:
            _fail(key_s, reason=f"{action} 缺必填：{key_s}")
            continue
        src = _raw_or_out(key_s)
        out[key_s] = str(src) if src is not None else val

    for group in rules.get("require_any_nonempty") or ():
        keys = tuple(str(k) for k in group)  # type: ignore[union-attr]
        # 组内已有键被记为非法时不再重复索整组
        if any(k in missing_out for k in keys):
            continue
        if not any(_require_any_present(k) for k in keys):
            _fail(*keys, reason=f"{action} 须具备其一：{'/'.join(keys)}")
            continue
        for key_s in keys:
            val = _nonempty_str(key_s)
            if val and key_s not in out:
                src = _raw_or_out(key_s)
                out[key_s] = str(src) if src is not None else val

    enums = rules.get("enum_in") or {}
    if isinstance(enums, Mapping):
        for key, allowed in enums.items():
            key_s = str(key)
            val = _nonempty_str(key_s)
            if not val:
                continue
            allowed_set = frozenset(str(x) for x in allowed)  # type: ignore[union-attr]
            if val not in allowed_set:
                _fail(key_s, reason=f"{action}.{key_s} 非法：{val!r}")
                continue
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
                _fail(rk_s, reason=f"{action} 当 {ctrl}={cval} 缺 {rk_s}")
                continue
            src = _raw_or_out(rk_s)
            out[rk_s] = str(src) if src is not None else _nonempty_str(rk_s)

    for pair in rules.get("mutex_nonempty_pairs") or ():
        keys = tuple(str(k) for k in pair)  # type: ignore[union-attr]
        present = [k for k in keys if _nonempty_str(k)]
        if len(present) > 1:
            # 互斥并存：两字段都列入补交，由 LLM 择一保留
            _fail(
                *present,
                reason=f"{action} 互斥键不得并存：{'/'.join(present)}",
            )

    pos_when = rules.get("positive_amount_when")
    if pos_when and len(pos_when) >= 2:  # type: ignore[arg-type]
        ctrl, cval = str(pos_when[0]), str(pos_when[1])  # type: ignore[index]
        if _nonempty_str(ctrl) == cval:
            amt_raw = _raw_or_out("amount")
            if amt_raw is None or amt_raw == "":
                _fail("amount", reason=f"{action} {cval} 缺 amount")
            else:
                try:
                    if isinstance(amt_raw, bool):
                        raise ValueError("bool")
                    amount = int(amt_raw)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    _fail("amount", reason=f"{action} amount 非法：{amt_raw!r}")
                else:
                    if amount <= 0:
                        _fail(
                            "amount",
                            reason=f"{action} amount 须为正整数，得 {amount}",
                        )
                    else:
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
                _fail(
                    "amount",
                    reason=f"{action} 非 {cval} 不得带正 amount",
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

    #1746（heal-covers-illegal-values-too）：权威 shape/normalize 一次收齐失败字段
    （缺或错，不分类）→ RescriptOptionMissingFieldsError 走同一补交回路。
    组合错误仍 StructuredDecreeCombinationError（有界重抽）。禁止填占位合法值。
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
        # 未知键：整批 shape（F2.5/F3.3），非单 option 补交
        raise ValueError(
            f"票拟 option 含未知字段（整批 shape 错，F2.5/F3.3）：{sorted(unknown)}"
        )
    out: Dict[str, object] = {}
    failed: List[str] = []
    reasons: Dict[str, str] = {}

    def _fail(*fields: str, reason: str = "") -> None:
        _note_failed(failed, *fields, reasons=reasons, reason=reason)

    for key in required_keys:  # type: ignore[union-attr]
        key_s = str(key)
        if key_s not in raw or raw.get(key_s) is None:
            _fail(key_s, reason=f"缺必填：{key_s}")
            continue
        val = raw.get(key_s)
        if not isinstance(val, str):
            # 错类型与缺值同一补交列表（heal-covers-illegal-values-too）
            _fail(key_s, reason=f"{key_s} 须为 str，拒 {type(val).__name__}")
            continue
        if not val.strip():
            _fail(key_s, reason=f"缺必填：{key_s}")
            continue
        out[key_s] = val  # 原文；strip 仅判空

    action_type = ""
    if "action_type" in out:
        action_type = str(out["action_type"]).strip()
        if action_type not in action_types:
            _fail(
                "action_type",
                reason=f"action_type 非七类 routable：{action_type!r}",
            )
            action_type = ""
        else:
            out["action_type"] = action_type
            # #1620：grant_kind 仅 grant_allocation 合法
            if action_type != "grant_allocation":
                raw_kind = raw.get("grant_kind") if "grant_kind" in raw else None
                if raw_kind is not None and str(raw_kind).strip():
                    _fail(
                        "grant_kind",
                        reason=f"非 grant_allocation 不得带 grant_kind：{raw_kind!r}",
                    )

    if "target_kind" in out:
        target_kind = str(out["target_kind"]).strip()
        if target_kind not in TARGET_KINDS:
            _fail("target_kind", reason=f"target_kind 非法：{target_kind!r}")
        else:
            out["target_kind"] = target_kind

    if "locality_scope" in out:
        # #1624：locality 归一唯一真源；禁止平行别名表，禁止按 target_kind 覆盖
        from ming_sim.execution_pressure import normalize_locality_scope
        try:
            out["locality_scope"] = normalize_locality_scope(out["locality_scope"])
        except (TypeError, ValueError) as exc:
            _fail("locality_scope", reason=f"locality_scope 非法：{exc}")

    # C.3：三键必须在且为 str（可 ""）；禁缺键补全 / None→"" / truthiness 洗值
    for key in present_keys:  # type: ignore[union-attr]
        key_s = str(key)
        if key_s not in raw:
            _fail(key_s, reason=f"缺须在键：{key_s}")
            continue
        value = raw[key_s]
        if not isinstance(value, str):
            _fail(
                key_s,
                reason=f"{key_s} 须为 str（可空串），拒 {type(value).__name__}",
            )
            continue
        out[key_s] = value

    # 七类 action-conditional（与 shape/renderer 同真源；先于组合闸）
    if action_type:
        _enforce_layer_a_action_conditional(
            out, raw, shape=shape, missing_out=failed, reasons_out=reasons,
        )

    # #1624 组合：属地矩阵可在无 target_id 时独立判定（不得被无关缺字段跳过）；
    # 完整组合（含 target_id 必填）仅在 target_id 已给出时跑，避免把缺 target_id
    # 误送组合重抽。组合矛盾仍 StructuredDecreeCombinationError。
    if (
        action_type
        and "target_kind" in out
        and str(out.get("target_kind") or "").strip()
        and "locality_scope" in out
        and str(out.get("locality_scope") or "").strip()
        and "target_kind" not in failed
        and "locality_scope" not in failed
    ):
        from ming_sim.execution_pressure import (
            TargetLocalityMatrixError,
            assert_target_locality_matrix,
        )
        from ming_sim.structured_decree import StructuredDecreeCombinationError
        try:
            assert_target_locality_matrix(
                action_type=action_type,
                target_kind=str(out["target_kind"]),
                locality_scope=out.get("locality_scope"),
            )
        except TargetLocalityMatrixError as exc:
            raise StructuredDecreeCombinationError(
                str(exc), failed_fields=exc.failed_fields,
            ) from exc
        except ValueError as exc:
            raise StructuredDecreeCombinationError(
                str(exc),
                failed_fields=frozenset(
                    {"locality_scope", "target_kind", "action_type"}
                ),
            ) from exc
        tid = str(out.get("target_id") or "").strip()
        if tid and "target_id" not in failed:
            from ming_sim.structured_decree import (
                validate_structured_decree_combination,
            )
            validate_structured_decree_combination(out)

    # 其余 capability 闭集字段透传（有则规范化，无则由 derive 填默认）
    for key in capability_str_keys:  # type: ignore[union-attr]
        if key == "stop_condition":
            continue
        if key in raw and raw[key] is not None:
            # 不 truthiness 洗值；bool/非 str 原样 str() 仅作运输，权威 shape 再判
            out[key] = str(raw[key])
    if "stop_condition" in raw and raw["stop_condition"] is not None:
        try:
            out["stop_condition"] = normalize_stop_condition(raw["stop_condition"])
        except ValueError as exc:
            _fail("stop_condition", reason=str(exc))
    # #1620：grant amount 不走通用 int()——由 require_grant_allocation_shape 独掌；
    # 非 grant 整数字段维持既有 int()；失败进补交列表。
    int_keys = tuple(
        k for k in capability_int_keys  # type: ignore[union-attr]
        if k != "amount" or action_type != "grant_allocation"
    )
    for key in int_keys:
        if key in raw and raw[key] is not None and raw[key] != "":
            try:
                out[key] = int(raw[key])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                _fail(key, reason=f"{key} 非法：{raw[key]!r}")

    # #1620 grant：先 require_grant_allocation_shape 归一金额/account，
    # 协饷再 require_explicit_xiexang_fields（吃已归一 amount）——恢复既有 grant 语义。
    # 权威失败字段一律进补交，不分缺失/非法；不平行 strict_int/正金额预检。
    if action_type == "grant_allocation":
        from ming_sim.action_materialize import (
            IncompleteXiexangPayloadError,
            require_explicit_xiexang_fields,
            require_grant_allocation_shape,
        )

        grant_kind = ""
        if "grant_kind" in raw and raw["grant_kind"] is not None:
            grant_kind = str(raw["grant_kind"]).strip()
        raw_ga = ""
        if "grant_action" in raw and raw["grant_action"] is not None:
            raw_ga = str(raw["grant_action"]).strip()

        if generation_admission and not grant_kind and not raw_ga:
            # 双缺辨别：索其一；不预断 army_pay，不平行金额预检
            _fail(
                "grant_kind", "grant_action",
                reason="grant_allocation 须补 grant_kind 或 grant_action",
            )
        elif grant_kind:
            if grant_kind != grant_kind_army_pay:
                _fail("grant_kind", reason=f"grant 非法 grant_kind：{grant_kind!r}")
            elif raw_ga:
                _fail(
                    "grant_kind", "grant_action",
                    reason=(
                        f"grant_kind=army_pay 不得同时显式给 grant_action：{raw_ga!r}"
                    ),
                )
            else:
                out["grant_action"] = "协饷"
        elif generation_admission and raw_ga == "协饷":
            _fail(
                "grant_kind",
                reason="生成侧军饷须用 grant_kind=army_pay，不得直接 grant_action=协饷",
            )
        elif raw_ga:
            out["grant_action"] = raw_ga

        resolved_ga = str(out.get("grant_action") or "").strip()
        if resolved_ga:
            # account：保留 raw 原值给权威 shape（不 or "" 洗 false）
            if "account" in raw and raw["account"] is not None and "account" not in out:
                out["account"] = raw["account"]  # type: ignore[assignment]
            input_account_present = (
                "account" in out
                and out.get("account") is not None
                and str(out.get("account") or "").strip() != ""
            )
            try:
                shaped = require_grant_allocation_shape(
                    grant_action=resolved_ga,
                    amount=raw.get("amount") if "amount" in raw else None,
                    account=out.get("account") if "account" in out else (
                        raw.get("account") if "account" in raw else None
                    ),
                )
            except ValueError as exc:
                field = str(getattr(exc, "field", "") or "") or "grant_action"
                _fail(field, reason=str(exc))
            else:
                out["grant_action"] = shaped["grant_action"]
                if "amount" in shaped:
                    out["amount"] = shaped["amount"]
                if input_account_present:
                    out["account"] = shaped["account"]
                if str(out.get("grant_action") or "").strip() == "协饷":
                    # 吃 grant shape 已归一的 amount，恢复既有语义（"300"→300）
                    try:
                        explicit = require_explicit_xiexang_fields(
                            amount=out.get("amount", 0),
                            account=str(out.get("account") or ""),
                            purpose=str(
                                out.get("purpose")
                                if "purpose" in out
                                else (raw.get("purpose") if "purpose" in raw else "")
                                or ""
                            ),
                            target_kind=str(
                                out.get("target_kind") or raw.get("target_kind") or ""
                            ),
                            target_id=str(
                                out.get("target_id") or raw.get("target_id") or ""
                            ),
                            cadence=str(
                                out.get("cadence")
                                if "cadence" in out
                                else (raw.get("cadence") if "cadence" in raw else "")
                                or ""
                            ),
                        )
                    except IncompleteXiexangPayloadError as exc:
                        # 权威 failed_fields 全部进补交——不再分缺失/非法
                        _fail(
                            *[str(f) for f in exc.failed_fields],
                            reason=str(exc),
                        )
                    else:
                        out["amount"] = explicit["amount"]
                        out["account"] = explicit["account"]
                        out["purpose"] = explicit["purpose"]
                        out["target_kind"] = explicit["target_kind"]
                        out["target_id"] = explicit["target_id"]

    if failed:
        _raise_option_missing_fields(
            f"票拟 option 契约失败字段：{'/'.join(failed)}",
            missing_fields=tuple(failed),
            raw_option=raw,
            field_reasons=reasons,
        )

    # derive 需要 action_type 等必填已齐
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
    *,
    min_options: int = 2,
    max_options: int = 3,
    isolate_option_missing: bool = False,
) -> List[Dict[str, object]]:
    """shape 校验（F2.2/F2.5）＋权威快照绑定＋原样不变式（F3.3）。

    - 顶层非法（非 dict / 无 items list）→ raise ValueError（整批降级，本月无头版）；
    - 条目必需字段缺失或非法（title/context）→ raise ValueError 整批失败；
    - options 数量：首抽/常规默认 2–3（F2.2）；#1746 剔除后 min_options=1 仍可呈；
    - option 契约失败字段（#1746，缺或错同一补交）：isolate_option_missing=True
      时收齐为 RescriptOptionMissingFieldsBatch（补交／耗尽单 option 剔除）；
      False 时仍整批 ValueError（旧直调行为）；
    - 组合错误 → StructuredDecreeCombinationError（既有有界重抽，不动）；
    - 未知键等非整单字段可补的 option shape → 整批 ValueError（F2.5 其它分支）；
    - 合法 `items=[]` 仍是「本月无急务」（F2.3）；
    - 自由文本零删改；draft_capability 服务端重算。
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
    missing_failures: List[RescriptOptionMissingFailure] = []
    for item_index, raw in enumerate(items):
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
        if not isinstance(raw_opts, list) or not (
            min_options <= len(raw_opts) <= max_options
        ):
            raise ValueError(
                f"票拟条目 options 非 {min_options}-{max_options} 项"
                f"（整批失败，F2.2）：{title!r}"
            )
        options: List[Dict[str, object]] = []
        item_missing: List[RescriptOptionMissingFailure] = []
        for option_index, opt in enumerate(raw_opts):
            if not isinstance(opt, dict):
                raise ValueError(f"票拟 option 非 object（整批失败，F2.2）：{title!r}")
            # 层 A 单真源：完整 option + 服务端 draft_capability
            # 生成 admission：落实 grant_kind discriminator，拒直写协饷旁路
            try:
                normalized_opt = normalize_rescript_layer_a_option(
                    opt, generation_admission=True,
                )
            except StructuredDecreeCombinationError as exc:
                # typed 组合失败原样上抛（保留 failed_fields）；generate 可有界结构重抽。
                # 不得包成普通 ValueError 导致月末跳过纠错直接 F2.5。
                raise StructuredDecreeCombinationError(
                    f"票拟 option 结构组合失败：{title!r} {exc}",
                    failed_fields=exc.failed_fields,
                ) from exc
            except RescriptOptionMissingFieldsError as exc:
                if isolate_option_missing:
                    # 契约失败 quarantine 不得跳过其它 F2.5 面：UTF-8 仍咬 raw option
                    raw_for_miss = opt if isinstance(opt, dict) else exc.raw_option
                    if isinstance(raw_for_miss, dict):
                        _assert_utf8(str(raw_for_miss.get("label") or ""), "label")
                        _assert_utf8(str(raw_for_miss.get("hint") or ""), "hint")
                    reasons = tuple(
                        (str(k), str(v))
                        for k, v in dict(getattr(exc, "field_reasons", {}) or {}).items()
                    )
                    item_missing.append(RescriptOptionMissingFailure(
                        item_index=item_index,
                        option_index=option_index,
                        title=title,
                        missing_fields=tuple(exc.missing_fields),
                        raw_option=raw_for_miss,
                        heal_id=_option_heal_id(item_index, option_index),
                        field_reasons=reasons,
                    ))
                    continue
                raise ValueError(
                    f"票拟 option 层 A shape 失败（整批失败，F2.2/F2.5）：{title!r} {exc}"
                ) from exc
            except ValueError as exc:
                raise ValueError(
                    f"票拟 option 层 A shape 失败（整批失败，F2.2/F2.5）：{title!r} {exc}"
                ) from exc
            # 自由文本 UTF-8 可编码性（label/hint 原文）
            _assert_utf8(str(normalized_opt.get("label") or ""), "label")
            _assert_utf8(str(normalized_opt.get("hint") or ""), "hint")
            options.append(normalized_opt)
        if item_missing:
            # 本条有缺字段 option：收齐后统一 batch；不把本条 partial 当成功 draft
            missing_failures.extend(item_missing)
            continue
        # options_json 序列化前再校验 ensure_ascii=False 场景的可编码性
        try:
            json.dumps(options, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError as exc:  # noqa: BLE001
            raise ValueError(
                f"票拟字段含 SQLite 不可编码字符（整批 shape 错，F2.5）：options {exc}"
            )
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
    if missing_failures:
        raise RescriptOptionMissingFieldsBatch(missing_failures)
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


def _assert_raw_option_targets_grounded(
    raw_option: object,
    *,
    region_target_ids: set[str],
    army_target_ids: set[str],
) -> None:
    """缺字段 quarantine 前仍咬 target 接地（其它 F2.5 不得被 isolate 掩盖）。"""
    if not isinstance(raw_option, dict):
        return
    kind = str(raw_option.get("target_kind") or "").strip()
    tid = str(raw_option.get("target_id") or "").strip()
    if not tid:
        return
    if kind == "region" and tid not in region_target_ids:
        raise ValueError(
            f"票拟 option.target_id 不在同批 region_targets：{tid!r}"
        )
    if kind == "army" and tid not in army_target_ids:
        raise ValueError(
            f"票拟 option.target_id 不在同批 army_targets：{tid!r}"
        )


def _board_issue_ids(active_issues: object) -> set[int]:
    ids: set[int] = set()
    if isinstance(active_issues, list):
        for item in active_issues:
            if isinstance(item, dict) and isinstance(item.get("issue_id"), int) \
                    and not isinstance(item.get("issue_id"), bool):
                ids.add(int(item["issue_id"]))
    return ids


def _write_degraded_note(
    turn: int,
    reason: str,
    *,
    extra: Optional[Dict[str, object]] = None,
) -> None:
    """响亮降级/剔除的 error pack 附记：诊断目录留 JSON 注记（不写整包热备——结算未中止）。"""
    try:
        root = error_packs_root() / "rescript_draft_degraded"
        root.mkdir(parents=True, exist_ok=True)
        note: Dict[str, object] = {
            "turn": int(turn),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            note.update(extra)
        (root / f"turn{int(turn)}.json").write_text(
            json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 — 附记是诊断旁路，任何异常不得拖垮结算
        tlog(f"[rescript] 降级附记写盘失败：{exc}")


def _option_heal_id(item_index: int, option_index: int) -> str:
    return f"{int(item_index)}:{int(option_index)}"


def _missing_field_heal_feedback(
    failures: Sequence[RescriptOptionMissingFailure],
    *,
    attempt: int,
    max_attempts: int,
) -> str:
    """#1746 契约失败补交请求：同一会话续接，带失败字段+结构化原因 + 显式身份。

    缺字段与错值走同一回路（heal-covers-illegal-values-too）。
    原始首抽/历次补交由 prior_messages 入上下文，此处不再拼 original_raw。
    与 combination_correction_feedback（整批结构重抽）是两种动作，不得混用。
    """
    lines = [
        f"【字段补交 {attempt}/{max_attempts}】同一会话续接：下列 option 未通过契约校验。",
        "请只修正列出的失败字段（缺或错值）。可返回：",
        '1) {"heals":[{"heal_id":"i:o", "<失败字段>":...},...]}',
        '2) {"heals":[{"heal_id":"i:o", "option":{...完整 option...}},...]}',
        '3) 完整 {"items":[...]}，且每个补交 option 必须回指同一 heal_id。',
        "不要改写未列出的 option；已给出且未失败的 amount/account/target 等保持原值。",
        "代码不猜字段默认值——须由你补正。",
    ]
    for failure in failures:
        heal_id = failure.heal_id or _option_heal_id(
            failure.item_index, failure.option_index,
        )
        fields = ",".join(failure.missing_fields)
        lines.append(
            f"- heal_id={heal_id} item_index={failure.item_index} "
            f"option_index={failure.option_index} 缺字段: {fields}"
        )
        reason_map = dict(failure.field_reasons or ())
        if reason_map:
            # 结构化原因：字段→原因；供 LLM 与日志，不作机器分支
            lines.append(
                "  失败原因: "
                + json.dumps(reason_map, ensure_ascii=False)
            )
        if isinstance(failure.raw_option, dict):
            snapshot = dict(failure.raw_option)
            snapshot["heal_id"] = heal_id
            lines.append(
                "  原始 option: "
                + json.dumps(snapshot, ensure_ascii=False)
            )
    lines.append("请输出 JSON（heals 或带 heal_id 的 items）。")
    return "\n".join(lines)


def _candidate_heal_id(blob: Mapping[str, Any]) -> str:
    raw = blob.get("heal_id")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    if "item_index" in blob and "option_index" in blob:
        try:
            return _option_heal_id(int(blob["item_index"]), int(blob["option_index"]))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return ""
    return ""


def _iter_healed_option_candidates(healed: Dict[str, Any]) -> List[Tuple[str, dict]]:
    """从补交 JSON 收集 (heal_id, option_dict)；只认显式结构身份，不猜 title/label/位次。"""
    found: List[Tuple[str, dict]] = []

    def _push(heal_id: str, option: object) -> None:
        if not heal_id or not isinstance(option, dict):
            return
        # 机面身份键不落入 option 正文
        cleaned = {
            k: v for k, v in option.items()
            if k not in {"heal_id", "item_index", "option_index"}
        }
        found.append((heal_id, cleaned))

    heals = healed.get("heals")
    if isinstance(heals, list):
        for entry in heals:
            if not isinstance(entry, dict):
                continue
            heal_id = _candidate_heal_id(entry)
            if isinstance(entry.get("option"), dict):
                _push(heal_id, entry["option"])
            else:
                # 扁平：缺字段或完整 option 键与 heal_id 同级
                body = {
                    k: v for k, v in entry.items()
                    if k not in {"heal_id", "item_index", "option_index", "option"}
                }
                _push(heal_id, body)

    items = healed.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            opts = item.get("options")
            if not isinstance(opts, list):
                continue
            for cand in opts:
                if not isinstance(cand, dict):
                    continue
                _push(_candidate_heal_id(cand), cand)

    # 顶层单 option 形态
    top_id = _candidate_heal_id(healed)
    if top_id and any(
        k not in {"heals", "items", "heal_id", "item_index", "option_index"}
        for k in healed
    ):
        body = {
            k: v for k, v in healed.items()
            if k not in {"heals", "items", "heal_id", "item_index", "option_index"}
        }
        if body:
            _push(top_id, body)
    return found


def _find_healed_option_for_failure(
    healed: Dict[str, Any],
    failure: RescriptOptionMissingFailure,
) -> Optional[dict]:
    """按补交请求显式 heal_id 回指定位；0/多命中均拒绝（不按位次/措辞猜配）。"""
    want = (failure.heal_id or _option_heal_id(
        failure.item_index, failure.option_index,
    )).strip()
    if not want:
        return None
    hits = [
        option for heal_id, option in _iter_healed_option_candidates(healed)
        if heal_id == want
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def _apply_missing_fields_only(
    baseline_opt: dict,
    replacement: dict,
    missing_fields: Sequence[str],
) -> Optional[dict]:
    """只把失败字段从补交结果写入底稿 option；其它键一律冻结。

    失败字段含缺与错值（heal-covers-illegal-values-too）。完整重交可接受其形态，
    但未列入失败的键（amount/account/target 等）以底稿为准。
    失败字段在 replacement 仍无有效值则拒绝（None）。
    """
    if not missing_fields:
        return None
    out = copy.deepcopy(baseline_opt)
    filled = 0
    for field in missing_fields:
        key = str(field)
        if key not in replacement:
            continue
        val = replacement[key]
        # None = 未补；空串若键显式给出则写回（present_keys 可空合法）
        # 仍空/仍错由下一轮权威校验再进补交，不在此猜默认。
        if val is None:
            continue
        out[key] = copy.deepcopy(val)
        filled += 1
    if filled == 0:
        return None
    # 部分进展合法（如先 purpose 后 account）：已填键保留，其余留给后续补交
    return out


def _merge_healed_missing_options(
    baseline: Dict[str, Any],
    healed: Dict[str, Any],
    failures: Sequence[RescriptOptionMissingFailure],
) -> Dict[str, Any]:
    """#1746：只回填缺字段；兄弟 option 与已有结构化键冻结为首抽。

    完整重交仅用于提供缺失键的值；禁止覆盖 amount/account/target 等已有字段。
    """
    result = copy.deepcopy(baseline)
    base_items = result.get("items")
    if not isinstance(base_items, list):
        return copy.deepcopy(healed) if isinstance(healed, dict) else {"items": []}
    for failure in failures:
        if failure.item_index >= len(base_items):
            continue
        base_item = base_items[failure.item_index]
        if not isinstance(base_item, dict):
            continue
        base_opts = base_item.get("options")
        if not isinstance(base_opts, list) or failure.option_index >= len(base_opts):
            continue
        base_opt = base_opts[failure.option_index]
        if not isinstance(base_opt, dict):
            continue
        replacement = _find_healed_option_for_failure(healed, failure)
        if replacement is None:
            continue
        patched = _apply_missing_fields_only(
            base_opt, replacement, failure.missing_fields,
        )
        if patched is None:
            continue
        base_opts[failure.option_index] = patched
    return result


def _drop_options_by_failures(
    data: Dict[str, Any],
    failures: Sequence[RescriptOptionMissingFailure],
) -> Dict[str, Any]:
    """耗尽后只剔失败 option；急务条目 options 空则整条去掉（F2.3 不足照实）。"""
    drop_map: Dict[int, set[int]] = {}
    for failure in failures:
        drop_map.setdefault(int(failure.item_index), set()).add(int(failure.option_index))
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return {"items": []}
    kept_items: List[object] = []
    for item_index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            kept_items.append(item)
            continue
        drop_idxs = drop_map.get(item_index) or set()
        if not drop_idxs:
            kept_items.append(item)
            continue
        raw_opts = item.get("options")
        if not isinstance(raw_opts, list):
            continue
        kept_opts = [
            opt for option_index, opt in enumerate(raw_opts)
            if option_index not in drop_idxs
        ]
        if not kept_opts:
            # 该急务 options 全剔 → 条目消失，其它急务不受牵连
            continue
        new_item = dict(item)
        new_item["options"] = kept_opts
        kept_items.append(new_item)
    return {"items": kept_items}


def _failure_log_rows(
    failures: Sequence[RescriptOptionMissingFailure],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for failure in failures:
        heal_id = failure.heal_id or _option_heal_id(
            failure.item_index, failure.option_index,
        )
        row: Dict[str, object] = {
            "heal_id": heal_id,
            "title": failure.title,
            "item_index": failure.item_index,
            "option_index": failure.option_index,
            "missing_fields": list(failure.missing_fields),
        }
        if failure.field_reasons:
            row["field_reasons"] = dict(failure.field_reasons)
        if isinstance(failure.raw_option, dict):
            label = failure.raw_option.get("label")
            if label is not None:
                row["label"] = label
        rows.append(row)
    return rows


def generate_rescript_draft(
    agent: Any,
    payload: Dict[str, object],
    turn: int,
) -> Optional[List[Dict[str, object]]]:
    """phase2 fan-out 第 N+1 路（N=同池 extractor 模块数）：票拟生成 LLM 调用并校验 shape。

    响亮降级契约（F2.5）按错误归属拆缝（r2 裁决 B3 / ADR 0005 / relation_brew 同款
    先例）：业务降级面只收声明类型——LLM 调用缝只收 typed LLMUnavailable；解析/shape
    校验缝只收 LLMContractError/ValueError。命中即 tlog 留痕＋诊断目录附记，返回 None，
    本月视作无头版。程序错（RuntimeError/KeyError/TypeError 等）**响亮上抛**——票拟
    业务降级 ≠ 代码故障降级，不再以「非承重支路」为由吞程序错误。

    #1624：首抽若触发 typed StructuredDecreeCombinationError，复用共同
    combination_correction_feedback 有界结构重抽并重验整批；耗尽后仍 F2.5 整批降级，
    零部分头版。禁止静默改写 army+single→none / army→region 或另造月末矩阵。

    #1746：可定位到单 option 的缺结构化字段 → 同一会话补交（附原始产出、索缺字段，
    最多 RESCRIPT_OPTION_FIELD_HEAL_RETRIES 次，与组合重抽是两种动作）；耗尽只剔除该
    option，其余急务/option 照出，不告知皇帝；后台 tlog + error pack 响亮留痕。
    剔后剩 1 个 option 仍可呈（F2.2 局部修订）；剩 0 则该急务条目不足照实消失。
    """
    # payload 序列化是纯程序逻辑：其错误属代码侧错（ADR 0005），不在降级面内，响亮上抛。
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    tlog(f"[rescript] user payload total={len(payload_json)} chars (~{len(payload_json)//1.5:.0f} tok)")

    def _degrade(exc: Exception) -> None:
        tlog(f"[rescript] 票拟生成失败，本月视作无头版：{exc}")
        _write_degraded_note(turn, str(exc))

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
    board_ids = _board_issue_ids(payload.get("active_issues"))

    def _ground(drafts: List[Dict[str, object]]) -> List[Dict[str, object]]:
        _assert_region_targets_grounded(drafts, region_target_ids)
        _assert_army_targets_grounded(drafts, army_target_ids)
        return drafts

    def _parse_and_validate(
        raw: str,
        *,
        isolate_option_missing: bool,
        min_options: int = 2,
        max_options: int = 3,
    ) -> List[Dict[str, object]]:
        data = _parse_rescript_json_strict(raw)
        drafts = validate_rescript_draft_items(
            data,
            board_ids,
            min_options=min_options,
            max_options=max_options,
            isolate_option_missing=isolate_option_missing,
        )
        return _ground(drafts)

    combo_correction = ""
    combo_retries = max(0, int(RESCRIPT_COMBO_CORRECTION_RETRIES))
    combo_attempt = 0
    heal_retries = max(0, int(RESCRIPT_OPTION_FIELD_HEAL_RETRIES))
    heal_attempt = 0
    pending_missing: Optional[List[RescriptOptionMissingFailure]] = None
    # 单一底稿：首抽/组合重抽/补交合并共用；消除 original_raw 与 working_data 双轨。
    working_data: Optional[Dict[str, Any]] = None
    heal_trace: List[Dict[str, object]] = []
    # 本票拟链局部会话：真实 user/assistant 轮次入 prior_messages（不持久化、不启其它角色）。
    session_messages: List[Any] = []
    # 有界循环骨架与组合重抽共用；补交/重抽分支分叉，不另造第三套 heal 机器。
    while True:
        if pending_missing is not None and heal_attempt >= 1:
            prompt = _missing_field_heal_feedback(
                pending_missing,
                attempt=heal_attempt,
                max_attempts=heal_retries,
            )
            tag = "rescript-draft-heal"
        elif combo_correction:
            prompt = f"{combo_correction}\n{payload_json}"
            tag = "rescript-draft"
        else:
            prompt = payload_json
            tag = "rescript-draft"
        try:
            raw = run_agent_text(
                agent,
                prompt,
                tag=tag,
                prior_messages=session_messages or None,
            )
        except (APITimeoutError, APIConnectionError, APIStatusError) as error:
            # 窄捕 provider 已知故障→译 typed（照抄 decree.py:1991 Z3 缝）
            _degrade(llm_unavailable_from_error(error, "急务票拟生成"))
            return None
        except LLMUnavailable as exc:  # LLM 调用缝：只收 typed 声明，程序错上抛
            _degrade(exc)
            return None
        # 续接本链会话：保留原始输入/输出与历次补交（机面 Message，不落库）
        session_messages.append({"role": "user", "content": prompt})
        session_messages.append({"role": "assistant", "content": raw})
        if tag == "rescript-draft-heal":
            entry = {
                "attempt": heal_attempt,
                "raw_summary": raw[:800],
                "failures": _failure_log_rows(pending_missing or ()),
            }
            heal_trace.append(entry)
            # 票面：tlog 记 option 身份 + 缺字段 + 各次补交产出摘要
            tlog(
                f"[rescript] option 缺字段补交产出 {heal_attempt}/{heal_retries} "
                f"raw_summary={json.dumps(entry['raw_summary'], ensure_ascii=False)} "
                f"failures={json.dumps(entry['failures'], ensure_ascii=False)}"
            )
        try:
            if tag == "rescript-draft-heal" and working_data is not None and pending_missing:
                # 只把缺字段 option 的补交结果合并进当前底稿；兄弟项不改写
                healed_data = _parse_rescript_json_strict(raw)
                if not isinstance(healed_data, dict):
                    raise ValueError(
                        '票拟补交产出顶层非法：须为 {"heals":[...]} 或 {"items":[...]}'
                    )
                merged = _merge_healed_missing_options(
                    working_data, healed_data, pending_missing,
                )
                working_data = merged
                drafts = validate_rescript_draft_items(
                    merged,
                    board_ids,
                    isolate_option_missing=True,
                )
                drafts = _ground(drafts)
            else:
                # 首抽与组合重抽都刷新单一底稿——补交合并必须以最新有效整批为基
                data = _parse_rescript_json_strict(raw)
                if isinstance(data, dict):
                    working_data = copy.deepcopy(data)
                drafts = _parse_and_validate(raw, isolate_option_missing=True)
        except StructuredDecreeCombinationError as exc:
            # typed 组合：有界重抽；耗尽才 F2.5（StructuredDecree 是 ValueError 子类，
            # 必须先于下方宽捕，否则会跳过纠错）。与缺字段补交分流。
            if combo_attempt >= combo_retries:
                _degrade(exc)
                return None
            combo_attempt += 1
            combo_correction = combination_correction_feedback(exc)
            pending_missing = None
            tlog(f"[rescript] 结构组合纠错重试 {combo_attempt}/{combo_retries}: {exc}")
            continue
        except RescriptOptionMissingFieldsBatch as exc:
            # 混合失败：缺字段 option 若同时 target 未接地 → 整批 F2.5，不进补交 quarantine
            try:
                for failure in exc.failures:
                    _assert_raw_option_targets_grounded(
                        failure.raw_option,
                        region_target_ids=region_target_ids,
                        army_target_ids=army_target_ids,
                    )
            except ValueError as mixed_exc:
                _degrade(mixed_exc)
                return None
            pending_missing = list(exc.failures)
            rows = _failure_log_rows(pending_missing)
            if heal_attempt < heal_retries:
                heal_attempt += 1
                tlog(
                    f"[rescript] option 缺字段补交 {heal_attempt}/{heal_retries}："
                    f"{json.dumps(rows, ensure_ascii=False)}"
                )
                continue
            # 耗尽：只剔失败 option，其余照出；不告知皇帝；后台响亮留痕
            tlog(
                f"[rescript] option 缺字段补交耗尽，剔除："
                f"{json.dumps(rows, ensure_ascii=False)} "
                f"heal_trace={json.dumps(heal_trace, ensure_ascii=False)}"
            )
            drop_rows = [
                {**row, "heal_attempts": heal_retries}
                for row in rows
            ]
            _write_degraded_note(
                turn,
                "option_missing_fields_heal_exhausted",
                extra={
                    "dropped_options": drop_rows,
                    "heal_trace": heal_trace,
                },
            )
            # 剔除底稿用 working_data（已累积中间补交成功项）
            data = working_data if isinstance(working_data, dict) else None
            if data is None:
                try:
                    parsed = _parse_rescript_json_strict(raw)
                except (LLMContractError, ValueError) as parse_exc:
                    _degrade(parse_exc)
                    return None
                if not isinstance(parsed, dict):
                    _degrade(exc)
                    return None
                data = parsed
            dropped = _drop_options_by_failures(data, pending_missing)
            try:
                # F2.2 局部修订：剔后剩 1 仍呈；0 option 条目已在 drop 时去掉
                drafts = validate_rescript_draft_items(
                    dropped,
                    board_ids,
                    min_options=1,
                    max_options=3,
                    isolate_option_missing=False,
                )
                drafts = _ground(drafts)
            except (LLMContractError, ValueError) as drop_exc:
                _degrade(drop_exc)
                return None
            tlog(
                f"[rescript] 票拟生成 {len(drafts)} 条"
                f"（缺字段剔除 {len(pending_missing)} option 后）。"
            )
            return drafts
        except (LLMContractError, ValueError) as exc:  # 解析/非组合/非缺字段 shape：整批降级
            _degrade(exc)
            return None
        tlog(f"[rescript] 票拟生成 {len(drafts)} 条。")
        return drafts
