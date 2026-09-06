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
    DOSSIER_ACTION_TYPES,
    TARGET_KINDS,
    _DRAFT_CAPABILITY_KEYS,
    derive_draft_capability,
)
from ming_sim.error_pack import error_packs_root
from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.models import GameState, reign_period_label
from ming_sim.structured_decree import StructuredDecreeCombinationError
from ming_sim.token_stats import tlog

MAX_RESCRIPT_DRAFTS = 5
# #1746：单 option 契约失败（缺/错/组合/接地/形）→ 同一会话补交（不含首抽）；耗尽只剔该 option。
# decision: missing-field-heal-by-resume-not-drop / per-option-drop-after-heal-exhausted
# decision: heal-covers-illegal-values-too（不问错在哪；不按错误种类分闸）
RESCRIPT_OPTION_FIELD_HEAL_RETRIES = 3
# 整 option 替换语义标记（非 object 等）；出现在 missing_fields 时合并器接受完整 option 体。
_OPTION_REPLACE_FIELD = "option"


def _field_failure(
    field: str,
    *,
    current: object = None,
    expected: object = None,
) -> Dict[str, object]:
    """权威失败事实一条；current/expected 保持源值，转义只在 JSON 运输边界。"""
    return {
        "field": str(field),
        "current": current,
        "expected": expected,
    }


def _merge_field_failure(
    facts: Dict[str, Dict[str, object]],
    field: str,
    *,
    current: object = None,
    expected: object = None,
) -> None:
    key = str(field)
    if not key or key in facts:
        return
    facts[key] = _field_failure(key, current=current, expected=expected)


def _note_failed(
    facts: Dict[str, Dict[str, object]],
    *fields: str,
    current: object = None,
    expected: object = None,
    currents: Optional[Mapping[str, object]] = None,
    expecteds: Optional[Mapping[str, object]] = None,
) -> None:
    """唯一事实集合：字段/现值/期望；failed 名由此派生。"""
    for field in fields:
        key = str(field)
        if not key:
            continue
        cur = current
        exp = expected
        if currents is not None and key in currents:
            cur = currents[key]
        if expecteds is not None and key in expecteds:
            exp = expecteds[key]
        _merge_field_failure(facts, key, current=cur, expected=exp)


class RescriptOptionMissingFieldsError(ValueError):
    """可定位到单 option 的契约失败（#1746 补交分支）。

    缺字段、错值、组合矛盾、未知键、非 object 等凡可定位到 option 的失败
    均走同一补交回路（heal-covers-illegal-values-too）；非顶层/急务条目非法。
    权威失败事实只有 field_failures（field/current/expected）；missing_fields 由其派生。
    """

    def __init__(
        self,
        message: str,
        *,
        raw_option: object = None,
        field_failures: Optional[Sequence[Mapping[str, object]]] = None,
    ) -> None:
        self.raw_option = raw_option
        # 权威接缝已给出事实；此处只承载，不过滤/去重/补空
        self.field_failures: Tuple[Dict[str, object], ...] = tuple(
            dict(f) for f in (field_failures or ())
        )
        self.missing_fields = tuple(str(f["field"]) for f in self.field_failures)
        super().__init__(message)


def _raise_option_missing_fields(
    message: str,
    *,
    raw_option: object = None,
    field_failures: Optional[Sequence[Mapping[str, object]]] = None,
) -> None:
    """抛可定位单 option 契约失败（#1746 heal-by-resume）。不问错误种类。"""
    raise RescriptOptionMissingFieldsError(
        message,
        raw_option=raw_option,
        field_failures=field_failures,
    )


@dataclass(frozen=True)
class RescriptOptionMissingFailure:
    item_index: int
    option_index: int
    title: str
    missing_fields: Tuple[str, ...]  # 由 field_failures 派生
    raw_option: object
    # 机面结构身份：补交请求显式携带、响应回指；不依赖 title/label 自由文。
    heal_id: str = ""
    field_failures: Tuple[Dict[str, object], ...] = ()


class RescriptOptionMissingFieldsBatch(ValueError):
    """一批 option 契约失败（validate isolate 模式一次收齐，供补交/剔除）。"""

    def __init__(self, failures: Sequence[RescriptOptionMissingFailure]) -> None:
        self.failures = list(failures)
        parts = [
            f"{f.title!r}#{f.option_index}:{','.join(f.missing_fields)}"
            for f in self.failures
        ]
        super().__init__("票拟 option 契约失败：" + "; ".join(parts))

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

# 逐类 action-conditional 必填/互斥/枚举/条件必填（纯 shape，无 DB grounding）。
# #1778：本表只对列出的类型加形状检查，不是准入闭集——未列出的库级类型照常受理。
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
assert frozenset(_LAYER_A_ACTION_CONDITIONAL) <= DOSSIER_ACTION_TYPES

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
    """逐类条件契约的 typed 视图（shape/normalize/renderer 共用）。"""
    out: Dict[str, Dict[str, object]] = {}
    for action in sorted(_LAYER_A_ACTION_CONDITIONAL):
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
    action_conditional 承载逐类必填/互斥/枚举/条件必填，禁止入口平行手抄。
    #1778：action_types＝库级全集（ADR 0040 形状检查），不是七类准入闭集。
    """
    return {
        "required_keys": _LAYER_A_REQUIRED_KEYS,
        "present_keys": _LAYER_A_PRESENT_KEYS,
        "action_types": tuple(sorted(DOSSIER_ACTION_TYPES)),
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
    facts_out: Dict[str, Dict[str, object]],
) -> None:
    """按 shape.action_conditional 强制逐类必填/互斥/枚举（写回 out）。

    字段契约失败（缺或错）写入唯一事实集合；不填占位值。
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

    def _fail(
        *fields: str,
        current: object = None,
        expected: object = None,
        currents: Optional[Mapping[str, object]] = None,
        expecteds: Optional[Mapping[str, object]] = None,
    ) -> None:
        _note_failed(
            facts_out, *fields,
            current=current, expected=expected,
            currents=currents, expecteds=expecteds,
        )

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
            except (TypeError, ValueError, OverflowError):
                _fail(
                    key,
                    current=val,
                    expected={"type": "positive_int"},
                )
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
                current=got,
                expected=sorted(allowed_tk),
            )

    for key in rules.get("required_nonempty") or ():
        key_s = str(key)
        val = _nonempty_str(key_s)
        if not val:
            _fail(
                key_s,
                current=_raw_or_out(key_s),
                expected={"nonempty_str": True},
            )
            continue
        src = _raw_or_out(key_s)
        out[key_s] = str(src) if src is not None else val

    for group in rules.get("require_any_nonempty") or ():
        keys = tuple(str(k) for k in group)  # type: ignore[union-attr]
        # 组内已有键被记为非法时不再重复索整组
        if any(k in facts_out for k in keys):
            continue
        if not any(_require_any_present(k) for k in keys):
            _fail(
                *keys,
                currents={k: _raw_or_out(k) for k in keys},
                expecteds={k: {"any_of_group": list(keys)} for k in keys},
            )
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
                _fail(
                    key_s,
                    current=val,
                    expected=sorted(allowed_set),
                )
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
                _fail(
                    rk_s,
                    current=_raw_or_out(rk_s),
                    expected={"required_when": {ctrl: cval}},
                )
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
                currents={k: _raw_or_out(k) for k in present},
                expecteds={k: {"mutex": list(keys), "keep_one": True} for k in present},
            )

    pos_when = rules.get("positive_amount_when")
    if pos_when and len(pos_when) >= 2:  # type: ignore[arg-type]
        ctrl, cval = str(pos_when[0]), str(pos_when[1])  # type: ignore[index]
        if _nonempty_str(ctrl) == cval:
            amt_raw = _raw_or_out("amount")
            if amt_raw is None or amt_raw == "":
                _fail(
                    "amount",
                    current=amt_raw,
                    expected={"type": "positive_int"},
                )
            else:
                try:
                    if isinstance(amt_raw, bool):
                        raise ValueError("bool")
                    amount = int(amt_raw)  # type: ignore[arg-type]
                except (TypeError, ValueError, OverflowError):
                    _fail(
                        "amount",
                        current=amt_raw,
                        expected={"type": "positive_int"},
                    )
                else:
                    if amount <= 0:
                        _fail(
                            "amount",
                            current=amount,
                            expected={"type": "positive_int"},
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
            except (TypeError, ValueError, OverflowError):
                amount = 0
            if isinstance(amt_raw, bool):
                amount = 0
            if amount > 0:
                _fail(
                    "amount",
                    current=amt_raw,
                    expected={"forbid_positive_unless": {ctrl: cval}},
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

    #1746（heal-covers-illegal-values-too）：权威 shape/normalize/组合一次收齐
    失败字段（不问错在哪）→ RescriptOptionMissingFieldsError 同一补交回路。
    禁止填占位合法值；不按错误种类分流。
    """
    if not isinstance(raw, dict):
        _raise_option_missing_fields(
            "票拟 option 非 object（层 A shape）",
            raw_option=raw,
            field_failures=[
                _field_failure(
                    _OPTION_REPLACE_FIELD,
                    current=type(raw).__name__,
                    expected="object",
                )
            ],
        )
    shape = layer_a_option_shape()
    required_keys = shape["required_keys"]  # type: ignore[assignment]
    present_keys = shape["present_keys"]  # type: ignore[assignment]
    action_types = frozenset(shape["action_types"])  # type: ignore[arg-type]
    grant_kind_army_pay = str(shape["grant_kind_army_pay"])
    capability_str_keys = shape["capability_str_keys"]  # type: ignore[assignment]
    capability_int_keys = shape["capability_int_keys"]  # type: ignore[assignment]
    out: Dict[str, object] = {}
    facts: Dict[str, Dict[str, object]] = {}

    def _fail(
        *fields: str,
        current: object = None,
        expected: object = None,
        currents: Optional[Mapping[str, object]] = None,
        expecteds: Optional[Mapping[str, object]] = None,
    ) -> None:
        _note_failed(
            facts, *fields,
            current=current, expected=expected,
            currents=currents, expecteds=expecteds,
        )

    unknown = sorted(set(raw) - _LAYER_A_ALLOWED_KEYS)
    if unknown:
        # 未知键：单 option 补交（完整替换或去掉未知键）；不整批降级
        for key in unknown:
            _fail(
                key,
                current=raw.get(key),
                expected={"allowed_keys": sorted(_LAYER_A_ALLOWED_KEYS)},
            )
        if _OPTION_REPLACE_FIELD not in facts:
            _fail(
                _OPTION_REPLACE_FIELD,
                current=unknown,
                expected={"allowed_keys": sorted(_LAYER_A_ALLOWED_KEYS)},
            )

    for key in required_keys:  # type: ignore[union-attr]
        key_s = str(key)
        if key_s not in raw or raw.get(key_s) is None:
            _fail(
                key_s,
                current=None if key_s not in raw else raw.get(key_s),
                expected={"type": "nonempty_str"},
            )
            continue
        val = raw.get(key_s)
        if not isinstance(val, str):
            _fail(
                key_s,
                current=val,
                expected={"type": "nonempty_str"},
            )
            continue
        if not val.strip():
            _fail(
                key_s,
                current=val,
                expected={"type": "nonempty_str"},
            )
            continue
        out[key_s] = val  # 原文；strip 仅判空

    action_type = ""
    if "action_type" in out:
        action_type = str(out["action_type"]).strip()
        if action_type not in action_types:
            _fail(
                "action_type",
                current=action_type,
                expected=sorted(action_types),
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
                        current=raw_kind,
                        expected={"allowed_when_action": "grant_allocation"},
                    )

    if "target_kind" in out:
        target_kind = str(out["target_kind"]).strip()
        if target_kind not in TARGET_KINDS:
            _fail(
                "target_kind",
                current=target_kind,
                expected=sorted(TARGET_KINDS),
            )
        else:
            out["target_kind"] = target_kind

    if "locality_scope" in out:
        # #1624：locality 归一唯一真源；禁止平行别名表，禁止按 target_kind 覆盖
        from ming_sim.execution_pressure import (
            LOCALITY_SCOPES,
            normalize_locality_scope,
        )
        try:
            out["locality_scope"] = normalize_locality_scope(out["locality_scope"])
        except (TypeError, ValueError):
            _fail(
                "locality_scope",
                current=out.get("locality_scope"),
                expected=sorted(LOCALITY_SCOPES),
            )

    # C.3：三键必须在且为 str（可 ""）；禁缺键补全 / None→"" / truthiness 洗值
    for key in present_keys:  # type: ignore[union-attr]
        key_s = str(key)
        if key_s not in raw:
            _fail(
                key_s,
                current=None,
                expected={"type": "str", "allow_empty": True},
            )
            continue
        value = raw[key_s]
        if not isinstance(value, str):
            _fail(
                key_s,
                current=value,
                expected={"type": "str", "allow_empty": True},
            )
            continue
        out[key_s] = value

    # 逐类 action-conditional（与 shape/renderer 同真源；先于组合闸）
    if action_type:
        _enforce_layer_a_action_conditional(
            out, raw, shape=shape, facts_out=facts,
        )

    # #1624/#1746：完整组合判定只走权威接缝一次；消费端只携带事实。
    if (
        action_type
        and "target_kind" in out
        and str(out.get("target_kind") or "").strip()
        and "locality_scope" in out
        and str(out.get("locality_scope") or "").strip()
        and "target_kind" not in facts
        and "locality_scope" not in facts
    ):
        from ming_sim.structured_decree import (
            validate_structured_decree_combination,
        )
        try:
            validate_structured_decree_combination(out)
        except StructuredDecreeCombinationError as exc:
            for raw_fact in exc.field_failures:
                _note_failed(
                    facts, str(raw_fact["field"]),
                    current=raw_fact.get("current"),
                    expected=raw_fact.get("expected"),
                )

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
        except ValueError:
            _fail(
                "stop_condition",
                current=raw.get("stop_condition"),
                expected={"type": "str"},
            )
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
            except (TypeError, ValueError, OverflowError):
                # JSON 1e309/-1e309 → ±inf；int(inf) 抛 OverflowError，与错类型同入补交
                _fail(
                    key,
                    current=raw[key],
                    expected={"type": "int"},
                )

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
                currents={"grant_kind": None, "grant_action": None},
                expecteds={
                    "grant_kind": grant_kind_army_pay,
                    "grant_action": {"nonempty_grant_action": True},
                },
            )
        elif grant_kind:
            if grant_kind != grant_kind_army_pay:
                _fail(
                    "grant_kind",
                    current=grant_kind,
                    expected=grant_kind_army_pay,
                )
            elif raw_ga:
                _fail(
                    "grant_kind", "grant_action",
                    currents={"grant_kind": grant_kind, "grant_action": raw_ga},
                    expecteds={
                        "grant_kind": grant_kind_army_pay,
                        "grant_action": {
                            "mutex_with": "grant_kind",
                            "must_be_empty": True,
                        },
                    },
                )
            else:
                out["grant_action"] = "协饷"
        elif generation_admission and raw_ga == "协饷":
            _fail(
                "grant_kind",
                current=None,
                expected=grant_kind_army_pay,
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
                field = str(getattr(exc, "field", "") or "").strip()
                if not field:
                    raise
                current = getattr(exc, "current", None)
                if current is None:
                    current = (
                        raw.get(field) if field in raw else out.get(field)
                    )
                expected = getattr(exc, "expected", None)
                if expected is None and not hasattr(exc, "expected"):
                    raise
                _fail(field, current=current, expected=expected)
            else:
                out["grant_action"] = shaped["grant_action"]
                if "amount" in shaped:
                    out["amount"] = shaped["amount"]
                if input_account_present:
                    out["account"] = shaped["account"]
                if str(out.get("grant_action") or "").strip() == "协饷":
                    # 吃 grant shape 已归一的 amount，恢复既有语义（"300"→300）
                    purpose_cur = str(
                        out.get("purpose")
                        if "purpose" in out
                        else (raw.get("purpose") if "purpose" in raw else "")
                        or ""
                    )
                    cadence_cur = str(
                        out.get("cadence")
                        if "cadence" in out
                        else (raw.get("cadence") if "cadence" in raw else "")
                        or ""
                    )
                    try:
                        explicit = require_explicit_xiexang_fields(
                            amount=out.get("amount", 0),
                            account=str(out.get("account") or ""),
                            purpose=purpose_cur,
                            target_kind=str(
                                out.get("target_kind") or raw.get("target_kind") or ""
                            ),
                            target_id=str(
                                out.get("target_id") or raw.get("target_id") or ""
                            ),
                            cadence=cadence_cur,
                        )
                    except IncompleteXiexangPayloadError as exc:
                        for raw_fact in exc.field_failures:
                            _note_failed(
                                facts, str(raw_fact["field"]),
                                current=raw_fact.get("current"),
                                expected=raw_fact.get("expected"),
                            )
                    else:
                        out["amount"] = explicit["amount"]
                        out["account"] = explicit["account"]
                        out["purpose"] = explicit["purpose"]
                        out["target_kind"] = explicit["target_kind"]
                        out["target_id"] = explicit["target_id"]

    # 首次消耗前：可归属 option 的编码失败并入同一补交事实集（不擦洗、不改哈希契约）
    _note_option_utf8_failures(raw, out, facts=facts)

    if facts:
        _raise_option_missing_fields(
            f"票拟 option 契约失败字段：{'/'.join(facts)}",
            raw_option=raw,
            field_failures=list(facts.values()),
        )

    # derive 需要 action_type 等必填已齐；编码已在上环收束，不再经 ValueError 整批
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


def _option_failure_from_exc(
    *,
    item_index: int,
    option_index: int,
    title: str,
    exc: RescriptOptionMissingFieldsError,
    raw_option: object = None,
) -> RescriptOptionMissingFailure:
    raw_for = raw_option if raw_option is not None else exc.raw_option
    facts = tuple(dict(f) for f in exc.field_failures)
    return RescriptOptionMissingFailure(
        item_index=item_index,
        option_index=option_index,
        title=title,
        missing_fields=tuple(exc.missing_fields),
        raw_option=raw_for,
        heal_id=_option_heal_id(item_index, option_index),
        field_failures=facts,
    )


def _target_catalog_for_kind(
    kind: str,
    *,
    region_target_ids: Optional[set[str]],
    army_target_ids: Optional[set[str]],
) -> Optional[set[str]]:
    if kind == "region":
        return region_target_ids
    if kind == "army":
        return army_target_ids
    return None


def _ungrounded_target_failure(
    raw_option: object,
    *,
    region_target_ids: Optional[set[str]],
    army_target_ids: Optional[set[str]],
) -> Optional[RescriptOptionMissingFieldsError]:
    """option 级 target 未接地 → 补交失败（非整批）。无目录时不检。"""
    if not isinstance(raw_option, dict):
        return None
    kind = str(raw_option.get("target_kind") or "").strip()
    tid = str(raw_option.get("target_id") or "").strip()
    if not tid:
        return None
    catalog = _target_catalog_for_kind(
        kind,
        region_target_ids=region_target_ids,
        army_target_ids=army_target_ids,
    )
    if catalog is None or tid in catalog:
        return None
    return RescriptOptionMissingFieldsError(
        f"票拟 option.target_id 不在同批 {kind}_targets：{tid!r}",
        raw_option=raw_option,
        field_failures=[
            _field_failure(
                "target_id",
                current=tid,
                expected=sorted(catalog),
            )
        ],
    )


def _note_option_utf8_failures(
    *sources: object,
    facts: Dict[str, Dict[str, object]],
) -> None:
    """capability/序列化字符串字段 UTF-8 不可编码 → 并入同一失败事实集。

    在 derive_draft_capability / options_json 首次消耗前调用；不擦洗字符。
    """
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        for key, val in src.items():
            key_s = str(key)
            if not key_s or key_s in facts:
                continue
            if not isinstance(val, str):
                continue
            try:
                val.encode("utf-8")
            except UnicodeEncodeError:
                _note_failed(
                    facts, key_s,
                    current=val,
                    expected={"encoding": "utf-8"},
                )


def validate_rescript_draft_items(
    data: object,
    board_issue_ids: set[int],
    *,
    min_options: int = 2,
    max_options: int = 3,
    isolate_option_missing: bool = False,
    region_target_ids: Optional[set[str]] = None,
    army_target_ids: Optional[set[str]] = None,
) -> List[Dict[str, object]]:
    """shape 校验（F2.2/F2.5）＋权威快照绑定＋原样不变式（F3.3）。

    - 顶层非法（非 dict / 无 items list）→ raise ValueError（整批降级，本月无头版）；
    - 条目必需字段缺失或非法（title/context）→ raise ValueError 整批失败；
    - options 数量：首抽/常规默认 2–3（F2.2）；#1746 剔除后 min_options=1 仍可呈；
    - 可定位单 option 的契约失败（#1746，不问错种类）：isolate_option_missing=True
      时收齐为 RescriptOptionMissingFieldsBatch（补交／耗尽单 option 剔除）；
      False 时仍整批 ValueError（旧直调行为）；
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
            try:
                normalized_opt = normalize_rescript_layer_a_option(
                    opt, generation_admission=True,
                )
            except RescriptOptionMissingFieldsError as exc:
                if isolate_option_missing:
                    item_missing.append(_option_failure_from_exc(
                        item_index=item_index,
                        option_index=option_index,
                        title=title,
                        exc=exc,
                        raw_option=opt if isinstance(opt, dict) else exc.raw_option,
                    ))
                    continue
                raise ValueError(
                    f"票拟 option 层 A shape 失败（整批失败，F2.2/F2.5）：{title!r} {exc}"
                ) from exc
            except ValueError as exc:
                # 非 option 可归属的程序/契约异常：整批降级（保留边界）
                raise ValueError(
                    f"票拟 option 层 A shape 失败（整批失败，F2.2/F2.5）：{title!r} {exc}"
                ) from exc
            # 成功归一后唯一接地检查；失败进同一补交
            ground_exc = _ungrounded_target_failure(
                normalized_opt,
                region_target_ids=region_target_ids,
                army_target_ids=army_target_ids,
            )
            if ground_exc is not None:
                if isolate_option_missing:
                    item_missing.append(_option_failure_from_exc(
                        item_index=item_index,
                        option_index=option_index,
                        title=title,
                        exc=ground_exc,
                        raw_option=opt if isinstance(opt, dict) else ground_exc.raw_option,
                    ))
                    continue
                raise ValueError(
                    f"票拟 option 接地失败（整批失败，F2.5）：{title!r} {ground_exc}"
                ) from ground_exc
            options.append(normalized_opt)
        if item_missing:
            # 本条有失败 option：收齐后统一 batch；不把本条 partial 当成功 draft
            missing_failures.extend(item_missing)
            continue
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


def _assert_army_targets_grounded(
    drafts: List[Dict[str, object]], army_target_ids: set[str]
) -> None:
    """仅 army target_id 对同批 army_targets 接地。

    成员判定唯一实现 = _ungrounded_target_failure；本入口只做改票适配。
    military_order 的 target_kind/assignee_name 形状由层 A action-conditional
    单源在 normalize 强制；此处不平行复述。session 改票入口仍调用本契约。
    """
    for draft in drafts:
        for option in draft["options"]:  # type: ignore[union-attr]
            ground_exc = _ungrounded_target_failure(
                option,
                region_target_ids=None,
                army_target_ids=army_target_ids,
            )
            if ground_exc is not None:
                raise ValueError(str(ground_exc))


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
            json.dumps(note, indent=2), encoding="utf-8"
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
    """#1746 契约失败补交请求：同一会话续接的结构化 JSON（字段/现值/期望 + 身份 + 底稿）。

    heal-covers-illegal-values-too：不问错种类。请求体是实际送给 LLM 的 user 内容，
    机器与测试只认 typed 键，不解析散文。源值经 JSON 运输边界转义，loads 后与源一致。
    """
    payload_failures: List[Dict[str, object]] = []
    for failure in failures:
        heal_id = failure.heal_id or _option_heal_id(
            failure.item_index, failure.option_index,
        )
        field_failures = [dict(fact) for fact in failure.field_failures]
        draft_option: object = None
        if isinstance(failure.raw_option, dict):
            draft_option = dict(failure.raw_option)
            draft_option["heal_id"] = heal_id
        elif failure.raw_option is not None:
            draft_option = failure.raw_option
        payload_failures.append({
            "heal_id": heal_id,
            "item_index": int(failure.item_index),
            "option_index": int(failure.option_index),
            "missing_fields": list(failure.missing_fields),
            "field_failures": field_failures,
            "draft_option": draft_option,
        })
    body: Dict[str, object] = {
        "kind": "rescript_option_field_heal",
        "attempt": int(attempt),
        "max_attempts": int(max_attempts),
        "rules": [
            "Fix listed field_failures (field/current/expected).",
            'Return partial fields: {"heals":[{"heal_id":"i:o", "<field>":...},...]} ',
            'or complete option: {"heals":[{"heal_id":"i:o", "option":{...}}]} ',
            'or items with explicit heal_id on each fixed option.',
            "Do not rewrite sibling options; code does not guess defaults.",
        ],
        "failures": payload_failures,
    }
    return json.dumps(body)


def _explicit_heal_id(blob: Mapping[str, Any]) -> str:
    """只认显式 heal_id；不按坐标/标题/标签/位次猜配。"""
    raw = blob.get("heal_id")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return ""


def _healed_options_by_id(
    healed: Dict[str, Any],
) -> Dict[str, Tuple[dict, bool]]:
    """一次解析补交响应 → heal_id 索引。

    契约三形态（显式语义，不猜形）：
    - 部分字段 heals（无 option 键）→ replace=False，合并；
    - 完整 option heals（有 option 键）→ replace=True，整份替换；
    - 带显式 heal_id 的 items → replace=True，整份替换。
    同 id 多命中记为冲突（值 None），查找时拒绝。
    """
    index: Dict[str, Optional[Tuple[dict, bool]]] = {}
    _ID_KEYS = frozenset({"heal_id", "item_index", "option_index"})

    def _push(heal_id: str, option: object, *, replace: bool) -> None:
        if not heal_id or not isinstance(option, dict):
            return
        cleaned = {k: v for k, v in option.items() if k not in _ID_KEYS}
        # 部分体清洗后为空不形成响应；完整体空壳仍入索引由 apply 拒绝
        if not cleaned and not replace:
            return
        if heal_id in index:
            index[heal_id] = None  # duplicate → refuse
            return
        index[heal_id] = (cleaned, replace)

    heals = healed.get("heals")
    if isinstance(heals, list):
        for entry in heals:
            if not isinstance(entry, dict):
                continue
            heal_id = _explicit_heal_id(entry)
            if "option" in entry:
                # 显式 option 包装 = 完整替换语义；不因缺 required 键降成合并
                opt = entry.get("option")
                if isinstance(opt, dict):
                    _push(heal_id, opt, replace=True)
                continue
            # 身份键清洗唯一在 _push；部分体直接移交 entry
            _push(heal_id, entry, replace=False)

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
                _push(_explicit_heal_id(cand), cand, replace=True)

    return {k: v for k, v in index.items() if v is not None}


def _find_healed_option_for_failure(
    by_id: Mapping[str, Tuple[dict, bool]],
    failure: RescriptOptionMissingFailure,
) -> Optional[Tuple[dict, bool]]:
    """按补交请求显式 heal_id 回指定位；缺失或冲突均拒绝。"""
    want = (failure.heal_id or _option_heal_id(
        failure.item_index, failure.option_index,
    )).strip()
    if not want:
        return None
    return by_id.get(want)


def _apply_option_heal(
    baseline_opt: object,
    replacement: dict,
    failure: RescriptOptionMissingFailure,
    *,
    replace: bool,
) -> Optional[dict]:
    """把补交结果写入底稿 option。

    - 显式完整 option（option 包装 / items 形态）→ 整份替换，交权威完整校验；
    - 部分字段 → 合并提供的键；未知多余键若在失败集且未再给出则删除；
    - 底稿非 object：接受替换体；
    - 不按 required 键猜完整形态；不把显式完整体自动补成原稿。
    """
    # 一次 deepcopy 隔离 ownership；合并路径不再对同一值二次复制
    body = {k: copy.deepcopy(v) for k, v in replacement.items()}
    if not isinstance(baseline_opt, dict) or replace:
        return body or None

    if not body and not failure.missing_fields:
        return None
    out = copy.deepcopy(baseline_opt)
    changed = False
    for key, val in body.items():
        if val is None:
            continue
        out[key] = val
        changed = True
    for field in failure.missing_fields:
        key = str(field)
        if key == _OPTION_REPLACE_FIELD or key in body:
            continue
        # 未知/多余键：补交未再给出 → 从底稿删除
        if key in out and key not in _LAYER_A_ALLOWED_KEYS:
            del out[key]
            changed = True
    return out if changed else None


def _merge_healed_missing_options(
    baseline: Dict[str, Any],
    healed: Dict[str, Any],
    failures: Sequence[RescriptOptionMissingFailure],
) -> Dict[str, Any]:
    """#1746：回填失败 option；兄弟 option 不改写。

    显式完整 option 整份替换；部分字段合并。底稿与坐标依已成立不变式直接消费。
    缺响应/身份冲突 → 跳过该项，继续下一次补交（外部输入契约）。
    """
    result = copy.deepcopy(baseline)
    base_items = result["items"]
    by_id = _healed_options_by_id(healed)
    for failure in failures:
        base_item = base_items[failure.item_index]
        base_opts = base_item["options"]
        base_opt = base_opts[failure.option_index]
        found = _find_healed_option_for_failure(by_id, failure)
        if found is None:
            continue  # 缺响应或身份冲突：外部输入，下次补交
        replacement, replace = found
        patched = _apply_option_heal(
            base_opt, replacement, failure, replace=replace,
        )
        if patched is None:
            continue
        base_opts[failure.option_index] = patched
    return result


def _drop_options_by_failures(
    data: Dict[str, Any],
    failures: Sequence[RescriptOptionMissingFailure],
) -> Dict[str, Any]:
    """耗尽后只剔失败 option；急务条目 options 空则整条去掉（F2.3 不足照实）。

    底稿 items 依已成立不变式直接消费；程序破坏自然上抛。
    """
    drop_map: Dict[int, set[int]] = {}
    for failure in failures:
        drop_map.setdefault(int(failure.item_index), set()).add(int(failure.option_index))
    raw_items = data["items"]
    kept_items: List[object] = []
    for item_index, item in enumerate(raw_items):
        drop_idxs = drop_map.get(item_index) or set()
        if not drop_idxs:
            kept_items.append(item)
            continue
        raw_opts = item["options"]
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
            "field_failures": [dict(f) for f in failure.field_failures],
        }
        if isinstance(failure.raw_option, dict):
            label = failure.raw_option.get("label")
            if label is not None:
                row["label"] = label
        rows.append(row)
    return rows


def _with_heal_response_contract_failure(
    failures: Sequence[RescriptOptionMissingFailure],
    *,
    exc: BaseException,
    raw: str,
) -> List[RescriptOptionMissingFailure]:
    """补交响应自身不合契约时，把失败位置/现值/期望并入既有 option 失败事实。

    不另造循环：仍走同一 ≤3 补交/剔除回路；下一次请求经 field_failures 携带
    本次响应哪里不合契约，不得只重复旧缺字段。
    """
    response_fact: Dict[str, object] = {
        "field": "heal_response",
        "current": {
            "error": type(exc).__name__,
            "detail": str(exc)[:500],
            "raw_summary": (raw or "")[:500],
        },
        "expected": {
            "type": "object",
            "keys": ["heals", "items"],
        },
    }
    out: List[RescriptOptionMissingFailure] = []
    for failure in failures:
        facts = tuple([dict(f) for f in failure.field_failures] + [dict(response_fact)])
        out.append(
            RescriptOptionMissingFailure(
                item_index=failure.item_index,
                option_index=failure.option_index,
                title=failure.title,
                missing_fields=tuple(str(f["field"]) for f in facts),
                raw_option=failure.raw_option,
                heal_id=failure.heal_id,
                field_failures=facts,
            )
        )
    return out


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

    #1746：可定位到单 option 的契约失败（缺/错/组合/接地/形，不问种类）→ 同一会话
    补交（结构化失败事实 field/current/expected，最多 RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    次）；耗尽只剔除该 option，其余急务/option 照出，不告知皇帝；后台 tlog + error pack
    响亮留痕。剔后剩 1 个 option 仍可呈（F2.2 局部修订）；剩 0 则该急务条目不足照实消失。
    顶层/急务条目/provider 调用失败仍整批降级，不扩成所有异常都 heal。
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

    def _validate(
        data: object,
        *,
        isolate_option_missing: bool,
        min_options: int = 2,
        max_options: int = 3,
    ) -> List[Dict[str, object]]:
        # grounding 由 validate 内唯一完整 option 校验负责（不在此重复末端断言）
        return validate_rescript_draft_items(
            data,
            board_ids,
            min_options=min_options,
            max_options=max_options,
            isolate_option_missing=isolate_option_missing,
            region_target_ids=region_target_ids,
            army_target_ids=army_target_ids,
        )

    heal_retries = max(0, int(RESCRIPT_OPTION_FIELD_HEAL_RETRIES))
    heal_attempt = 0
    pending_missing: Optional[List[RescriptOptionMissingFailure]] = None
    # 单一底稿：首抽/补交合并共用。
    working_data: Optional[Dict[str, Any]] = None
    heal_trace: List[Dict[str, object]] = []
    # 本票拟链局部会话：真实 user/assistant 轮次入 prior_messages（不持久化、不启其它角色）。
    session_messages: List[Any] = []
    while True:
        if pending_missing is not None and heal_attempt >= 1:
            prompt = _missing_field_heal_feedback(
                pending_missing,
                attempt=heal_attempt,
                max_attempts=heal_retries,
            )
            tag = "rescript-draft-heal"
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
            tlog(
                f"[rescript] option 契约失败补交产出 {heal_attempt}/{heal_retries} "
                f"raw_summary={json.dumps(entry['raw_summary'])} "
                f"failures={json.dumps(entry['failures'])}"
            )
        try:
            if tag == "rescript-draft-heal" and working_data is not None and pending_missing:
                healed_data = _parse_rescript_json_strict(raw)
                if not isinstance(healed_data, dict):
                    raise ValueError(
                        '票拟补交产出顶层非法：须为 {"heals":[...]} 或 {"items":[...]}'
                    )
                merged = _merge_healed_missing_options(
                    working_data, healed_data, pending_missing,
                )
                working_data = merged
                drafts = _validate(merged, isolate_option_missing=True)
            else:
                data = _parse_rescript_json_strict(raw)
                if isinstance(data, dict):
                    working_data = copy.deepcopy(data)
                drafts = _validate(data, isolate_option_missing=True)
        except RescriptOptionMissingFieldsBatch as exc:
            pending_missing = list(exc.failures)
        except (LLMContractError, ValueError) as exc:
            # 已有底稿的补交响应契约失败（非法 JSON / 围栏外 prose / 非 object 等）
            # → 消耗本次补交，保留底稿与已成功兄弟，沿唯一 ≤3 回路继续。
            # 首抽顶层/急务条目失败仍整批降级（无 pending 底稿）。
            if working_data is None or pending_missing is None:
                _degrade(exc)
                return None
            pending_missing = _with_heal_response_contract_failure(
                pending_missing, exc=exc, raw=raw,
            )
        else:
            tlog(f"[rescript] 票拟生成 {len(drafts)} 条。")
            return drafts

        # 可定位 option 契约失败 / 补交响应契约失败：同一 continue-or-drop 回路
        rows = _failure_log_rows(pending_missing)
        if heal_attempt < heal_retries:
            heal_attempt += 1
            tlog(
                f"[rescript] option 契约失败补交 {heal_attempt}/{heal_retries}："
                f"{json.dumps(rows)}"
            )
            continue
        # 耗尽：只剔失败 option，其余照出；不告知皇帝；后台响亮留痕
        tlog(
            f"[rescript] option 契约失败补交耗尽，剔除："
            f"{json.dumps(rows)} "
            f"heal_trace={json.dumps(heal_trace)}"
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
        # 底稿在首抽/前轮已确立；非法则程序破坏自然上抛
        dropped = _drop_options_by_failures(working_data, pending_missing)
        try:
            # F2.2 局部修订：剔后剩 1 仍呈；0 option 条目已在 drop 时去掉
            drafts = _validate(
                dropped,
                isolate_option_missing=False,
                min_options=1,
                max_options=3,
            )
        except (LLMContractError, ValueError) as drop_exc:
            _degrade(drop_exc)
            return None
        tlog(
            f"[rescript] 票拟生成 {len(drafts)} 条"
            f"（契约失败剔除 {len(pending_missing)} option 后）。"
        )
        return drafts
