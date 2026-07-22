"""动作档机械聚类登记表（#515 S0）。

唯一真源：ACTION_CLUSTERS（由 action_materialize.install 装入完整行，
含 effect / fields / materialize_fn）。prompt 字段枚举、shape 校验、
dispatcher 均只读本表。

范围（ADR 0039 / #513）：机械聚类挂点，不是 25 词语义表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple


EFFECT_NOOP = "noop"
EFFECT_ANSWER_EXISTING = "answer_existing"
EFFECT_MATERIALIZE = "materialize"

# #515 验收：既有六类必须在登记中；未来新行 ⊆ 扩展，不改此集合。
REQUIRED_MIGRATED_KINDS = frozenset({
    "none", "confirmation", "secret", "cultivate", "appointment", "draft",
})


@dataclass(frozen=True)
class FieldSpec:
    name: str
    zh: str
    allowed: Optional[FrozenSet[str]] = None
    default: Any = ""
    max_len: Optional[int] = None
    as_int: bool = False
    int_hi: int = 10**9


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
KIND_TO_LABEL: Dict[str, str] = {}
KNOWN_KINDS: FrozenSet[str] = frozenset()
KNOWN_LABELS: FrozenSet[str] = frozenset()
CONFIRMATION_VALUES: FrozenSet[str] = frozenset({"应允", "拒绝", "无"})
SECRET_ACTION_VALUES: FrozenSet[str] = frozenset(
    {"无", "更新", "提交核议", "催办", "记进展"}
)
APPOINT_ACTION_VALUES: FrozenSet[str] = frozenset({"无", "任命", "罢免"})


def install_action_catalog(clusters: Sequence[ActionCluster]) -> None:
    """唯一装载点：登记行一次性写入派生索引。"""
    global ACTION_CLUSTERS, LABEL_TO_KIND, KIND_TO_LABEL, KNOWN_KINDS, KNOWN_LABELS
    global CONFIRMATION_VALUES, SECRET_ACTION_VALUES, APPOINT_ACTION_VALUES
    ACTION_CLUSTERS = tuple(clusters)
    LABEL_TO_KIND = {c.label_zh: c.kind for c in ACTION_CLUSTERS}
    KIND_TO_LABEL = {c.kind: c.label_zh for c in ACTION_CLUSTERS}
    KNOWN_KINDS = frozenset(KIND_TO_LABEL)
    KNOWN_LABELS = frozenset(LABEL_TO_KIND)
    missing = REQUIRED_MIGRATED_KINDS - KNOWN_KINDS
    if missing:
        raise RuntimeError(f"action catalog missing required kinds: {sorted(missing)}")
    for c in ACTION_CLUSTERS:
        if c.effect == EFFECT_MATERIALIZE and c.materialize_fn is None:
            raise RuntimeError(f"materialize cluster {c.kind!r} lacks materialize_fn")
    CONFIRMATION_VALUES = _enum_allowed("confirmation") or CONFIRMATION_VALUES
    SECRET_ACTION_VALUES = _enum_allowed("secret_action") or SECRET_ACTION_VALUES
    APPOINT_ACTION_VALUES = _enum_allowed("appoint_action") or APPOINT_ACTION_VALUES


def _enum_allowed(field_name: str) -> FrozenSet[str]:
    for c in ACTION_CLUSTERS:
        for f in c.fields:
            if f.name == field_name and f.allowed is not None:
                return f.allowed
    return frozenset()


def _ensure_catalog() -> None:
    """Lazy-load action_materialize so ACTION_CLUSTERS carries materialize_fn."""
    if ACTION_CLUSTERS:
        return
    import ming_sim.action_materialize  # noqa: F401


def classifier_action_types_prompt() -> str:
    _ensure_catalog()
    return "|".join(c.label_zh for c in ACTION_CLUSTERS)


def classifier_json_fields_prompt() -> str:
    """从登记 FieldSpec 生成 JSON 字段行（无手写字段副本）。"""
    _ensure_catalog()
    lines = [f'  "动作类型": "{classifier_action_types_prompt()}",']
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
                lines.append(f'  "{f.zh}": 0,')
            else:
                lines.append(f'  "{f.zh}": "",')
    # trailing comma cleanup on last line
    if lines:
        lines[-1] = lines[-1].rstrip(",")
    return "{\n" + "\n".join(lines) + "\n}"


def cluster_by_kind(kind: str) -> Optional[ActionCluster]:
    _ensure_catalog()
    for c in ACTION_CLUSTERS:
        if c.kind == kind:
            return c
    return None


def get_materializer(kind: str) -> Optional[Callable[..., None]]:
    c = cluster_by_kind(kind)
    return c.materialize_fn if c is not None else None


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
    return {
        "kind": kind,
        "confirmation": "无",
        "secret_action": "无",
        "order_id": 0,
        "new_title": "",
        "new_content": "",
        "deadline_months": 0,
        "cultivate_skill": "",
        "cultivate_trait": "",
        "appoint_action": "无",
        "name": "",
        "office": "",
    }


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
    _ensure_catalog()
    if not isinstance(obj, Mapping):
        return False, "candidate must be a mapping"
    kind = _resolve_kind(obj)
    if kind is None:
        raw_k = obj.get("kind") or obj.get("动作类型")
        return False, f"unknown action kind/label: {raw_k!r}"
    cluster = cluster_by_kind(kind)
    assert cluster is not None
    for spec in cluster.fields:
        if spec.allowed is None:
            continue
        raw = _field_raw(obj, spec)
        if raw is None:
            continue
        if str(raw).strip() not in spec.allowed:
            return False, f"{spec.name} out of enum: {raw!r}"
    for fname, allowed, zh in (
        ("confirmation", CONFIRMATION_VALUES, "确认"),
        ("secret_action", SECRET_ACTION_VALUES, "密令动作"),
        ("appoint_action", APPOINT_ACTION_VALUES, "任免动作"),
    ):
        raw = obj.get(fname, obj.get(zh))
        if raw is None:
            continue
        if str(raw).strip() not in allowed:
            return False, f"{fname} out of enum: {raw!r}"
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
    all_specs: Dict[str, FieldSpec] = {}
    for c in ACTION_CLUSTERS:
        for f in c.fields:
            all_specs[f.name] = f

    def _enum(value: object, allowed: FrozenSet[str], default: str) -> str:
        v = str(value if value is not None else default).strip()
        if v in allowed:
            return v
        if soft:
            return default
        raise ActionCandidateShapeError(f"value {v!r} not in {sorted(allowed)}")

    for name, spec in all_specs.items():
        raw = _field_raw(obj, spec)
        if raw is None:
            raw = spec.default
        if spec.as_int:
            if name == "deadline_months":
                out[name] = max(0, min(_as_int(raw), 36))
            else:
                out[name] = _as_int(raw, hi=spec.int_hi)
        elif spec.allowed is not None:
            out[name] = _enum(raw, spec.allowed, str(spec.default))
        else:
            s = str(raw or "").strip()
            if spec.max_len is not None:
                s = s[: spec.max_len]
            out[name] = s
    if "draft_text" in obj:
        out["draft_text"] = obj.get("draft_text")
    return out


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
    return candidates[0]


def inject_scripted_candidates(raw: Any) -> List[Dict[str, Any]]:
    return candidates_from_classifier_payload(raw, soft=False)
