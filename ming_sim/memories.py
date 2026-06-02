"""章节记忆：把每回合的诏书 + 月末邸报 + 落库数值浓缩成一段叙事章节，落 event_memories
（event_type='chapter_summary'）。章节记忆取代旧的多主体原子事件卡，统一接管：
- 大臣对话「近来朝局」检索（registry）
- 月末推演历史脉络注入（simulation 的 relevant_memories）
- 结局总结的全程素材（国史编纂官读全部章节）

每回合一条，importance=5 永久保留。L5（依赖 agents/db/models）。
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from agno.agent import Agent

from ming_sim.agents import run_agent_text
from ming_sim.assets import strip_json_fence
from ming_sim.constants import TURN_UNIT
from ming_sim.db import GameDB
from ming_sim.models import GameState
from ming_sim.token_stats import tlog


def _short(text: object, limit: int = 80) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _parse_chapter_output(raw: str) -> tuple[str, List[str]]:
    """解析章节 agent 的 {body, tags} JSON。

    铁律不抛断：解析失败就把整段原文当 body、tags 空。tags 去重、限长、限 16 个。
    """
    text = strip_json_fence(raw).strip()
    data: object = None
    try:
        data = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(text[start : end + 1])
            except Exception:
                data = None
    if not isinstance(data, dict):
        # 非 JSON：原样当正文
        return text, []
    body = str(data.get("body") or "").strip()
    tags: List[str] = []
    raw_tags = data.get("tags")
    if isinstance(raw_tags, list):
        for t in raw_tags:
            s = str(t).strip()[:40]
            if s and s not in tags:
                tags.append(s)
    return body, tags[:16]


def _directive_summary(text: str) -> str:
    s = re.sub(r"奉天承运皇帝诏曰[:：]?", "", text or "").strip()
    s = s.replace("钦此。", "").replace("钦此", "").strip()
    return _short(s, 80)


# ── 结构化效果摘要：从 applied（已落库增量）拼一句「本月效果」，喂章节 agent + 时间线兜底 ──

def effect_brief(applied: Dict[str, object]) -> str:
    """把本回合落库的关键增量拼成一句话效果摘要（不调 LLM）。"""
    parts: List[str] = []
    md = applied.get("metric_delta") or {}
    metric_bits = []
    for key in ("国库", "内库", "民心", "皇威"):
        v = md.get(key)
        if not v:
            continue
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv:
            metric_bits.append(f"{key}{'+' if iv > 0 else ''}{iv}")
    if metric_bits:
        parts.append("、".join(metric_bits))

    issue_summary = applied.get("issue_summary") or {}
    closes = [c for c in (issue_summary.get("closes") or []) if isinstance(c, dict)]
    if closes:
        names = "、".join(_short(c.get("title"), 16) for c in closes[:3])
        parts.append(f"了结局势：{names}")
    advances = [a for a in (issue_summary.get("advances") or []) if isinstance(a, dict)]
    if advances:
        names = "、".join(_short(a.get("title"), 16) for a in advances[:3])
        parts.append(f"推进局势：{names}")

    # 建筑成就：局势结案落地的建筑新建/扩建/废止（埋在 closes[].building_ops）。
    built: List[str] = []
    upgraded: List[str] = []
    razed: List[str] = []
    for c in closes:
        for op in c.get("building_ops") or []:
            if not isinstance(op, dict):
                continue
            action = str(op.get("action") or "")
            if action == "create":
                built.append(_short(op.get("name"), 12))
            elif action == "modify":
                ch_names = [
                    str(x.get("label") or x.get("field"))
                    for x in (op.get("changes") or []) if isinstance(x, dict)
                ]
                name = _short(c.get("title"), 12)
                if any(lbl == "等级" for lbl in ch_names):
                    upgraded.append(name)
            elif action == "remove" and op.get("removed"):
                razed.append(_short(op.get("building_id"), 16))
    if built:
        parts.append(f"建成：{'、'.join(b for b in built if b)[:60]}")
    if upgraded:
        parts.append(f"扩建提级：{'、'.join(u for u in upgraded if u)[:60]}")
    if razed:
        parts.append(f"废止：{'、'.join(r for r in razed if r)[:60]}")

    offices = [o for o in (applied.get("office_changes") or []) if isinstance(o, dict) and not o.get("rejected")]
    if offices:
        names = "、".join(_short(o.get("name"), 8) for o in offices[:3])
        parts.append(f"人事调整：{names}")

    status_changes = [
        s for s in (applied.get("character_status_changes") or [])
        if isinstance(s, dict) and not s.get("rejected")
    ]
    if status_changes:
        names = "、".join(_short(s.get("name"), 8) for s in status_changes[:3])
        parts.append(f"处分：{names}")

    return "；".join(parts) or "盘面无显著结构化变化"


def build_timeline(db: GameDB, upto_turn: Optional[int] = None) -> List[Dict[str, object]]:
    """从已落库的 turn_extractions 逐回合抽「干了啥 + 效果」，供结局时间线 / 总结 agent。

    decree_text 取诏书摘要；extractor_output 解析后走 effect_brief 拼效果。
    若该回合有章节记忆（chapter_summary），优先用章节正文当叙事。
    """
    chapters = {c["turn"]: c for c in db.list_chapter_memories(upto_turn=upto_turn)}
    timeline: List[Dict[str, object]] = []
    for meta in db.list_archived_turns():
        turn = int(meta["turn"])
        if upto_turn is not None and turn > upto_turn:
            continue
        ext = db.get_turn_extraction(turn)
        decree_brief = ""
        effect = ""
        if ext:
            decree_brief = _directive_summary(str(ext.get("decree_text") or ""))
            raw_out = ext.get("extractor_output")
            applied_like = _coerce_extractor_output(raw_out)
            if applied_like:
                effect = effect_brief(applied_like)
        ch = chapters.get(turn)
        timeline.append({
            "turn": turn,
            "year": int(meta["year"]),
            "period": int(meta["period"]),
            "decree_brief": decree_brief,
            "effect_brief": effect,
            "chapter": (ch["body"] if ch else "") or (ch["title"] if ch else ""),
        })
    return timeline


def _coerce_extractor_output(raw: object) -> Dict[str, object]:
    """extractor_output 可能是 dict 或 JSON 字符串（get_turn_extraction 解析失败时回字符串）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


# ── 章节记忆生成（LLM 每回合浓缩一段叙事） ──

def record_chapter_memory(
    agent: Agent,
    db: GameDB,
    state: GameState,
    decree_text: str,
    narrative: str,
    applied: Dict[str, object],
) -> int:
    """调章节记忆 agent 把本回合浓缩成一段叙事章节，落 event_memories。

    失败降级：直接用 effect_brief + 邸报首段拼一段保底章节（铁律：不抛断游戏）。
    返回 memory_id（0=未落库）。
    """
    title = f"崇祯{state.year}年{state.period}{TURN_UNIT}"
    effect = effect_brief(applied)
    body = ""
    tags: list[str] = []
    try:
        payload = {
            "turn": {"year": state.year, "period": state.period, "turn": state.turn},
            "title": title,
            "decree_summary": _directive_summary(decree_text),
            "narrative": narrative,
            "effect_brief": effect,
            "instruction": (
                "把本月朝局浓缩成一段连贯叙事章节（150 字内），"
                "点明本月皇帝做了什么、引出什么效果、留下什么暗流，史笔笔法，不分点不列数值表；"
                "再抽出本月涉及的人物/地点/派系/事件动作召回标签。"
                "只输出 {\"body\":..., \"tags\":[...]} JSON。"
            ),
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
        tlog(f"[chapter-memory/INPUT] turn={state.turn} ({len(payload_json)}字)")
        raw = run_agent_text(agent, payload_json, tag="chapter-memory").strip()
        tlog(f"[chapter-memory/OUTPUT] turn={state.turn} ({len(raw)}字):\n{raw}")
        body, tags = _parse_chapter_output(raw)
    except Exception as exc:
        tlog(f"[chapter-memory] LLM 失败，走保底：{exc}")

    if not body:
        head = _short(narrative, 100)
        body = f"本月：{effect}。{head}".strip("。") + "。"

    memory_id = db.save_chapter_memory(state, title=title, body=body, tags=tags)
    tlog(f"[chapter-memory] saved id={memory_id} turn={state.turn}")
    return memory_id
