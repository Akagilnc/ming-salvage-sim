"""关系账 S1：有向边事件的契约、校验和 0079 读侧适配。

本模块只负责边事件流水，不负责摘要酿制，也不改 0079 的写端。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Iterable

EMPEROR_NODE = "皇帝"

MINISTER_EDGE_KINDS = frozenset({
    "荐引", "恩义", "结怨", "站台", "使绊", "联名", "连坐", "把柄", "协作",
})
CREDIT_EDGE_KINDS = frozenset({"兑现所托", "辜负", "撑腰", "弃卒保车", "知遇"})
EDGE_KINDS = MINISTER_EDGE_KINDS | CREDIT_EDGE_KINDS

# 0079 的记录只有一个当事人；方向由事件语义决定，不能由自由文本猜。
CREDIT_DIRECTION = {
    "兑现所托": "person_to_emperor",
    "撑腰": "emperor_to_person",
    "知遇": "emperor_to_person",
    "辜负": "emperor_to_person",
    "弃卒保车": "emperor_to_person",
}

_ROUND_RE = re.compile(r"(?:^|[|/:; ])round[=: -](\d+)(?:$|[|/:; ])", re.I)
_TURN_RE = re.compile(r"(?:^|[|/:; ])turn[=: -](\d+)(?:$|[|/:; ])", re.I)

# #633 结算口：非旨意自然演化的互动来源哨兵（与 shared canonical 同一哨兵字面）。
SETTLEMENT_ORIGIN_SENTINEL = "盘面自发"


def settlement_edge_origin(origin_ref: object, kind: str) -> str:
    """#633 结算口唯一 origin 拼装器：``{来源引用}:relation:{类目}``。

    来源须为非空字符串且已过 ``GameDB.effect_origin_rejection`` 守门（守门由
    ``_validated_settlement_origin`` 在调用侧先行）；缺失或非字符串形状在此
    诚实报错，不再静默默认成「盘面自发」。bind_origin_round 在写口内再附
    ``|round:N``（N=当前回合），TD-1 的 origin 回指由既有绑定机制承担，此处
    不重复拼 round。禁在调用侧另拼第二套 origin。"""
    if not isinstance(origin_ref, str):
        raise ValueError(f"来源引用必须为字符串，得 {type(origin_ref).__name__}")
    base = origin_ref.strip()
    if not base:
        raise ValueError("效果缺 origin_ref；盘面自然演化须显式标为「盘面自发」")
    return f"{base}:relation:{validate_edge_kind(kind)}"


def _validated_settlement_origin(db: Any, origin_ref: object) -> str:
    """结算口 provenance 守门：只收精确「盘面自发」或已颁且授权效果的案卷引用。

    复用 GameDB.effect_origin_rejection 既有拒收 API；拒绝缺失、伪前缀、未知/
    未授权案卷与自带 round/turn 的伪造值（origin_round 一律由当前回合同步绑定，
    TD-1 不容伪造）。非法形状按失败诚实报错，不猜测修正。"""
    if not isinstance(origin_ref, str):
        raise ValueError(f"来源引用必须为字符串，得 {type(origin_ref).__name__}")
    value = origin_ref.strip()
    if not value:
        raise ValueError("效果缺 origin_ref；盘面自然演化须显式标为「盘面自发」")
    if _ROUND_RE.search(value) or _TURN_RE.search(value):
        raise ValueError(
            f"来源引用不得自带回合绑定（origin_round 由当前回合强制）：{value}"
        )
    if db.effect_origin_rejection(value) is not None:
        raise ValueError(f"origin_ref 非法：{value}")
    return value


def validate_edge_kind(event_kind: Any) -> str:
    kind = str(event_kind or "").strip()
    if kind not in EDGE_KINDS:
        raise ValueError(f"未知边事件类目: {kind!r}")
    return kind


def normalize_evidence(evidence: Any) -> bool:
    if isinstance(evidence, bool):
        return evidence
    if evidence in (None, 0, 1):
        return bool(evidence)
    raise ValueError("evidence 必须是布尔值")


def bind_origin_round(origin: Any, turn: int) -> tuple[str, int]:
    text = str(origin or "").strip()
    if not text:
        raise ValueError("边事件 origin 不能为空")
    match = _ROUND_RE.search(text) or _TURN_RE.search(text)
    if match:
        return text, int(match.group(1))
    round_no = int(turn)
    return f"{text}|round:{round_no}", round_no


def credit_event_to_edge(record: Mapping[str, Any]) -> dict[str, Any]:
    kind = validate_edge_kind(record.get("event_kind") or record.get("kind"))
    if kind not in CREDIT_EDGE_KINDS:
        raise ValueError(f"非 0079 信用事件类目: {kind!r}")
    person = str(
        record.get("person")
        or record.get("person_name")
        or record.get("subject")
        or record.get("character")
        or ""
    ).strip()
    if not person:
        raise ValueError("信用事件缺少当事人")
    context = str(record.get("context") or record.get("sentence") or "").strip()
    if not context:
        raise ValueError("信用事件语境不能为空")
    direction = CREDIT_DIRECTION[kind]
    source, target = (
        (EMPEROR_NODE, person)
        if direction == "emperor_to_person"
        else (person, EMPEROR_NODE)
    )
    turn = int(record.get("turn") or record.get("source_turn") or 0)
    bound_origin, origin_round = bind_origin_round(
        record.get("origin") or record.get("source_id"), turn
    )
    return {
        "source": source,
        "target": target,
        "event_kind": kind,
        "context": context,
        "origin": bound_origin,
        "origin_round": origin_round,
        "turn": turn,
        "year": int(record.get("year") or 0),
        "period": int(record.get("period") or 0),
        "evidence": False,
    }


def credit_events_as_edges(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [credit_event_to_edge(record) for record in records]


# ── #633 结算口（ADR 0082）：邸报大臣互动 → 边事件当场落库 ──────────────


def _capture_one_interaction(
    db: Any, state: Any, item: Mapping[str, Any], turn: int,
) -> list[dict[str, Any]]:
    kind = validate_edge_kind(item.get("类目") or item.get("kind"))
    if kind not in MINISTER_EDGE_KINDS:
        raise ValueError(f"结算口只收大臣侧类目，得 {kind!r}（君臣类目归 0079 写端）")
    raw_source = (
        item["施动者"] if item.get("施动者") is not None else item.get("source")
    )
    if not isinstance(raw_source, str):
        raise ValueError(
            "施动者不能为空" if raw_source is None
            else f"施动者必须为字符串，得 {type(raw_source).__name__}"
        )
    source = raw_source.strip()
    if not source:
        raise ValueError("施动者不能为空")
    raw_targets = (
        item["受动者"] if item.get("受动者") is not None else item.get("target")
    )
    # 受动者形状只收字符串或纯字符串列表；tuple/混型等垃圾按失败逐项拒收。
    if isinstance(raw_targets, str):
        candidates: list[str] = [raw_targets]
    elif isinstance(raw_targets, list) and all(isinstance(t, str) for t in raw_targets):
        candidates = list(raw_targets)
    else:
        raise ValueError("受动者必须为字符串或字符串列表")
    seen: set[str] = set()
    targets: list[str] = []
    for candidate in candidates:
        name = candidate.strip()
        if name and name != source and name not in seen:
            seen.add(name)
            targets.append(name)
    if not targets:
        raise ValueError("受动者不能为空")
    raw_context = (
        item["语境"] if item.get("语境") is not None else item.get("context")
    )
    if not isinstance(raw_context, str):
        raise ValueError(
            "边事件语境不能为空" if raw_context is None
            else f"语境必须为字符串，得 {type(raw_context).__name__}"
        )
    # F1：strip 只作非空谓词；存储值原样交写口（字节相等验收靠这条不加工）。
    if not raw_context.strip():
        raise ValueError("边事件语境不能为空")
    context = raw_context
    origin = settlement_edge_origin(
        _validated_settlement_origin(
            db,
            item.get("来源引用") if item.get("来源引用") is not None else item.get("origin_ref"),
        ),
        kind,
    )
    out: list[dict[str, Any]] = []
    for target in targets:
        # r2 F2 基数：每「施动者→受动者」有序对恰一行；N 方联名=牵头者→各联署者
        # N-1 行；联署者互不写边、不做对称翻倍——由这个机械展开保证。
        edge_id = int(db.record_relation_edge_event(
            source=source,
            target=target,
            event_kind=kind,
            context=context,
            origin=origin,
            turn=turn,
            year=int(state.year),
            period=int(state.period),
        ))
        out.append({
            "source": source, "target": target, "event_kind": kind,
            "origin": origin, "edge_id": edge_id,
        })
    return out


def resolve_relation_edge_events_from_extraction(
    db: Any, state: Any, extracted: Any,
) -> list[dict[str, Any]]:
    """#633 结算口真入口（resolve_credit_events_from_extraction 先例）。

    消费 extractor delta 的 ``relation_edge_events`` section，经 record_relation_edge_event
    唯一写口当场落库（TD-1）；尊重调用方事务（apply_score_extraction atomic 内）。
    类目 fail-closed 限大臣侧九类；坏项逐条拒收留痕（category=invalid_relation_event），
    不猜测修正；捕获为空时零事件零副作用。重复项由表 UNIQUE
    (source,target,event_kind,context,origin) 幂等吸收，重放不双记。"""
    results: list[dict[str, Any]] = []
    if not isinstance(extracted, Mapping):
        return results
    items = extracted.get("relation_edge_events")
    if not isinstance(items, list):
        return results
    turn = int(getattr(state, "turn", 0) or 0)
    for item in items:
        if not isinstance(item, Mapping):
            results.append({
                "rejected": True, "category": "invalid_shape", "item": item,
                "reason": "大臣互动项必须为对象",
            })
            continue
        try:
            results.extend(_capture_one_interaction(db, state, item, turn))
        except (TypeError, ValueError) as exc:
            results.append({
                "rejected": True, "category": "invalid_relation_event",
                "reason": str(exc), "item": dict(item),
            })
    return results
