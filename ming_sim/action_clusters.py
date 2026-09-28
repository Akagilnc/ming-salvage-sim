"""动作档 FieldSpec 登记表（#515 / #1871）。

唯一真源：ACTION_CLUSTERS（由 action_materialize.install 装入）。
提供 kind/fields 枚举、shape 校验与 prompt 投影；分类器候选链与 materialize_fn 已删。

范围（ADR 0039 / #513）：机械聚类挂点，不是 25 词语义表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple


EFFECT_NOOP = "noop"
EFFECT_MATERIALIZE = "materialize"

@dataclass(frozen=True)
class FieldSpec:
    name: str
    zh: str
    allowed: Optional[FrozenSet[str]] = None
    default: Any = ""
    max_len: Optional[int] = None
    as_int: bool = False
    int_lo: int = 0  # symmetric lower bound; >0 marks positive integer
    int_hi: int = 10**9
    quantity_unit: Optional[str] = None
    season_option: bool = False
    # Optional per-enum execution metadata lives on the canonical field row.
    execution_coverage: Optional[Mapping[str, Optional[str]]] = None
    # Field is populated only when another canonical field has one of these values.
    populated_when: Optional[Tuple[str, FrozenSet[str]]] = None
    # A controller value may narrow this enum's effective allowed values.
    allowed_when: Optional[Tuple[str, str, FrozenSet[str]]] = None


@dataclass(frozen=True)
class ActionCluster:
    label_zh: str
    kind: str
    effect: str
    priority: int = 100
    fields: Tuple[FieldSpec, ...] = ()


# 由 action_materialize.install_action_catalog() 装入。
ACTION_CLUSTERS: Tuple[ActionCluster, ...] = ()
LABEL_TO_KIND: Dict[str, str] = {}
KNOWN_KINDS: FrozenSet[str] = frozenset()
# 从 catalog FieldSpec 派生的共享 superset 索引（只读 Mapping，非手写表）。
_FIELD_SPECS_BY_NAME: Mapping[str, FieldSpec] = MappingProxyType({})


def install_action_catalog(clusters: Sequence[ActionCluster]) -> None:
    """唯一装载点：登记行一次性写入派生索引。"""
    global ACTION_CLUSTERS, LABEL_TO_KIND, KNOWN_KINDS
    global _FIELD_SPECS_BY_NAME
    ACTION_CLUSTERS = tuple(clusters)
    LABEL_TO_KIND = {c.label_zh: c.kind for c in ACTION_CLUSTERS}
    KNOWN_KINDS = frozenset(c.kind for c in ACTION_CLUSTERS)
    specs: Dict[str, FieldSpec] = {}
    # #1871：catalog 只供 FieldSpec/枚举。
    for c in ACTION_CLUSTERS:
        for f in c.fields:
            # 同名 FieldSpec 以先出现为准（catalog 内不得自相矛盾）
            specs.setdefault(f.name, f)
    _FIELD_SPECS_BY_NAME = MappingProxyType(specs)


def _field_specs() -> Mapping[str, FieldSpec]:
    """内部只读索引；调用方 pop/mutate 不得影响全局真源。"""
    _ensure_catalog()
    return _FIELD_SPECS_BY_NAME


def _ensure_catalog() -> None:
    """Lazy-load action_materialize so ACTION_CLUSTERS FieldSpec catalog is present."""
    if ACTION_CLUSTERS:
        return
    import ming_sim.action_materialize  # noqa: F401


def _render_field_specs(
    specs: Sequence[Tuple[str, FieldSpec]],
) -> Tuple[List[str], List[str]]:
    """Render transport examples and action-scoped constraints from catalog rows."""
    lines: List[str] = []
    notes: List[str] = []
    seen_zh: set = set()
    for action, spec in specs:
        prefix = f"{action}·" if action else ""
        if spec.allowed is not None:
            values = sorted(spec.allowed, key=lambda value: (value != "无", value))
            example = f'"{"|".join(values)}"'
        elif spec.as_int:
            example = "null" if spec.default is None else "0"
            if spec.int_lo > 0 or spec.quantity_unit:
                constraint = (
                    f"可null；命中 JSON integer>={spec.int_lo}；禁数字字符串"
                    if spec.default is None
                    else f"JSON integer>={spec.int_lo}"
                )
                if spec.quantity_unit:
                    constraint += f"；单位={spec.quantity_unit}"
                notes.append(f"{prefix}{spec.zh}：{constraint}")
        else:
            example = '""'
        if spec.zh not in seen_zh:
            seen_zh.add(spec.zh)
            lines.append(f'  "{spec.zh}": {example},')
        if spec.populated_when is not None:
            controller_name, controller_values = spec.populated_when
            controller = _field_specs()[controller_name]
            values = "|".join(sorted(controller_values))
            notes.append(
                f"{prefix}{spec.zh}：仅{controller.zh}={values}时填写；其它留空"
            )
    return lines, notes


def cluster_by_kind(kind: str) -> Optional[ActionCluster]:
    _ensure_catalog()
    for c in ACTION_CLUSTERS:
        if c.kind == kind:
            return c
    return None


def season_option_fields(kind: str) -> Tuple[str, ...]:
    """Typed season-option keys projected from the canonical action row."""
    cluster = cluster_by_kind(kind)
    if cluster is None:
        return ()
    return ("action_type", *(f.name for f in cluster.fields if f.season_option))


def _season_specs(kind: str) -> Tuple[FieldSpec, ...]:
    cluster = cluster_by_kind(kind)
    return tuple(f for f in cluster.fields if f.season_option) if cluster else ()


def validate_season_option(option: Mapping[str, object]) -> str:
    """Validate a typed season option and return its canonical action type."""
    from ming_sim.strict_types import strict_int

    has_action_type = "action_type" in option
    action_type = str(option.get("action_type") or "").strip()
    _ensure_catalog()
    has_typed_fields = any(
        spec.season_option and spec.name in option
        for cluster in ACTION_CLUSTERS
        for spec in cluster.fields
    )
    if has_action_type and not action_type:
        raise ValueError("choice.action_type 不可空")
    if not has_action_type and has_typed_fields:
        raise ValueError("choice.action_type 不可空")
    if action_type and not _season_specs(action_type):
        raise ValueError(f"choice.action_type 非法：{action_type!r}")
    for spec in _season_specs(action_type):
        if spec.name not in option:
            raise ValueError(f"choice.{spec.name} 不可空")
        if spec.as_int and spec.default is None and option[spec.name] is None:
            raise ValueError(f"choice.{spec.name} 不可空")
        if not field_population_allowed(action_type, spec.name, option):
            raise ValueError(f"choice.{spec.name} 不适用于当前选项")
        value = option[spec.name]
        if spec.allowed is None and not spec.as_int and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ValueError(f"choice.{spec.name} 不可空")
        allowed = effective_field_allowed(spec, option)
        if allowed is not None and value not in allowed:
            raise ValueError(f"choice.{spec.name} 非法：{value!r}")
        if spec.as_int:
            number = strict_int(value, accept_numeric_strings=False)
            if number < spec.int_lo or number > spec.int_hi:
                raise ValueError(f"choice.{spec.name} 超出范围：{number!r}")
    return action_type


def season_option_contract_prompt(kind: str) -> str:
    """Human-facing season option contract projected from FieldSpec."""
    specs = _season_specs(kind)
    details = []
    effective_values: Dict[str, FrozenSet[str]] = {}
    for spec in specs:
        detail = spec.name
        if spec.allowed is not None:
            allowed = frozenset(
                value for value in spec.allowed
                if all(
                    field_population_allowed(kind, dependent.name, {spec.name: value})
                    for dependent in specs
                    if dependent.populated_when is not None
                    and dependent.populated_when[0] == spec.name
                )
            )
            effective_values[spec.name] = allowed
            if spec.allowed_when is not None:
                controller = spec.allowed_when[0]
                controller_values = effective_values.get(controller, frozenset())
                context = (
                    {controller: next(iter(controller_values))}
                    if len(controller_values) == 1 else {}
                )
                allowed = effective_field_allowed(spec, context) or frozenset()
            detail += f'（{"|".join(sorted(allowed))}）'
        if spec.as_int:
            detail += f"（JSON integer，{spec.int_lo}..{spec.int_hi}，禁数字字符串）"
        if spec.quantity_unit:
            detail += f"（单位={spec.quantity_unit}）"
        details.append(detail)
    if not details:
        return ""
    return (
        f'协饷 option 须携带 action_type="{kind}"、'
        + "、".join(details)
        + "；非协饷 option 保持既有 label/hint，不携带这些字段。"
    )


def cluster_fields_prompt(kind: str) -> str:
    """Render one catalog row's extraction fields without a parallel schema."""
    cluster = cluster_by_kind(kind)
    if cluster is None:
        return ""
    lines, notes = _render_field_specs([
        (cluster.label_zh, spec) for spec in cluster.fields
    ])
    rendered = "\n".join(lines) + ("\n" if lines else "")
    if notes:
        rendered += "  // " + "；".join(notes) + "\n"
    return rendered


def project_cluster_fields(kind: str, obj: Mapping[str, Any]) -> Dict[str, Any]:
    """Project one catalog row from Chinese/English transport keys.

    Projection only maps catalog fields and defaults. Transport and durable
    admission seams validate their respective candidate shapes.
    """
    cluster = cluster_by_kind(kind)
    if cluster is None:
        return {}
    return {
        spec.name: _field_raw(obj, spec)
        if _field_raw(obj, spec) is not None else spec.default
        for spec in cluster.fields
    }


class ActionCandidateShapeError(ValueError):
    pass


def empty_none_candidate() -> Dict[str, Any]:
    return _blank_candidate(kind="none")


def _blank_candidate(*, kind: str = "none") -> Dict[str, Any]:
    """空候选：字段与 default 只从 catalog FieldSpec 派生。"""
    out: Dict[str, Any] = {"kind": kind}
    for name, spec in _field_specs().items():
        out[name] = spec.default
    return out


def _as_int(value: object, *, lo: int = 0, hi: int = 10**9) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(n, hi))


def _resolve_kind(obj: Mapping[str, Any]) -> Optional[str]:
    _ensure_catalog()
    kind = str(obj.get("kind") or "").strip()
    if kind in KNOWN_KINDS:
        return kind
    label = str(obj.get("动作类型") or "").strip()
    if label in LABEL_TO_KIND:
        return LABEL_TO_KIND[label]
    return None


def _field_raw(obj: Mapping[str, Any], spec: FieldSpec) -> Any:
    if spec.name in obj:
        return obj.get(spec.name)
    if spec.zh in obj:
        return obj.get(spec.zh)
    return None


def validate_action_candidate_shape(obj: Any) -> Tuple[bool, str]:
    """未知 kind 拒；共享 superset 中出现的任意 enum 字段 out-of-enum 拒。"""
    _ensure_catalog()
    if not isinstance(obj, Mapping):
        return False, "candidate must be a mapping"
    kind = _resolve_kind(obj)
    if kind is None:
        raw_k = obj.get("kind") or obj.get("动作类型")
        return False, f"unknown action kind/label: {raw_k!r}"
    # 共享 superset：任一 catalog enum 字段若出现（en 或 zh 键），按 FieldSpec 校验
    for spec in _field_specs().values():
        if spec.allowed is None:
            continue
        raw = _field_raw(obj, spec)
        if raw is None:
            continue
        normalized = str(raw).strip()
        if not normalized:
            continue
        if normalized not in spec.allowed:
            return False, f"{spec.name} out of enum: {raw!r}"
    return True, ""


def effective_field_allowed(
    spec: FieldSpec, candidate: Mapping[str, Any],
) -> Optional[FrozenSet[str]]:
    """Project the enum values allowed for this candidate from one field row."""
    if spec.allowed_when is not None:
        controller, controller_value, allowed = spec.allowed_when
        if str(candidate.get(controller) or "").strip() == controller_value:
            return allowed
    return spec.allowed


def field_population_allowed(
    kind: str, field_name: str, candidate: Mapping[str, Any],
) -> bool:
    """Read a field's canonical population condition from its cluster row."""
    cluster = cluster_by_kind(kind)
    if cluster is None:
        return False
    spec = next((field for field in cluster.fields if field.name == field_name), None)
    if spec is None:
        return False
    if spec.populated_when is None:
        return True
    controller, allowed = spec.populated_when
    return str(candidate.get(controller) or "").strip() in allowed


def assert_action_candidate_shape(obj: Any) -> Dict[str, Any]:
    ok, reason = validate_action_candidate_shape(obj)
    if not ok:
        raise ActionCandidateShapeError(reason)
    return normalize_one_candidate(obj, soft=False)


def normalize_one_candidate(obj: Mapping[str, Any], *, soft: bool) -> Dict[str, Any]:
    _ensure_catalog()
    kind = _resolve_kind(obj)
    if kind is None:
        if soft:
            return empty_none_candidate()
        raise ActionCandidateShapeError(
            f"unknown action kind/label: {obj.get('kind') or obj.get('动作类型')!r}"
        )
    if not soft:
        ok, reason = validate_action_candidate_shape(obj)
        if not ok:
            raise ActionCandidateShapeError(reason)

    out = _blank_candidate(kind=kind)

    def _enum(value: object, allowed: FrozenSet[str], default: str) -> str:
        v = str(value if value is not None else default).strip()
        if not v:
            return default
        if v in allowed:
            return v
        if soft:
            return default
        raise ActionCandidateShapeError(f"value {v!r} not in {sorted(allowed)}")

    for name, spec in _field_specs().items():
        raw = _field_raw(obj, spec)
        if raw is None:
            raw = spec.default
        # #658：可选正整数 id（as_int + default None）禁 generic clamp；raw 直达严格写边界
        if spec.as_int and spec.default is None:
            out[name] = _field_raw(obj, spec)
            continue
        if spec.as_int:
            out[name] = _as_int(raw, lo=int(spec.int_lo), hi=int(spec.int_hi))
        elif spec.allowed is not None:
            out[name] = _enum(raw, spec.allowed, str(spec.default))
        else:
            # 容器值须 JSON 运输（stages/stop_condition/ongoing_effects 等）；
            # str(list/dict) 是 Python repr（单引号），下游 json.loads 会当坏形丢掉。
            if isinstance(raw, (dict, list, tuple)):
                s = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
            else:
                # Canonical generated body is transport, not user-entered metadata:
                # preserve the extractor's bytes (including edge whitespace).
                s = str(raw or "") if name == "new_content" else str(raw or "").strip()
            if spec.max_len is not None:
                s = s[: spec.max_len]
            out[name] = s
    if "draft_text" in obj:
        out["draft_text"] = obj.get("draft_text")
    # #1509：confirmation 目标编号非 FieldSpec，须随 candidate 过缝。
    if "target_ids" in obj and obj.get("target_ids") is not None:
        out["target_ids"] = obj.get("target_ids")
    elif "目标编号" in obj and obj.get("目标编号") is not None:
        out["target_ids"] = obj.get("目标编号")
    # #1783+#1778：仅 grant 一件事一案可带承办人/名单过缝（assignment 承办人走后置抽取，
    # assignee 不得当改派入口——见 test_assignment_lead_from_extract_*）。
    if kind == "grant_allocation":
        for key in ("assignee", "assignee_id", "assignee_name", "participant_roster", "承办人"):
            if key in obj and obj.get(key) not in (None, ""):
                out[key if key != "承办人" else "assignee"] = obj.get(key)
    return out

