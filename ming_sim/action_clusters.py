"""动作档机械聚类登记表（#515 S0）。

单一扩展挂点：后续动词聚类切片只在此加一行定义，分类器 prompt 枚举、
label→kind、typed shape 校验、候选 list 归一都从本表生成。

范围（ADR 0039 / #513）：**机械聚类**挂点，不是 25 词语义表，也不收
平行自由文本规则库。口令档 / 对话档不进此表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ActionCluster:
    """一条动作档机械聚类。"""

    label_zh: str
    kind: str
    # 应答类（准驳）：只处置既有 pending，不新 stage（PRD #513 裁决豁免）。
    answer_class: bool = False


# 现有六类；新聚类 = 在此追加一行（外加 materialize 委派，不在本模块抄落库）。
ACTION_CLUSTERS: Tuple[ActionCluster, ...] = (
    ActionCluster("无", "none"),
    ActionCluster("确认", "confirmation", answer_class=True),
    ActionCluster("密令动作", "secret"),
    ActionCluster("调教", "cultivate"),
    ActionCluster("任免", "appointment"),
    ActionCluster("拟旨", "draft"),
)

LABEL_TO_KIND: Dict[str, str] = {c.label_zh: c.kind for c in ACTION_CLUSTERS}
KIND_TO_LABEL: Dict[str, str] = {c.kind: c.label_zh for c in ACTION_CLUSTERS}
KNOWN_KINDS = frozenset(KIND_TO_LABEL)
KNOWN_LABELS = frozenset(LABEL_TO_KIND)

CONFIRMATION_VALUES = frozenset({"应允", "拒绝", "无"})
SECRET_ACTION_VALUES = frozenset({"无", "更新", "提交核议", "催办", "记进展"})
APPOINT_ACTION_VALUES = frozenset({"无", "任命", "罢免"})

# 候选 dict 的稳定字段（classify 软洗后形态）。
_CANDIDATE_KEYS = (
    "kind",
    "confirmation",
    "secret_action",
    "order_id",
    "new_title",
    "new_content",
    "deadline_months",
    "cultivate_skill",
    "cultivate_trait",
    "appoint_action",
    "name",
    "office",
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
    """从英文 kind 或中文 动作类型 解析登记 kind；未知返回 None。"""
    kind = str(obj.get("kind") or "").strip()
    if kind in KNOWN_KINDS:
        return kind
    label = str(obj.get("动作类型") or "").strip()
    if label in LABEL_TO_KIND:
        return LABEL_TO_KIND[label]
    return None


def validate_action_candidate_shape(obj: Any) -> Tuple[bool, str]:
    """严格 shape：未知 kind / 子枚举外值 → (False, reason)。"""
    if not isinstance(obj, Mapping):
        return False, "candidate must be a mapping"
    kind = _resolve_kind(obj)
    if kind is None:
        raw_k = obj.get("kind") or obj.get("动作类型")
        return False, f"unknown action kind/label: {raw_k!r}"
    conf = obj.get("confirmation", obj.get("确认", "无"))
    if conf is not None and str(conf).strip() not in CONFIRMATION_VALUES:
        return False, f"confirmation out of enum: {conf!r}"
    sa = obj.get("secret_action", obj.get("密令动作", "无"))
    if sa is not None and str(sa).strip() not in SECRET_ACTION_VALUES:
        return False, f"secret_action out of enum: {sa!r}"
    aa = obj.get("appoint_action", obj.get("任免动作", "无"))
    if aa is not None and str(aa).strip() not in APPOINT_ACTION_VALUES:
        return False, f"appoint_action out of enum: {aa!r}"
    return True, ""


def assert_action_candidate_shape(obj: Any) -> Dict[str, Any]:
    """脚本化判词注入：坏 shape 抛 ActionCandidateShapeError。"""
    ok, reason = validate_action_candidate_shape(obj)
    if not ok:
        raise ActionCandidateShapeError(reason)
    return normalize_one_candidate(obj, soft=False)


def normalize_one_candidate(obj: Mapping[str, Any], *, soft: bool) -> Dict[str, Any]:
    """单条候选洗成引擎形态。soft=True 时子枚举外值折 default；kind 仍须在登记表。"""
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

    def _enum(value: object, allowed: frozenset, default: str) -> str:
        v = str(value if value is not None else default).strip()
        if v in allowed:
            return v
        if soft:
            return default
        raise ActionCandidateShapeError(f"value {v!r} not in {sorted(allowed)}")

    conf_raw = obj.get("confirmation", obj.get("确认", "无"))
    sa_raw = obj.get("secret_action", obj.get("密令动作", "无"))
    aa_raw = obj.get("appoint_action", obj.get("任免动作", "无"))
    out = _blank_candidate(kind=kind)
    out["confirmation"] = _enum(conf_raw, CONFIRMATION_VALUES, "无")
    out["secret_action"] = _enum(sa_raw, SECRET_ACTION_VALUES, "无")
    out["order_id"] = _as_int(obj.get("order_id", obj.get("目标密令编号", 0)))
    out["new_title"] = str(obj.get("new_title", obj.get("新标题", "")) or "").strip()
    out["new_content"] = str(obj.get("new_content", obj.get("新内容", "")) or "").strip()[:500]
    out["deadline_months"] = max(0, min(_as_int(obj.get("deadline_months", obj.get("期限月数", 0))), 36))
    out["cultivate_skill"] = str(
        obj.get("cultivate_skill", obj.get("调教技能", "")) or ""
    ).strip()[:30]
    out["cultivate_trait"] = str(
        obj.get("cultivate_trait", obj.get("调教性格", "")) or ""
    ).strip()[:30]
    out["appoint_action"] = _enum(aa_raw, APPOINT_ACTION_VALUES, "无")
    out["name"] = str(obj.get("name", obj.get("姓名", "")) or "").strip()[:20]
    out["office"] = str(obj.get("office", obj.get("官职", "")) or "").strip()[:40]
    # Preserve optional draft_text if callers/tests attach it (not from classifier).
    if "draft_text" in obj:
        out["draft_text"] = obj.get("draft_text")
    return out


def candidates_from_classifier_payload(raw: Any, *, soft: bool = True) -> List[Dict[str, Any]]:
    """LLM / 原始 payload → 候选列表。

    - 单对象 → 长度 0（kind=none）或 1
    - 已是 list → 逐条归一
    - soft：坏 shape / 未知 kind → 丢弃该条；全坏则 []
    - strict（soft=False）：任一坏 shape 抛 ActionCandidateShapeError
    """
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
    """消费点统一入口。

    - None → None（分类器未跑，保留串行回落语义）
    - dict / list → soft 归一后的 list（kind=none 或空 → []）
    """
    if raw is None:
        return None
    return candidates_from_classifier_payload(raw, soft=True)


def primary_intent(candidates: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """给仍按单对象读 kind 的路径：None=未跑；[]→{kind:none}；否则首条。"""
    if candidates is None:
        return None
    if not candidates:
        return empty_none_candidate()
    return candidates[0]


def inject_scripted_candidates(raw: Any) -> List[Dict[str, Any]]:
    """表驱动 / 脚本化判词：严格校验，枚举外响亮拒绝。"""
    return candidates_from_classifier_payload(raw, soft=False)
