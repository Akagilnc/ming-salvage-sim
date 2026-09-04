"""#1624 结构化旨意共同契约：schema / 组装 / 落库前组合校验。

召对拟旨、手工拟诏、月末票拟三入口只提供原始输入，消费本模块 canonical 结果。
属地 8×3 矩阵真源 = execution_pressure.assert_target_locality_matrix；
事务类别闭集真源 = executor_routing.duty_route_categories（duty_routes 派生）。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    TargetLocalityMatrixError,
    assert_target_locality_matrix,
    normalize_locality_scope,
    project_target_locality_matrix_prompt,
    resolve_dossier_region_ids,
    write_locality_scope_for_target_kind,
)
from ming_sim.executor_routing import duty_route_categories


class StructuredDecreeCombinationError(ValueError):
    """结构化旨意组合校验失败（typed；纠错路径只捕本类，禁异常文本子串识别）。

    partial_result：抽取已解析但组合未过的首抽快照（含 participant_roster）；
    failed_fields：本不变式可修字段边界（单条）；
    draft_failures：批抽 idx → 可修字段边界；
    heal 只从纠错轮采纳边界内字段，保留首抽名册与未失败结构。
    """

    def __init__(
        self,
        message: object,
        *,
        partial_result: Optional[Dict[str, Any]] = None,
        failed_fields: Optional[frozenset[str]] = None,
        draft_failures: Optional[Dict[int, frozenset[str]]] = None,
    ) -> None:
        super().__init__(message)
        self.partial_result = partial_result
        self.failed_fields = frozenset(failed_fields or ())
        self.draft_failures = dict(draft_failures or {})


# 组合纠错可覆盖的结构字段（与 assemble/validate 核心键同集；名册/旨文不在此列）
STRUCTURED_DECREE_FIELD_KEYS: tuple[str, ...] = (
    "action_type",
    "dossier_action_type",
    "target_kind",
    "target_id",
    "locality_scope",
    "region_id",
    "transaction_category",
    "assignee_name",
    "assignee_id",
    "assignee",
)

# 失败字段 → 同义/依赖键一并采纳（禁只改英键漏中文同源键；
# target_kind 纠错必须同束带走身份 target_id/region_id，禁留旧身份）
_FAILED_FIELD_EXPAND: Dict[str, tuple[str, ...]] = {
    "action_type": ("action_type", "dossier_action_type"),
    "dossier_action_type": ("action_type", "dossier_action_type"),
    "target_kind": ("target_kind", "target_id", "region_id"),
    "assignee_name": ("assignee_name", "assignee_id", "assignee"),
    "assignee_id": ("assignee_name", "assignee_id", "assignee"),
    "assignee": ("assignee_name", "assignee_id", "assignee"),
}


def expand_combo_failed_fields(fields: object) -> tuple[str, ...]:
    """把不变式 failed_fields 扩成可 merge 的 STRUCTURED_DECREE_FIELD_KEYS 子集。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in fields or ():  # type: ignore[union-attr]
        key = str(raw or "").strip()
        if not key:
            continue
        for item in _FAILED_FIELD_EXPAND.get(key, (key,)):
            if item in STRUCTURED_DECREE_FIELD_KEYS and item not in seen:
                seen.add(item)
                out.append(item)
    return tuple(out)


# 抽取/层 A 运输键 → canonical 英键
_TRANSPORT_KEY_ALIASES: Dict[str, str] = {
    "动作类型": "action_type",
    "dossier_action_type": "action_type",
    "目标类型": "target_kind",
    "目标ID": "target_id",
    "目标": "target_id",
    "施行范围": "locality_scope",
    "地区ID": "region_id",
    "事务类别": "transaction_category",
    "承办人": "assignee_name",
    "assignee": "assignee_name",
    "assignee_id": "assignee_name",
    "holder_id": "assignee_name",
}

_CORE_KEYS = STRUCTURED_DECREE_FIELD_KEYS


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _transaction_categories() -> frozenset[str]:
    return duty_route_categories()


def structured_decree_prompt_contract() -> str:
    """三入口共用结构化旨意契约（唯一真源；禁入口平行复述）。

    运输键（中/英）均经 transport_keys_to_canonical 归一；本块只写闭集与语义一次。
    target×locality 可接受面由 TARGET_KIND_LOCALITY_SCOPES 投影（与 assert 同真源）；
    national 动作限制同属该投影，不扩票拟七类 action、不手抄第二份矩阵。
    """
    cats = "|".join(sorted(_transaction_categories()))
    kinds = "|".join(sorted(TARGET_KINDS))
    matrix_face = project_target_locality_matrix_prompt()
    return (
        "结构化旨意契约（共同真源；运输键经 transport_keys_to_canonical 归一）："
        f"target_kind/目标类型∈{kinds}；target_id/目标ID；"
        "locality_scope/施行范围∈national|single|none（中文全国|单省|无）；"
        f"{matrix_face}；"
        "region_id/地区ID——仅 target_kind=region 时填且与 target_id 同，非 region 必须空；"
        f"transaction_category/事务类别∈{cats}|——非空须在闭集；"
        "assignment 交办须填类别或点将；assignee_name/承办人仅点将填规范人名，"
        "机关承办留空，由职司路由（如督赈→户部）得出，勿把机关名写入承办人。"
        "明指某省差务→target_kind=region、target_id=省 id、locality_scope=single、"
        "region_id=同省 id；不得用 office 等机关目标承载省务；"
        "禁止用目标类型回写施行范围掩盖错误目标。"
        "assignee_name/region_id/transaction_category 输出时键可在、值可空串。"
    )


def transport_keys_to_canonical(raw: Mapping[str, object]) -> Dict[str, object]:
    """运输键归一；同义键合并，后写不覆盖已有非空 canonical。"""
    if not isinstance(raw, Mapping):
        raise ValueError("structured decree raw 须为 object")
    out: Dict[str, object] = dict(raw)
    for src, dest in _TRANSPORT_KEY_ALIASES.items():
        if src not in raw:
            continue
        if dest in out and _as_str(out.get(dest)).strip():
            continue
        out[dest] = raw[src]
    if not _as_str(out.get("action_type")).strip():
        for key in ("dossier_action_type", "动作类型"):
            if _as_str(out.get(key)).strip():
                out["action_type"] = out[key]
                break
    return out


def _scope_was_explicit(raw: Mapping[str, object]) -> bool:
    for key in ("locality_scope", "施行范围"):
        if key not in raw:
            continue
        if _as_str(raw.get(key)).strip():
            return True
    return False


def validate_structured_decree_combination(
    payload: Mapping[str, object],
    *,
    conn: Any = None,
    regions_content: Optional[Mapping[str, Any]] = None,
) -> None:
    """动作×目标×属地×承办组合校验（落库前共同闸）。

    属地矩阵唯一走 assert_target_locality_matrix；有 conn 时再 resolve 省 id。
    失败一律 StructuredDecreeCombinationError（typed）。
    """
    action_type = _as_str(payload.get("action_type") or "").strip()
    dossier_action_type = _as_str(payload.get("dossier_action_type") or "").strip()
    if action_type and dossier_action_type and action_type != dossier_action_type:
        raise StructuredDecreeCombinationError(
            "action_type 与 dossier_action_type 冲突："
            f"{action_type!r} vs {dossier_action_type!r}",
            failed_fields=frozenset({"action_type", "dossier_action_type"}),
        )
    action = action_type or dossier_action_type
    target_kind = _as_str(payload.get("target_kind") or "").strip()
    target_id = _as_str(payload.get("target_id") or "").strip()
    if not target_kind:
        raise StructuredDecreeCombinationError(
            "structured decree 缺 target_kind",
            failed_fields=frozenset({"target_kind"}),
        )
    if not target_id:
        raise StructuredDecreeCombinationError(
            "structured decree 缺 target_id",
            failed_fields=frozenset({"target_id"}),
        )

    try:
        scope = assert_target_locality_matrix(
            action_type=action or "policy",
            target_kind=target_kind,
            locality_scope=payload.get("locality_scope"),
        )
    except TargetLocalityMatrixError as exc:
        raise StructuredDecreeCombinationError(
            str(exc), failed_fields=exc.failed_fields,
        ) from exc
    except ValueError as exc:
        raise StructuredDecreeCombinationError(
            str(exc),
            failed_fields=frozenset({"locality_scope", "target_kind", "action_type"}),
        ) from exc

    region_id = _as_str(payload.get("region_id") or "").strip()
    if target_kind == "region":
        if region_id and region_id != target_id:
            raise StructuredDecreeCombinationError(
                f"region 目标 region_id={region_id!r} 须与 target_id={target_id!r} 一致",
                failed_fields=frozenset({"region_id", "target_id"}),
            )
    elif region_id:
        raise StructuredDecreeCombinationError(
            f"target_kind={target_kind!r} 不得夹带 region_id={region_id!r}",
            failed_fields=frozenset({"region_id"}),
        )

    cat = _as_str(payload.get("transaction_category") or "").strip()
    if cat and cat not in _transaction_categories():
        raise StructuredDecreeCombinationError(
            f"transaction_category 非法：{cat!r}",
            failed_fields=frozenset({"transaction_category"}),
        )
    if action == "assignment":
        assignee = _as_str(
            payload.get("assignee_name")
            or payload.get("assignee_id")
            or payload.get("assignee")
            or ""
        ).strip()
        if not cat and not assignee:
            raise StructuredDecreeCombinationError(
                "assignment 缺 transaction_category 与主办",
                failed_fields=frozenset({"transaction_category", "assignee_name"}),
            )

    if conn is not None:
        try:
            resolve_dossier_region_ids(
                conn,
                action_type=action or "policy",
                payload={
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "locality_scope": scope,
                    "region_id": region_id or (
                        target_id if target_kind == "region" else ""
                    ),
                },
                regions_content=regions_content,
            )
        except TargetLocalityMatrixError as exc:
            raise StructuredDecreeCombinationError(
                str(exc), failed_fields=exc.failed_fields,
            ) from exc
        except ValueError as exc:
            raise StructuredDecreeCombinationError(
                str(exc),
                failed_fields=frozenset({"region_id", "target_id", "locality_scope"}),
            ) from exc


def assemble_structured_decree(
    raw: Mapping[str, object],
    *,
    conn: Any = None,
    regions_content: Optional[Mapping[str, Any]] = None,
    validate: bool = True,
) -> Dict[str, object]:
    """原始入口字段 → canonical 结构；不按 target_kind 覆盖已给 locality。"""
    src = transport_keys_to_canonical(raw)
    explicit_scope = _scope_was_explicit(raw) or _scope_was_explicit(src)

    action = _as_str(src.get("action_type") or "").strip()
    target_kind = _as_str(src.get("target_kind") or "").strip()
    target_id = _as_str(src.get("target_id") or "").strip()
    region_id = _as_str(src.get("region_id") or "").strip()
    if target_kind == "region":
        from ming_sim.matching import canonical_region_id_exact

        regions = dict(regions_content or {})
        canonical_target = canonical_region_id_exact(target_id, regions)
        canonical_region = canonical_region_id_exact(region_id or target_id, regions)
        if canonical_target is not None:
            target_id = canonical_target
        if canonical_region is not None:
            region_id = canonical_region

    out: Dict[str, object] = dict(src)
    if action:
        out["action_type"] = action
        if not _as_str(out.get("dossier_action_type")).strip():
            out["dossier_action_type"] = action
    if target_kind:
        out["target_kind"] = target_kind
    if target_id:
        out["target_id"] = target_id

    if explicit_scope:
        out["locality_scope"] = normalize_locality_scope(src.get("locality_scope"))
    else:
        out["locality_scope"] = write_locality_scope_for_target_kind(target_kind)

    if target_kind == "region":
        out["region_id"] = region_id or target_id
    elif region_id:
        out["region_id"] = region_id
    else:
        out.pop("region_id", None)

    cat = _as_str(src.get("transaction_category") or "").strip()
    if cat:
        out["transaction_category"] = cat
    else:
        out.pop("transaction_category", None)

    assignee = _as_str(src.get("assignee_name") or "").strip()
    if action == "assignment" and cat:
        if assignee:
            out["assignee_name"] = assignee
            out["assignee_id"] = assignee
            out["assignee"] = assignee
        else:
            out.pop("assignee_name", None)
            out.pop("assignee_id", None)
            out.pop("assignee", None)
    elif assignee:
        out["assignee_name"] = assignee
        out["assignee_id"] = assignee
        out["assignee"] = assignee

    if validate:
        validate_structured_decree_combination(
            out, conn=conn, regions_content=regions_content,
        )
    return out


def apply_assembled_to_payload(
    payload: MutableMapping[str, object],
    assembled: Mapping[str, object],
) -> None:
    """把 assemble 结果写回 directive/rescript payload 核心字段。"""
    for key in _CORE_KEYS:
        if key not in assembled:
            payload.pop(key, None)
            continue
        val = assembled[key]
        if val in (None, ""):
            payload.pop(key, None)
        else:
            payload[key] = val


def combination_correction_feedback(exc: BaseException) -> str:
    """有界重试回喂：只纠正结构组合，不改写自由文本旨文。"""
    return (
        "【结构组合校验失败，请按共同契约重抽结构化字段（勿改旨文正文）】\n"
        f"{exc}\n"
        + structured_decree_prompt_contract()
        + "\n"
    )
