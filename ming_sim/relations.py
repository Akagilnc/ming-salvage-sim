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
    "兑现所托": "emperor_to_person",
    "撑腰": "emperor_to_person",
    "知遇": "emperor_to_person",
    "辜负": "person_to_emperor",
    "弃卒保车": "person_to_emperor",
}

_ROUND_RE = re.compile(r"(?:^|[|/:; ])round[=: -](\d+)(?:$|[|/:; ])", re.I)
_TURN_RE = re.compile(r"(?:^|[|/:; ])turn[=: -](\d+)(?:$|[|/:; ])", re.I)


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
