"""#620 / ADR 0074 分段承诺载体。

一条多段里程碑 = 单一 commitment issue（stages_json）。
段到期扫描独立（与 form③ 共享谓词面、不共用其 SQL 结果集），
待裁载体改道 next_audience_todos（次回合召对待办）；
结算不停轮、不接 DECISION/AWAITING_DECISION（0074/0076）。

存储选型（本片定）：
- 段表：issues.stages_json（JSON 数组，挂在单一承诺对象上）
- 待办：next_audience_todos 表（P2 字段集）
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

ENTRY_KIND_STAGED = "staged_commitment"
TODO_STATUS_PENDING = "pending"
TODO_STATUS_CONSUMED = "consumed"
TODO_STATUS_ROLLED = "rolled"

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
    """从「三年X五年Y」文案抽出分段（scripted 捕获；禁 live-LLM 作唯一验收）。"""
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
    """Normalize structured stages payload → durable list.

    Accepts list/tuple of dicts, or a JSON array string. Non-JSON free text
    returns [] here — production CN-year capture goes through
    ``capture_commitment_stages`` (does not silently treat char-iterated strings
    as stage rows; that hole is closed in ``stages_to_json``).
    """
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
    return out


def stages_to_json(stages: object) -> str:
    """Serialize stages for durable DB write.

    Designed string surface: JSON array string is parsed, not char-iterated.
    Invalid non-empty strings raise ValueError (never silently store ``[]``).
    ``None`` / empty / ``[]`` → ``"[]"``.
    """
    if stages is None:
        return "[]"
    if isinstance(stages, str):
        text = stages.strip()
        if not text or text in ("[]", "{}"):
            return "[]"
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"stages_json 须为 JSON 数组字符串，解析失败：{text[:80]!r}"
            ) from exc
        if not isinstance(data, (list, tuple)):
            raise ValueError(
                f"stages_json 须为 JSON 数组，得 {type(data).__name__}"
            )
        if len(data) == 0:
            return "[]"
        normalized = normalize_commitment_stages(data)
        if not normalized:
            raise ValueError(
                "stages_json 无有效段（每段须 due_turn>0 与 criterion_text）"
            )
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if isinstance(stages, (list, tuple)):
        if not stages:
            return "[]"
        normalized = normalize_commitment_stages(list(stages))
        # 非空 list 归一后无有效段：与 str 支同响亮拒绝，禁静默存 []
        if not normalized:
            raise ValueError(
                "stages_json 无有效段（每段须 due_turn>0 与 criterion_text）"
            )
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    raise ValueError(f"stages_json 类型非法：{type(stages).__name__}")


# sentinel：显式 stages 字符串 json.loads 失败（与成功解析到的 None 区分）
_CAPTURE_JSON_MISS = object()


def capture_commitment_stages(
    raw: object = None,
    *,
    narrative_text: str = "",
    origin_turn: int,
) -> List[Dict[str, object]]:
    """生产捕获：结构化 stages / JSON 字符串 / 「三年X五年Y」文案 → 绝对 due 段表。

    召对 materializer 与邸报/score new_issues 共用此入口，避免 CN year 解析只停在测试。
    - 显式 stages 字段：JSON 数组优先；否则对字段文本跑 scripted 年诺解析
    - 显式 stages 字符串若 JSON-ish 坏形 → ValueError（与 stages_to_json 同响亮口径，禁静默 []）
    - 无显式 stages：对 narrative（召对正文 / stage_text）解析；≥2 段才自动落
      （对齐 AC2「三年X五年Y」，避免单次「三年后复试」误收成分段）
    """
    if raw not in (None, "", [], (), {}):
        if isinstance(raw, str):
            text = raw.strip()
            if text and text not in ("[]", "{}"):
                try:
                    data = json.loads(text)
                except (TypeError, ValueError):
                    data = _CAPTURE_JSON_MISS
                if data is not _CAPTURE_JSON_MISS:
                    # JSON 已解析：坏形响亮拒绝（同 stages_to_json），勿静默 []
                    if not isinstance(data, (list, tuple)):
                        raise ValueError(
                            f"stages 须为 JSON 数组，得 {type(data).__name__}"
                        )
                    if len(data) == 0:
                        return []
                    structured = normalize_commitment_stages(data)
                    if not structured:
                        raise ValueError(
                            "stages 无有效段（每段须 due_turn>0 与 criterion_text）"
                        )
                    return structured
                # 非 JSON：scripted 年诺；JSON-ish 起首坏串响亮拒绝
                parsed = parse_staged_year_promise(text, origin_turn=int(origin_turn))
                if parsed:
                    return parsed
                if text[:1] in "[{":
                    raise ValueError(
                        f"stages 须为 JSON 数组字符串，解析失败：{text[:80]!r}"
                    )
        else:
            # 非 str 正式面（list/dict）：与 str 支同响亮口径，勿静默 []
            # 空 list/tuple 已由入口 raw not in (…, [], ()) 排除，此处无空支
            if not isinstance(raw, (list, tuple)):
                raise ValueError(
                    f"stages 须为 JSON 数组，得 {type(raw).__name__}"
                )
            structured = normalize_commitment_stages(raw)
            if not structured:
                raise ValueError(
                    "stages 无有效段（每段须 due_turn>0 与 criterion_text）"
                )
            return structured
    narrative = str(narrative_text or "").strip()
    if narrative:
        parsed = parse_staged_year_promise(narrative, origin_turn=int(origin_turn))
        # 叙事回落仅收多段（三年X五年Y）；单段不抢 form③ 单值 end_turn 语义
        if len(parsed) >= 2:
            return parsed
    return []


def stages_source_from_issue_item(ni: Dict[str, object]) -> object:
    """Single stages key fallback for new_issues items (stages | stages_json)."""
    stages = ni.get("stages")
    if stages not in (None, "", [], (), {}):
        return stages
    return ni.get("stages_json")


def is_stage_derived_end_turn(
    stages: object,
    end_turn: int,
) -> bool:
    """True when end_turn is purely max(stages.due_turn) display-compat (no independent due)."""
    norm = normalize_commitment_stages(stages)
    if not norm:
        return False
    try:
        et = int(end_turn or 0)
    except (TypeError, ValueError):
        return False
    if et <= 0:
        return False
    return et == max(int(s["due_turn"]) for s in norm)


def should_skip_form3_due_for_staged(
    stages_raw: object,
    end_turn: int,
) -> bool:
    """form③ due_commitments 跳过面：仅段派生 end_turn 改道；独立 end_turn 待裁不吞。"""
    norm = normalize_commitment_stages(stages_raw)
    if not norm:
        return False
    try:
        et = int(end_turn or 0)
    except (TypeError, ValueError):
        et = 0
    # 无独立 end_turn：分段只走 next_audience_todos
    if et <= 0:
        return True
    # 段派生展示 end_turn：改道；显式独立 end_turn（≠ max due）：保留 form③
    return is_stage_derived_end_turn(norm, et)


def list_due_stages_for_scan(db: Any, turn: int) -> List[Dict[str, object]]:
    """段到期扫描（独立 SQL；与 form③ 共享「active 承诺 + 到期」谓词语义，不共用结果集）。

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

    待裁载体改道 next_audience_todos；不置 TurnPhase.AWAITING_DECISION，
    不写 <<DECISION>>，不停轮（0074/0076）。
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
