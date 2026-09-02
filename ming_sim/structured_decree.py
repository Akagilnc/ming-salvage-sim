"""#1624 结构化旨意共同契约：schema / 组装 / 落库前组合校验。

召对拟旨、手工拟诏、月末票拟三入口只提供原始输入，消费本模块 canonical 结果。
禁止平行定义目标/属地/承办校验；禁止用 target_kind 覆盖 locality_scope 掩盖错误目标。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    normalize_locality_scope,
    resolve_dossier_region_ids,
)

# 职司路由事务类别闭集（与 ACTION_CLUSTERS / offices.json duty_routes 同族；不新建路由）
TRANSACTION_CATEGORIES = frozenset({
    "钱粮", "清丈", "督赈", "缉拿", "缉捕", "河工",
})

# 抽取/层 A 运输键 → canonical 英键（组装入口）
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

# 缺省 locality：仅当输入未给出 scope 时补全；显式错误组合不得覆盖
_DEFAULT_SCOPE_BY_TARGET = {
    "region": "single",
}


def structured_decree_guidance() -> str:
    """三入口共用语义指引（禁止各入口平行复述）。"""
    cats = "|".join(sorted(TRANSACTION_CATEGORIES))
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
    cats = "|".join(sorted(TRANSACTION_CATEGORIES))
    kinds = "|".join(sorted(TARGET_KINDS))
    return (
        f'  "目标类型": "{kinds}",\n'
        '  "目标ID": "",\n'
        '  "地区ID": "",              // region 目标时与目标ID同；非 region 留空\n'
        '  "施行范围": "无|全国|单省", // 省务=单省；全国政令=全国；无属地=无\n'
        f'  "事务类别": "{cats}|", // assignment 交办填类别；非交办留空\n'
        '  "承办人": "",              // 仅点将填规范人名；机关承办留空走职司路由\n'
    )


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


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
    # action_type 优先；dossier 侧同义
    if not _as_str(out.get("action_type")).strip():
        for key in ("dossier_action_type", "动作类型"):
            if _as_str(out.get(key)).strip():
                out["action_type"] = out[key]
                break
    return out


def _scope_was_explicit(raw: Mapping[str, object]) -> bool:
    """运输或 canonical 是否显式给出 locality（含中文三值）；缺键/空白=未给出。"""
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

    有 conn 时走 resolve_dossier_region_ids 完整属地 oracle；
    无 conn 时只做 8×3 矩阵与 assignment 承办规则。
    """
    action = _as_str(
        payload.get("action_type") or payload.get("dossier_action_type") or ""
    ).strip()
    target_kind = _as_str(payload.get("target_kind") or "").strip()
    target_id = _as_str(payload.get("target_id") or "").strip()
    if not target_kind:
        raise ValueError("structured decree 缺 target_kind")
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind 非法：{target_kind!r}")
    if not target_id:
        raise ValueError("structured decree 缺 target_id")

    scope = normalize_locality_scope(payload.get("locality_scope"))

    # 8×3 矩阵（与 resolve_dossier_region_ids 同源规则；禁止平行第二份）
    if target_kind == "region":
        if scope != "single":
            raise ValueError(
                f"region 目标与 locality_scope={scope!r} 矛盾（须 single）"
            )
    elif target_kind == "dossier":
        if scope != "none":
            raise ValueError(
                f"target_kind=dossier 与 locality_scope={scope!r} 矛盾（须 none）"
            )
    elif scope == "single":
        raise ValueError(
            f"locality_scope=single 只配 region 目标，得 target_kind={target_kind!r}"
        )
    elif scope == "national":
        if target_kind in {"character", "office", "army", "dossier"}:
            raise ValueError(
                f"target_kind={target_kind!r} 不得 national fan-out"
            )

    region_id = _as_str(payload.get("region_id") or "").strip()
    if target_kind == "region":
        if region_id and region_id != target_id:
            raise ValueError(
                f"region 目标 region_id={region_id!r} 须与 target_id={target_id!r} 一致"
            )
    elif region_id and scope == "none":
        # 非属地不得夹带 region_id 冒充省务
        raise ValueError(
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
            raise ValueError("assignment 缺 transaction_category 与主办")
        if cat and cat not in TRANSACTION_CATEGORIES:
            raise ValueError(f"transaction_category 非法：{cat!r}")

    if conn is not None:
        # 完整属地解析（含省 id 存在性）；matrix 已先行
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


def assemble_structured_decree(
    raw: Mapping[str, object],
    *,
    conn: Any = None,
    regions_content: Optional[Mapping[str, Any]] = None,
    validate: bool = True,
) -> Dict[str, object]:
    """原始入口字段 → canonical 结构；不按 target_kind 覆盖已给 locality。

    - 缺 locality 时按目标补默认（region→single，其余→none）
    - 显式 locality 只归一、不改写；与目标矛盾 → 组合校验 fail-loud
    - assignment+事务类别：不把机关名承办人写入 assignee（点将人名除外，由调用方名册闸）
    - region：region_id 缺省=target_id
    """
    src = transport_keys_to_canonical(raw)
    explicit_scope = _scope_was_explicit(raw) or _scope_was_explicit(src)

    action = _as_str(src.get("action_type") or "").strip()
    target_kind = _as_str(src.get("target_kind") or "").strip()
    target_id = _as_str(src.get("target_id") or "").strip()

    out: Dict[str, object] = dict(src)
    if action:
        out["action_type"] = action
        # durable 指令载荷惯用键
        if "dossier_action_type" not in out or not _as_str(
            out.get("dossier_action_type")
        ).strip():
            out["dossier_action_type"] = action
    if target_kind:
        out["target_kind"] = target_kind
    if target_id:
        out["target_id"] = target_id

    # locality：显式只 normalize；缺省才补
    if explicit_scope:
        out["locality_scope"] = normalize_locality_scope(src.get("locality_scope"))
    else:
        default = _DEFAULT_SCOPE_BY_TARGET.get(target_kind, "none")
        out["locality_scope"] = default

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
    # assignment + 事务类别：机关承办归职司路由；空 assignee 不写人物
    if action == "assignment" and cat:
        if assignee:
            out["assignee_name"] = assignee
            out["assignee_id"] = assignee
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
    for key in (
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
    ):
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
