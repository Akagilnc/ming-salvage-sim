"""#620 / ADR 0074 分段承诺载体。

一条多段里程碑 = 单一 commitment issue（stages_json），段到期扫描写
next_audience_todos（次回合召对待办），结算不停轮、不接 DECISION/AWAITING_DECISION。

存储选型（本片定）：
- 段表：issues.stages_json（JSON 数组，挂在单一承诺对象上）
- 待办：next_audience_todos 表（P2 字段集）
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Sequence

ENTRY_KIND_STAGED = "staged_commitment"
TODO_STATUS_PENDING = "pending"

_CN_YEAR_DIGITS = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10,
}

# 「三年火器见眉目」「五年新历成」「七八年农政见效」
_STAGE_YEAR_RE = re.compile(
    r"(?P<years>[一二三四五六七八九十两〇零]+)年"
    r"(?P<body>[^，。；;、\n]*?)"
    r"(?=(?:[一二三四五六七八九十两〇零]+年)|[，。；;、\n]|$)"
)


def _cn_years_to_int(token: str) -> int:
    raw = str(token or "").strip()
    if not raw:
        raise ValueError("年数为空")
    if raw == "十":
        return 10
    if raw.startswith("十") and len(raw) == 2 and raw[1] in _CN_YEAR_DIGITS:
        return 10 + _CN_YEAR_DIGITS[raw[1]]
    if raw.endswith("十") and len(raw) == 2 and raw[0] in _CN_YEAR_DIGITS:
        return _CN_YEAR_DIGITS[raw[0]] * 10
    # 「七八」取首数（约数年取下界）
    if all(ch in _CN_YEAR_DIGITS for ch in raw):
        if len(raw) == 1:
            return _CN_YEAR_DIGITS[raw]
        if "十" not in raw:
            return _CN_YEAR_DIGITS[raw[0]]
    raise ValueError(f"无法解析年数：{raw!r}")


def parse_staged_year_promise(text: str, *, origin_turn: int) -> List[Dict[str, object]]:
    """Scripted AC2 夹具：从「三年X五年Y」文案抽出分段（禁 live-LLM 作唯一验收）。"""
    src = str(text or "").strip()
    if not src:
        return []
    stages: List[Dict[str, object]] = []
    for match in _STAGE_YEAR_RE.finditer(src):
        years_tok = match.group("years")
        body = str(match.group("body") or "").strip(" ，。；;、")
        if not body:
            continue
        try:
            years = _cn_years_to_int(years_tok)
        except ValueError:
            continue
        if years <= 0:
            continue
        origin_context = f"{years_tok}年{body}"
        stages.append({
            "stage_idx": len(stages),
            "due_turn": int(origin_turn) + years * 12,
            "criterion_text": body,
            "origin_context": origin_context,
        })
    return stages


def normalize_commitment_stages(raw: object) -> List[Dict[str, object]]:
    """Normalize stages payload → durable list[{stage_idx, due_turn, criterion_text, origin_context}]."""
    if raw in (None, "", [], ()):
        return []
    data = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text in ("[]", "{}"):
            return []
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, (list, tuple)):
        return []
    out: List[Dict[str, object]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        try:
            due_turn = int(item.get("due_turn") or 0)
        except (TypeError, ValueError):
            continue
        if due_turn <= 0:
            continue
        try:
            stage_idx = int(item.get("stage_idx", idx))
        except (TypeError, ValueError):
            stage_idx = idx
        criterion = str(
            item.get("criterion_text") or item.get("criterion") or ""
        ).strip()
        origin_context = str(
            item.get("origin_context") or item.get("origin") or criterion or ""
        ).strip()
        if not criterion and origin_context:
            criterion = origin_context
        if not criterion:
            continue
        out.append({
            "stage_idx": stage_idx,
            "due_turn": due_turn,
            "criterion_text": criterion[:200],
            "origin_context": (origin_context or criterion)[:240],
        })
    out.sort(key=lambda s: (int(s["stage_idx"]), int(s["due_turn"])))
    # re-pack stage_idx dense only when missing/duplicate? keep caller idx.
    return out


def stages_to_json(stages: Sequence[Dict[str, object]]) -> str:
    normalized = normalize_commitment_stages(list(stages))
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def list_due_stages_for_scan(db: Any, turn: int) -> List[Dict[str, object]]:
    """form③ 扫描扩段：active 分段承诺中 due_turn<=turn 的段。

    去重键在写端用 (commitment_id, stage_idx)；此处返回全部到期段候选。
    """
    rows = db.conn.execute(
        """
        SELECT id, title, stages_json, origin_ref, origin_turn, stage_text
        FROM issues
        WHERE status='active'
          AND commitment_kind != ''
          AND stages_json IS NOT NULL
          AND stages_json != ''
          AND stages_json != '[]'
        ORDER BY id
        """
    ).fetchall()
    due: List[Dict[str, object]] = []
    for row in rows:
        stages = normalize_commitment_stages(row["stages_json"])
        for stage in stages:
            if int(stage["due_turn"]) <= int(turn):
                due.append({
                    "commitment_ref": int(row["id"]),
                    "stage_idx": int(stage["stage_idx"]),
                    "due_turn": int(stage["due_turn"]),
                    "criterion_text": str(stage["criterion_text"]),
                    "origin_context": str(stage["origin_context"]),
                    "title": str(row["title"] or ""),
                    "origin_ref": str(row["origin_ref"] or ""),
                })
    return due


def write_due_staged_commitment_todos(db: Any, state: Any, *, commit: bool = True) -> int:
    """结算内确定性写入次回合召对待办。返回新写入条数。

    不置 TurnPhase.AWAITING_DECISION，不写 <<DECISION>>，不停轮。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    due_stages = list_due_stages_for_scan(db, turn)
    if not due_stages:
        return 0
    written = 0
    for item in due_stages:
        created = db.insert_next_audience_todo(
            commitment_ref=int(item["commitment_ref"]),
            stage_idx=int(item["stage_idx"]),
            due_turn=int(item["due_turn"]),
            criterion_text=str(item["criterion_text"]),
            origin_context=str(item["origin_context"]),
            status=TODO_STATUS_PENDING,
            entry_kind=ENTRY_KIND_STAGED,
            created_turn=turn,
            commit=False,
        )
        if created:
            written += 1
    if commit and written:
        db.conn.commit()
    return written
