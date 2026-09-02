"""#1624 结构化旨意共同契约：schema / 组装 / 落库前组合校验。

召对拟旨、手工拟诏、月末票拟三入口只提供原始输入，消费本模块 canonical 结果。
属地 8×3 矩阵真源 = execution_pressure.assert_target_locality_matrix；
事务类别闭集真源 = executor_routing.duty_route_categories（duty_routes 派生）。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    assert_target_locality_matrix,
    normalize_locality_scope,
    resolve_dossier_region_ids,
    write_locality_scope_for_target_kind,
)
from ming_sim.executor_routing import duty_route_categories


class StructuredDecreeCombinationError(ValueError):
    """结构化旨意组合校验失败（typed；纠错路径只捕本类，禁异常文本子串识别）。"""


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

_CORE_KEYS = (
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


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _transaction_categories() -> frozenset[str]:
    return duty_route_categories()


def structured_decree_guidance() -> str:
    """三入口共用语义指引（禁止各入口平行复述）。"""
    cats = "|".join(sorted(_transaction_categories()))
    kinds = "|".join(sorted(TARGET_KINDS))
    return (
        "结构化旨意契约（共同真源）："
        f"目标类型∈{kinds}；施行范围∈无|全国|单省（落库 national/single/none）。"
        "明指某省差务→目标类型=region、目标ID=省 id、施行范围=单省、地区ID=同省 id；"
        "不得把户部/兵部等机关写成目标类型=office 来承载省务。"
        f"交办类动作类型=assignment 且填事务类别（{cats}）；"
        "承办机关只由既有职司路由（如督赈→户部）得出，勿把机关名写入承办人；"
        "承办人仅在皇帝点将时填规范人名，未点将留空。"
        "禁止用目标类型回写施行范围掩盖错误目标。"
    )


def structured_decree_extract_schema_lines() -> str:
    """召对/手工拟旨抽取共用 schema 行（中文运输键；组装后转 canonical）。"""
    cats = "|".join(sorted(_transaction_categories()))
    kinds = "|".join(sorted(TARGET_KINDS))
    return (
        f'  "目标类型": "{kinds}",\n'
        '  "目标ID": "",\n'
        '  "地区ID": "",              // region 目标时与目标ID同；非 region 留空\n'
        '  "施行范围": "无|全国|单省", // 省务=单省；全国政令=全国；无属地=无\n'
        f'  "事务类别": "{cats}|", // assignment 交办填类别；非交办留空\n'
        '  "承办人": "",              // 仅点将填规范人名；机关承办留空走职司路由\n'
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
    action = _as_str(
        payload.get("action_type") or payload.get("dossier_action_type") or ""
    ).strip()
    target_kind = _as_str(payload.get("target_kind") or "").strip()
    target_id = _as_str(payload.get("target_id") or "").strip()
    if not target_kind:
        raise StructuredDecreeCombinationError("structured decree 缺 target_kind")
    if not target_id:
        raise StructuredDecreeCombinationError("structured decree 缺 target_id")

    try:
        scope = assert_target_locality_matrix(
            action_type=action or "policy",
            target_kind=target_kind,
            locality_scope=payload.get("locality_scope"),
        )
    except ValueError as exc:
        raise StructuredDecreeCombinationError(str(exc)) from exc

    region_id = _as_str(payload.get("region_id") or "").strip()
    if target_kind == "region":
        if region_id and region_id != target_id:
            raise StructuredDecreeCombinationError(
                f"region 目标 region_id={region_id!r} 须与 target_id={target_id!r} 一致"
            )
    elif region_id and scope == "none":
        raise StructuredDecreeCombinationError(
            f"locality_scope=none 不得夹带 region_id={region_id!r}"
        )

    if action == "assignment":
        cat = _as_str(payload.get("transaction_category") or "").strip()
        assignee = _as_str(
            payload.get("assignee_name")
            or payload.get("assignee_id")
            or payload.get("assignee")
            or ""
        ).strip()
        if not cat and not assignee:
            raise StructuredDecreeCombinationError(
                "assignment 缺 transaction_category 与主办"
            )
        if cat and cat not in _transaction_categories():
            raise StructuredDecreeCombinationError(
                f"transaction_category 非法：{cat!r}"
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
        except ValueError as exc:
            raise StructuredDecreeCombinationError(str(exc)) from exc


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

    region_id = _as_str(src.get("region_id") or "").strip()
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
        + structured_decree_guidance()
        + "\n"
    )


def structured_decree_rescript_option_lines() -> str:
    """月末票拟/改票层 A 英键字段行（闭集同源；禁入口手抄第二份）。"""
    cats = "|".join(sorted(_transaction_categories()))
    kinds = "|".join(sorted(TARGET_KINDS))
    return (
        "每个 option 结构化字段（共同契约英键）："
        f"action_type；target_kind∈{kinds}；target_id；"
        "locality_scope∈national|single|none；region_id；"
        f"transaction_category∈{cats}|；"
        "assignee_name（仅点将填规范人名，未点将空串）。"
        "assignee_name/region_id/transaction_category 三键必须输出，值可空串。"
    )
