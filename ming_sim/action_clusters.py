"""动作档机械聚类登记表（#515 S0）。

唯一真源：ACTION_CLUSTERS（由 action_materialize.install 装入完整行，
含 effect / fields / materialize_fn）。prompt 字段枚举、shape 校验、
dispatcher 均只读本表。

范围（ADR 0039 / #513）：机械聚类挂点，不是 25 词语义表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple


EFFECT_NOOP = "noop"
EFFECT_ANSWER_EXISTING = "answer_existing"
EFFECT_MATERIALIZE = "materialize"
_PROMOTED_FROM_DRAFT_KEY = "_promoted_from_draft"
_PROMOTED_FROM_DRAFT_SENTINEL = object()


def is_promoted_draft_candidate(candidate: Mapping[str, Any]) -> bool:
    """只认本进程归一器生成的 draft 来源身份；classifier 同名字段无权伪造。"""
    return (
        candidate.get(_PROMOTED_FROM_DRAFT_KEY)
        is _PROMOTED_FROM_DRAFT_SENTINEL
    )


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
    # Optional per-enum execution metadata lives on the canonical field row.
    execution_coverage: Optional[Mapping[str, Optional[str]]] = None


@dataclass(frozen=True)
class ActionCluster:
    label_zh: str
    kind: str
    effect: str
    priority: int = 100
    fields: Tuple[FieldSpec, ...] = ()
    # 物化委派：同一登记行携带；noop/answer 为 None
    materialize_fn: Optional[Callable[..., None]] = field(
        default=None, compare=False, hash=False, repr=False,
    )


# 由 action_materialize.install_action_catalog() 装入（含 materialize_fn）。
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
    for c in ACTION_CLUSTERS:
        if c.effect == EFFECT_MATERIALIZE and c.materialize_fn is None:
            raise RuntimeError(f"materialize cluster {c.kind!r} lacks materialize_fn")
        for f in c.fields:
            # 同名 FieldSpec 以先出现为准（catalog 内不得自相矛盾）
            specs.setdefault(f.name, f)
    _FIELD_SPECS_BY_NAME = MappingProxyType(specs)


def _field_specs() -> Mapping[str, FieldSpec]:
    """内部只读索引；调用方 pop/mutate 不得影响全局真源。"""
    _ensure_catalog()
    return _FIELD_SPECS_BY_NAME


def _ensure_catalog() -> None:
    """Lazy-load action_materialize so ACTION_CLUSTERS carries materialize_fn."""
    if ACTION_CLUSTERS:
        return
    import ming_sim.action_materialize  # noqa: F401


def classifier_action_types_prompt() -> str:
    _ensure_catalog()
    return "|".join(c.label_zh for c in ACTION_CLUSTERS)


def classifier_json_fields_prompt() -> str:
    """从登记 FieldSpec 生成 JSON 字段行（无手写字段副本）。

    对象本体保持合法 JSON；FieldSpec 派生的人可读约束（nullable /
    positive integer / 禁数字字符串）附在对象外，不进对象行内。
    """
    _ensure_catalog()
    lines = [f'  "动作类型": "{classifier_action_types_prompt()}",']
    notes: list[str] = []
    seen_zh: set = set()
    for c in ACTION_CLUSTERS:
        for f in c.fields:
            if f.zh in seen_zh:
                continue
            seen_zh.add(f.zh)
            if f.allowed is not None:
                # stable order for prompt: put 无 first when present
                vals = sorted(f.allowed, key=lambda x: (x != "无", x))
                lines.append(f'  "{f.zh}": "{"|".join(vals)}",')
            elif f.as_int:
                # 合法 JSON 缺省示例：optional→null，否则 0；约束说明派生到对象外
                example = "null" if f.default is None else "0"
                lines.append(f'  "{f.zh}": {example},')
                if f.int_lo > 0:
                    constraint = (
                        f"可null；命中 JSON integer>={f.int_lo}；禁数字字符串"
                        if f.default is None
                        else f"JSON integer>={f.int_lo}"
                    )
                    notes.append(f"{f.zh}：{constraint}")
            else:
                lines.append(f'  "{f.zh}": "",')
    # trailing comma cleanup on last line
    if lines:
        lines[-1] = lines[-1].rstrip(",")
    body = "{\n" + "\n".join(lines) + "\n}"
    if notes:
        return body + "\n" + "；".join(notes)
    return body


def cluster_by_kind(kind: str) -> Optional[ActionCluster]:
    _ensure_catalog()
    for c in ACTION_CLUSTERS:
        if c.kind == kind:
            return c
    return None


def materialize_clusters_ordered() -> Tuple[ActionCluster, ...]:
    _ensure_catalog()
    return tuple(
        sorted(
            (c for c in ACTION_CLUSTERS if c.effect == EFFECT_MATERIALIZE),
            key=lambda c: c.priority,
        )
    )


def cluster_effect(kind: str) -> str:
    c = cluster_by_kind(kind)
    return c.effect if c else EFFECT_NOOP


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
    # #1509：confirmation 同次抽取的目标编号非 classifier FieldSpec，须随 candidate 过缝
    # （normalize_intent_candidates 会再走本函数；丢了则真实 chat 路多候选修改必歧义）。
    if "target_ids" in obj and obj.get("target_ids") is not None:
        out["target_ids"] = obj.get("target_ids")
    elif "目标编号" in obj and obj.get("目标编号") is not None:
        out["target_ids"] = obj.get("目标编号")
    # CLI classifier 先归一一次，Future join 后还会再归一；保留本模块生成的来源标记，
    # 让同一句里原生 grant 与其 draft 别名仍能在既有 materialize 去重缝相认。
    if is_promoted_draft_candidate(obj):
        out[_PROMOTED_FROM_DRAFT_KEY] = _PROMOTED_FROM_DRAFT_SENTINEL
    _promote_draft_xiexang_payload(out)
    return out


def _promote_draft_xiexang_payload(candidate: Dict[str, Any]) -> None:
    """#1503：完整 draft 协饷载荷 → grant 单轨；缺项仍留普通拟旨。"""
    if str(candidate.get("kind") or "").strip() != "draft":
        return
    if str(candidate.get("grant_action") or "").strip() != "协饷":
        return
    # 完备性只读协饷既有权威缝；升格不得把普通拟旨变成玩家可见硬异常。
    from ming_sim.action_materialize import (
        IncompleteXiexangPayloadError,
        require_explicit_xiexang_fields,
    )
    try:
        require_explicit_xiexang_fields(
            amount=candidate.get("amount"),
            account=str(candidate.get("account") or ""),
            purpose=str(candidate.get("purpose") or ""),
            target_kind=str(candidate.get("target_kind") or ""),
            target_id=str(candidate.get("target_id") or ""),
            cadence=str(candidate.get("cadence") or ""),
        )
    except IncompleteXiexangPayloadError:
        return
    candidate[_PROMOTED_FROM_DRAFT_KEY] = _PROMOTED_FROM_DRAFT_SENTINEL
    candidate["kind"] = "grant_allocation"


def candidates_from_classifier_payload(raw: Any, *, soft: bool = True) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    items: Sequence[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, Mapping):
        items = [raw]
    else:
        if soft:
            return []
        raise ActionCandidateShapeError(f"payload must be mapping or list, got {type(raw).__name__}")

    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            if soft:
                continue
            raise ActionCandidateShapeError("list item must be a mapping")
        if soft:
            ok, _ = validate_action_candidate_shape(item)
            if not ok:
                continue
            cand = normalize_one_candidate(item, soft=True)
        else:
            cand = assert_action_candidate_shape(item)
        if cand["kind"] == "none":
            continue
        out.append(cand)
    return out


def normalize_intent_candidates(raw: Any) -> Optional[List[Dict[str, Any]]]:
    if raw is None:
        return None
    return candidates_from_classifier_payload(raw, soft=True)


def primary_intent(candidates: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if candidates is None:
        return None
    if not candidates:
        return empty_none_candidate()
    return min(candidates, key=lambda c: cluster_by_kind(str(c.get("kind") or "")).priority)


def resolve_primary_intent(preclassified_intent: Any) -> Optional[Dict[str, Any]]:
    """session.chat / web stream 共用：None|list|dict → primary 候选。

    - None → None（分类器未跑）
    - list → primary_intent(list)
    - dict/其它 → soft normalize 后再 primary
    """
    if preclassified_intent is None:
        return None
    if isinstance(preclassified_intent, list):
        return primary_intent(preclassified_intent)
    return primary_intent(normalize_intent_candidates(preclassified_intent))


def is_confirmation_decision(intent: Optional[Mapping[str, Any]]) -> bool:
    """确认回合屏蔽：kind=confirmation 且 应允/拒绝/留中/修改（#525 第三态；#1376 修改）。"""
    return (
        isinstance(intent, Mapping)
        and str(intent.get("kind") or "") == "confirmation"
        and str(intent.get("confirmation") or "") in {"应允", "拒绝", "留中", "修改"}
    )
