"""结算 payload 的请旨解析与批红选项校验。请旨来自逐旨／世界段推演，不从邸报抽取。"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Dict, List

from ming_sim.models import effect_dict_has_work

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState

# 逐旨／世界段预推的请旨机标；不解析邸报正文。
# 只匹配显式机标本体；邻接 whitespace 属原文，不得一并消费（P6 / #671 / ADR 0142）
_DECISION_RE = re.compile(r"<<DECISION>>\s*(\{.*?\})\s*<<END>>", re.DOTALL)


def decision_prompt_contract() -> str:
    """Explicit question transport shared by decree and world producers."""
    return (
        '需要皇帝裁决时，在问处输出 <<DECISION>>'
        '{"title":"请旨标题","context":"请旨全文","options":'
        '[{"label":"拟批","hint":"拟办说明"},{"label":"另一拟批","hint":"说明"}]}'
        '<<END>>，随后停笔；问后内容不属于本段。'
        'title/context/label/hint 是原文字符串。'
        '关联事件可显式交 event_id，无事件的来源可交 origin_ref。'
    )


def bind_decision_options(options: object) -> Dict[str, Dict[str, object]]:
    """Bind verbatim labels to stored options, rejecting ambiguous decisions."""
    bound: Dict[str, Dict[str, object]] = {}
    if not isinstance(options, list):
        raise ValueError("decision options 须为 list")
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("decision option 须为 object")
        label = str(option.get("label") or "")
        if not label.strip() or label in bound:
            raise ValueError(f"decision option label 为空或重复：{label!r}")
        bound[label] = option
    return bound


def parse_decision_blocks(text: str) -> List[Dict[str, object]]:
    """读取世界段请旨机标中的决策列表，不改写原文。

    每块须含 title/context/options（每项 label + 可选 hint）。
    解析失败的块忽略；已形成的请旨与拟批原样保留。
    """
    decisions: List[Dict[str, object]] = []
    for m in _DECISION_RE.finditer(text or ""):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            from ming_sim.audience_night import write_audience_error_pack
            pack = write_audience_error_pack(kind="decision_admission", message=str(exc),
                detail={"block_span": m.span(), "input": m.group(1)}, exc=exc)
            logger.exception("decision block rejected diagnostic=%s", pack)
            continue
        if not isinstance(obj, dict):
            continue
        title = str(obj.get("title") or "")
        raw_opts = obj.get("options")
        if not title.strip() or not isinstance(raw_opts, list):
            continue
        options: List[Dict[str, object]] = []
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            label = str(o.get("label") or "")
            if not label.strip():
                continue
            # #1847 N11：请旨选项只保留 label/hint；旧 season-option 执行载荷退役。
            options.append({
                "label": label,
                "hint": str(o.get("hint") or ""),
            })
        try:
            bind_decision_options(options)
        except ValueError as exc:
            from ming_sim.audience_night import write_audience_error_pack
            pack = write_audience_error_pack(kind="decision_admission", message=str(exc),
                detail={"block_span": m.span(), "input": m.group(1)}, exc=exc)
            logger.exception("decision block rejected diagnostic=%s", pack)
            continue
        if len(options) < 2:  # 至少给 2 个选项才算有效抉择
            continue
        decision = {
            "title": title,
            "context": str(obj.get("context") or ""),
            "options": options,
        }
        explicit_event_id = str(obj.get("event_id") or "").strip()
        origin_ref = str(obj.get("origin_ref") or "").strip()
        event_id = explicit_event_id or origin_ref
        if event_id:
            decision["event_id"] = event_id
        # 只在 id 来自 origin_ref 时留下该键。世界请旨钉定就地排除它；
        # 显式 event_id 的块与原先一样只有 event_id。
        if origin_ref and not explicit_event_id:
            decision["origin_ref"] = origin_ref
        decisions.append(decision)
    return decisions


def list_due_commitments(db: GameDB, state: GameState) -> List[Dict[str, object]]:
    """到期的 form③ 一次性承诺供邸报作者读取；不自动结案。"""
    rows = db.conn.execute(
        """
        SELECT * FROM issues
        WHERE status='active'
          AND commitment_kind != ''
          AND end_turn > 0
          AND end_turn <= ?
        ORDER BY id
        """,
        (int(state.turn),),
    ).fetchall()
    due_commitments: List[Dict[str, object]] = []
    from ming_sim.staged_commitment import should_skip_form3_due_for_staged
    for row in rows:
        if effect_dict_has_work(row["ongoing_effects"]):
            continue
        # #620：仅段派生 end_turn 改道 next_audience_todos；独立 end_turn 待裁保留 form③
        # （不停轮仅约束分段路径，0074/0076）。
        stages_raw = row["stages_json"]
        end_turn_val = int(row["end_turn"] or 0)
        if should_skip_form3_due_for_staged(stages_raw, end_turn_val):
            continue
        due_commitments.append({
            "entry_kind": "due_commitment",
            "issue_id": int(row["id"]),
            "title": str(row["title"] or ""),
            # Free stage prose: full text (P6); no fixed-length clip.
            "content": str(row["stage_text"] or row["title"] or ""),
            "origin_kind": str(row["origin_kind"] or ""),
            "origin_ref": str(row["origin_ref"] or ""),
            "turn_issued": int(row["origin_turn"] or 0),
            "due_turn": int(row["end_turn"] or 0),
            "progress": "无持续效果，期限届满。",
            "review_reason": "到期待裁：未来一次性承诺已到期，请提到皇帝面前定夺，不得自动结案。",
        })
    return due_commitments
