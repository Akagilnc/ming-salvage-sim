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
issue 盘面事实，不新建 issue。event_id 以喂给 LLM 的 issue 盘面投影为准，不信 LLM
回显。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ming_sim.db import GameDB
from ming_sim.decree_vocabulary import (
    DOSSIER_ACTION_TYPES,
    PARTICIPANT_ROSTER_KEY,
    TARGET_KINDS,
    _DRAFT_CAPABILITY_KEYS,
    derive_draft_capability,
)
from ming_sim.exceptions import LLMContractError
from ming_sim.participant_roster import PARTICIPANT_LEAD_TIER, PARTICIPANT_TIERS
from ming_sim.structured_decree import StructuredDecreeCombinationError

# #1746：单 option 契约失败（缺/错/组合/接地/形）→ RescriptOptionMissingFieldsError。
# decision: heal-covers-illegal-values-too（不问错在哪；不按错误种类分闸）
# 整 option 替换语义标记（非 object 等）；出现在 missing_fields 时合并器接受完整 option 体。_OPTION_REPLACE_FIELD = "option"


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
    """可定位到单 option 的契约失败。

    缺字段、错值、组合矛盾、未知键、非 object 等凡可定位到 option 的失败。
    权威失败事实只有 field_failures（field/current/expected）。
    """

    def __init__(
        self,
        message: str,
        *,
        field_failures: Optional[Sequence[Mapping[str, object]]] = None,
    ) -> None:
        # 权威接缝已给出事实；此处只承载，不过滤/去重/补空
        self.field_failures: Tuple[Dict[str, object], ...] = tuple(
            dict(f) for f in (field_failures or ())
        )
        super().__init__(message)


def _raise_option_missing_fields(
    message: str,
    *,
    field_failures: Optional[Sequence[Mapping[str, object]]] = None,
) -> None:
    """抛可定位单 option 契约失败。不问错误种类。"""
    raise RescriptOptionMissingFieldsError(
        message,
        field_failures=field_failures,
    )


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

# #1778 决定 3：参与名单是 typed 结构化列表键（不进上面两组 str 键）。
# 机械三档与条目形状唯一真源＝GameDB._normalize_participant_roster（ADR 0053）；
# 生成批次必须写、且至少一名主办（主办可多人），否则＝票没拟完 → 既有补交回路。
_LAYER_A_ROSTER_SHAPE: Dict[str, object] = {
    "type": "list",
    "min_items": 1,
    "item_keys": ("character_id", "tier", "role", "delegator_id"),
    "tiers": PARTICIPANT_TIERS,
    "require_tier": PARTICIPANT_LEAD_TIER,
}

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
    + [PARTICIPANT_ROSTER_KEY, "draft_capability", "grant_kind"]
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
    #1778：action_types＝库级全集（ADR 0040 形状检查），不是七类准入闭集；
    structured_keys 承载参与名单（ADR 0053 三档），生成批次必写。
    """
    return {
        "required_keys": _LAYER_A_REQUIRED_KEYS,
        "present_keys": _LAYER_A_PRESENT_KEYS,
        "structured_keys": {PARTICIPANT_ROSTER_KEY: dict(_LAYER_A_ROSTER_SHAPE)},
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


def rescript_layer_a_prompt_contract(
    *,
    character_targets_supplied: bool = False,
) -> str:
    """初拟/改票共用：由 layer_a_option_shape 渲染层 A 完整受理契约。

    structured_decree_prompt_contract 承目标/属地/承办子契约；本块补
    required/present/action_types/action-conditional/grant_kind。
    character_targets_supplied：本批是否注入 character_targets。有则 roster
    人物主键指向该目录；无则不下 character_targets 子句（P6：只要求它能看见的）。
    禁 agents 手抄；禁复述 grounding 规则；禁锁本函数措辞。
    """
    shape = layer_a_option_shape()
    required = "/".join(str(k) for k in shape["required_keys"])  # type: ignore[arg-type]
    present = "/".join(str(k) for k in shape["present_keys"])  # type: ignore[arg-type]
    roster_shape = shape["structured_keys"][PARTICIPANT_ROSTER_KEY]  # type: ignore[index]
    roster_tiers = "|".join(str(t) for t in roster_shape["tiers"])  # type: ignore[index]
    actions = "|".join(str(a) for a in shape["action_types"])  # type: ignore[arg-type]
    grant_kind = str(shape["grant_kind_army_pay"])
    server_only = "/".join(str(k) for k in shape["server_only_keys"])  # type: ignore[arg-type]
    conditional = _render_action_conditional_contract(shape.get("action_conditional"))
    # #1804：目录在场才钉 character_targets；改票入口不供目录，不写该子句。
    if character_targets_supplied:
        roster_person = (
            f"{{character_id: 须取自同批 character_targets.name, tier∈{roster_tiers}, "
            f"role: 职分文字（可空串）, delegator_id: 委派人本名（无则 null，"
            f"有则同取 character_targets.name）}}；"
            f"{roster_shape['require_tier']} 至少一人、也可数人合力；"  # type: ignore[index]
            "旨里点了谁就照写谁，未点名的由你按人物与局势荐入名单；"
            "官职栏只供认人，不得用官职名冒充人物名；"
        )
    else:
        roster_person = (
            f"{{character_id: 朝堂名册上的大臣本名, tier∈{roster_tiers}, "
            f"role: 职分文字（可空串）, delegator_id: 委派人本名（无则 null）}}；"
            f"{roster_shape['require_tier']} 至少一人、也可数人合力；"  # type: ignore[index]
            "旨里点了谁就照写谁，未点名的由你按人物与局势荐入名单；"
        )
    return (
        "票拟层 A option 受理契约（与 normalize_rescript_layer_a_option 共用 shape）："
        f"每项 options[] 必填非空 {required}；"
        f"action_type∈{actions}；"
        f"{present} 三键必须输出（值可空串）；"
        f"{PARTICIPANT_ROSTER_KEY} 写这道旨的参与名单，每项 "
        + roster_person
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


def _normalize_layer_a_participant_roster(value: object) -> List[Dict[str, object]]:
    """票拟参与名单归一：形状真源＝GameDB._normalize_participant_roster（ADR 0053）。

    只判条目形状与机械档；名单上的人是否在名册里由落库缝
    `_validate_participant_roster_references` 响亮把关（决定 3：只核人存在）。
    """
    if not isinstance(value, list):
        raise ValueError("participant_roster 须为 list")
    return GameDB._normalize_participant_roster(value, strict_structured=True)


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

    # #1778 决定 3：参与名单 typed 结构化键。生成批次必写且须有主办——
    # 没写＝票没拟完，与其余字段共走同一补交回路（失败事实只带 typed 期望形状）。
    roster_expected = shape["structured_keys"][PARTICIPANT_ROSTER_KEY]  # type: ignore[index]
    roster_raw = raw.get(PARTICIPANT_ROSTER_KEY)
    if roster_raw is not None:
        try:
            roster = _normalize_layer_a_participant_roster(roster_raw)
        except ValueError:
            _fail(PARTICIPANT_ROSTER_KEY, current=roster_raw, expected=roster_expected)
        else:
            has_lead = any(
                item.get("tier") == PARTICIPANT_LEAD_TIER for item in roster
            )
            if generation_admission and not has_lead:
                _fail(
                    PARTICIPANT_ROSTER_KEY,
                    current=roster_raw, expected=roster_expected,
                )
            else:
                out[PARTICIPANT_ROSTER_KEY] = roster
    elif generation_admission:
        _fail(PARTICIPANT_ROSTER_KEY, current=None, expected=roster_expected)

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
            field_failures=list(facts.values()),
        )

    # derive 需要 action_type 等必填已齐；编码已在上环收束，不再经 ValueError 整批
    out["draft_capability"] = derive_draft_capability(out)
    return out


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
