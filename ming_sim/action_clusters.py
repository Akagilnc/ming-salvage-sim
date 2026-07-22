"""动作档机械聚类登记表（#515 S0）。

单一扩展挂点：后续动词聚类切片只在此加一行定义 + 注册 materialize 委派，
分类器 prompt 枚举、label→kind、typed shape、消费/物化 dispatch 都从本表生成。

范围（ADR 0039 / #513）：**机械聚类**挂点，不是 25 词语义表，也不收
平行自由文本规则库。口令档 / 对话档不进此表。

effect 语义：
- noop：零机械写入（「无」）
- answer_existing：只处置既有 pending，不新 stage（「确认」）
- materialize：经登记的 materializer 委派进真实 stage 路径（不抄第二套落库）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple


# effect tokens（登记表用，consumer 不得再 hardcode 语义分叉）
EFFECT_NOOP = "noop"
EFFECT_ANSWER_EXISTING = "answer_existing"
EFFECT_MATERIALIZE = "materialize"


@dataclass(frozen=True)
class FieldSpec:
    """候选子字段：英文名 + 中文 LLM 别名 + 枚举白名单（None=自由文本）+ default。"""

    name: str
    zh: str
    allowed: Optional[FrozenSet[str]] = None
    default: Any = ""
    max_len: Optional[int] = None
    as_int: bool = False
    int_hi: int = 10**9


@dataclass(frozen=True)
class ActionCluster:
    """一条动作档机械聚类。"""

    label_zh: str
    kind: str
    effect: str
    # 物化顺序（小先跑）；仅 effect=materialize 有意义
    priority: int = 100
    fields: Tuple[FieldSpec, ...] = ()


# 现有六类——新聚类 = 追加一行 + register_materializer(kind)（见 action_materialize）。
ACTION_CLUSTERS: Tuple[ActionCluster, ...] = (
    ActionCluster("无", "none", EFFECT_NOOP, priority=0),
    ActionCluster(
        "确认", "confirmation", EFFECT_ANSWER_EXISTING, priority=10,
        fields=(
            FieldSpec("confirmation", "确认", frozenset({"应允", "拒绝", "无"}), "无"),
        ),
    ),
    ActionCluster(
        "密令动作", "secret", EFFECT_MATERIALIZE, priority=30,
        fields=(
            FieldSpec(
                "secret_action", "密令动作",
                frozenset({"无", "更新", "提交核议", "催办", "记进展"}), "无",
            ),
            FieldSpec("order_id", "目标密令编号", None, 0, as_int=True),
            FieldSpec("new_title", "新标题", None, ""),
            FieldSpec("new_content", "新内容", None, "", max_len=500),
            FieldSpec("deadline_months", "期限月数", None, 0, as_int=True, int_hi=36),
        ),
    ),
    ActionCluster(
        "调教", "cultivate", EFFECT_MATERIALIZE, priority=40,
        fields=(
            FieldSpec("cultivate_skill", "调教技能", None, "", max_len=30),
            FieldSpec("cultivate_trait", "调教性格", None, "", max_len=30),
        ),
    ),
    ActionCluster(
        "拟旨", "draft", EFFECT_MATERIALIZE, priority=50,
        fields=(),
    ),
    ActionCluster(
        "任免", "appointment", EFFECT_MATERIALIZE, priority=60,
        fields=(
            FieldSpec(
                "appoint_action", "任免动作",
                frozenset({"无", "任命", "罢免"}), "无",
            ),
            FieldSpec("name", "姓名", None, "", max_len=20),
            FieldSpec("office", "官职", None, "", max_len=40),
        ),
    ),
)

LABEL_TO_KIND: Dict[str, str] = {c.label_zh: c.kind for c in ACTION_CLUSTERS}
KIND_TO_LABEL: Dict[str, str] = {c.kind: c.label_zh for c in ACTION_CLUSTERS}
KNOWN_KINDS = frozenset(KIND_TO_LABEL)
KNOWN_LABELS = frozenset(LABEL_TO_KIND)

# 兼容旧 import 名（子枚举仍可由登记表派生）
def _enum_allowed(field_name: str) -> FrozenSet[str]:
    for c in ACTION_CLUSTERS:
        for f in c.fields:
            if f.name == field_name and f.allowed is not None:
                return f.allowed
    return frozenset()


CONFIRMATION_VALUES = _enum_allowed("confirmation") or frozenset({"应允", "拒绝", "无"})
SECRET_ACTION_VALUES = _enum_allowed("secret_action") or frozenset(
    {"无", "更新", "提交核议", "催办", "记进展"}
)
APPOINT_ACTION_VALUES = _enum_allowed("appoint_action") or frozenset({"无", "任命", "罢免"})

# kind → materialize callable（由 action_materialize 在 import 时 register）
MaterializeFn = Callable[..., None]
_MATERIALIZERS: Dict[str, MaterializeFn] = {}


def register_materializer(kind: str, fn: MaterializeFn) -> None:
    """挂接物化委派。新聚类在此 + ACTION_CLUSTERS 行即可接入，不改编排散点。"""
    if kind not in KNOWN_KINDS:
        raise ValueError(f"register_materializer: unknown kind {kind!r}")
    _MATERIALIZERS[kind] = fn


def get_materializer(kind: str) -> Optional[MaterializeFn]:
    return _MATERIALIZERS.get(kind)


def materialize_clusters_ordered() -> Tuple[ActionCluster, ...]:
    return tuple(
        sorted(
            (c for c in ACTION_CLUSTERS if c.effect == EFFECT_MATERIALIZE),
            key=lambda c: c.priority,
        )
    )


class ActionCandidateShapeError(ValueError):
    """脚本化判词 / 严格注入路径：枚举外或未知 kind 响亮拒绝。"""


def classifier_action_types_prompt() -> str:
    """分类器 prompt 用的动作类型枚举串（同源登记表）。"""
    return "|".join(c.label_zh for c in ACTION_CLUSTERS)


def cluster_by_kind(kind: str) -> Optional[ActionCluster]:
    for c in ACTION_CLUSTERS:
        if c.kind == kind:
            return c
    return None


def empty_none_candidate() -> Dict[str, Any]:
    return _blank_candidate(kind="none")


def _blank_candidate(*, kind: str = "none") -> Dict[str, Any]:
    out: Dict[str, Any] = {
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
    return out


def _as_int(value: object, *, lo: int = 0, hi: int = 10**9) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(n, hi))


def _resolve_kind(obj: Mapping[str, Any]) -> Optional[str]:
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
    """严格 shape：未知 kind / 登记子枚举外值 → (False, reason)。"""
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
        v = str(raw).strip()
        if v not in spec.allowed:
            return False, f"{spec.name} out of enum: {raw!r}"
    # 跨类携带的常见子枚举（LLM 可能多填）——若出现也须在全局白名单内
    for fname, allowed in (
        ("confirmation", CONFIRMATION_VALUES),
        ("secret_action", SECRET_ACTION_VALUES),
        ("appoint_action", APPOINT_ACTION_VALUES),
    ):
        # zh aliases
        zh = {"confirmation": "确认", "secret_action": "密令动作", "appoint_action": "任免动作"}[fname]
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

    cluster = cluster_by_kind(kind)
    assert cluster is not None
    out = _blank_candidate(kind=kind)

    # Apply all clusters' known fields so multi-field payloads stay intact
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
            hi = spec.int_hi
            out[name] = max(0, min(_as_int(raw, hi=hi), hi)) if hi < 10**9 else _as_int(raw)
            if name == "deadline_months":
                out[name] = max(0, min(_as_int(raw), 36))
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
        # effect=noop never appears here (none stripped); answer/materialize kept
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


def cluster_effect(kind: str) -> str:
    c = cluster_by_kind(kind)
    return c.effect if c else EFFECT_NOOP
