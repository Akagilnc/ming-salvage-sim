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
from typing import Dict, Iterable, List, Mapping, Optional

from agno.agent import Agent

from ming_sim.agents import run_agent_text
from ming_sim.assets import strip_json_fence
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.models import GameState, reign_period_label
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


def _public_chapter_counterpart(
    items: Iterable[Mapping[str, object]],
) -> Optional[str]:
    """Return only independently public source material for a chapter write.

    A chapter body is LLM-rendered aggregate prose, so it cannot itself grant a
    reader access when the turn also contains restricted sources.  Give the
    archive writer a separate public counterpart made from the source-scoped
    turn items; the writer keeps legacy aggregate behaviour only when there
    are no source items to project.
    """
    source_items = list(items)
    items = [
        item for item in source_items
        # Archive rows are derived read-model projections, not independently
        # authorizable source material.  A chapter counterpart may aggregate
        # only the source rows that existed before either archive was written.
        if not str(item.get("source_id") or "").startswith(
            ("turn_report:", "chapter_source:", "projection:", "settlement:narrative:")
        )
    ]
    if not items:
        # ``None`` means no source snapshot exists, retaining the legacy body
        # fallback.  An empty string means this turn has only derived rows and
        # must not publish the chapter aggregate a second time.
        return "" if source_items else None
    return "\n".join(
        str(item.get("body") or item.get("title") or "")
        for item in items
        if not item.get("excluded_names")
    )


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
    # 过滤逐项拒收项（{rejected:True}）：它们是内部拒收留痕、无 title，不是成功结案/推进，
    # 不能被当成「了结局势」喊进效果摘要（cmr close-issues r2 codex）。
    closes = [c for c in (issue_summary.get("closes") or []) if isinstance(c, dict) and not c.get("rejected")]
    if closes:
        names = "、".join(_short(c.get("title"), 16) for c in closes[:3])
        parts.append(f"了结局势：{names}")
    advances = [a for a in (issue_summary.get("advances") or []) if isinstance(a, dict) and not a.get("rejected")]
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

    person_source = []
    seen_person_changes: set[str] = set()
    for source in (applied.get("applied_person_changes"), issue_summary.get("applied_person_changes")):
        if isinstance(source, list):
            for item in source:
                if not isinstance(item, dict):
                    continue
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key in seen_person_changes:
                    continue
                seen_person_changes.add(key)
                person_source.append(item)
    person_changes = [
        p for p in person_source
        if isinstance(p, dict) and not p.get("rejected")
    ]
    if person_changes:
        adjustments = [
            p for p in person_changes
            if str(p.get("动作") or p.get("action") or "") in {"任命", "调任", "易主", "册封", "行止"}
        ]
        if adjustments:
            names = "、".join(_short(p.get("name") or p.get("姓名"), 8) for p in adjustments[:3])
            parts.append(f"人事调整：{names}")
        release_markers = {"放归", "赦还", "起复", "昭雪", "夺情"}
        punishments = [
            p for p in person_changes
            if str(p.get("动作") or p.get("action") or "") == "罢黜"
            or (
                str(p.get("动作") or p.get("action") or "") == "处置"
                and str(p.get("status") or "") != "active"
                and str(p.get("reason") or p.get("derived_from") or "") not in release_markers
            )
        ]
        if punishments:
            names = "、".join(_short(p.get("name") or p.get("姓名"), 8) for p in punishments[:3])
            parts.append(f"处分：{names}")
    else:
        offices = [
            o for o in (applied.get("office_changes") or [])
            if isinstance(o, dict) and not o.get("rejected")
        ]
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

    # #649 人口守恒转移：机器面事实摘要（「某省农民流失 N 口为流民（加派）」式），
    # 单位措辞随落档 population_unit（新档 N 口／legacy N 万口）。仅作章节记忆/接口层
    # LLM 输入的事实摘要，不复活任何 UI 固定人口模板（P4/P7，#648 W1 已删者不复辟）。
    transfers = [
        t for t in (applied.get("population_transfers") or [])
        if isinstance(t, dict) and not t.get("rejected")
    ]
    if transfers:
        transfer_bits = []
        for t in transfers[:3]:
            region = str(t.get("region_id") or "")
            src_cls = str(t.get("source") or "").split("@", 1)[0]
            dst_cls = str(t.get("target") or "").split("@", 1)[0]
            reason = str(t.get("reason") or "")
            amount = t.get("amount")
            unit = str(t.get("population_unit") or "")
            qty = f"{amount}口" if unit == POPULATION_UNIT_PERSONS else f"{amount}万口"
            if reason == "回流":
                transfer_bits.append(f"{region}流民{qty}归农（{reason}）")
            else:
                transfer_bits.append(f"{region}{src_cls}流失{qty}为{dst_cls}（{reason}）")
        if transfer_bits:
            parts.append("、".join(transfer_bits))

    return "；".join(parts) or "盘面无显著结构化变化"


def build_timeline(db: GameDB, upto_turn: Optional[int] = None) -> List[Dict[str, object]]:
    """从已落库的 turn_extractions 逐回合抽「干了啥 + 效果」，供结局时间线 / 总结 agent。

    decree_text 取诏书摘要；extractor_output 解析后走 effect_brief 拼效果。
    若该回合有章节记忆（chapter_summary），优先用章节正文当叙事。
    """
    chapters = {c["turn"]: c for c in db.list_chapter_memories(upto_turn=upto_turn)}
    timeline: List[Dict[str, object]] = []
    for meta in db.list_monthly_archives():
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
    title = reign_period_label(state.year, state.period)
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

    knowledge_items = db.knowledge_items_for_turn(state.turn)
    public_body = _public_chapter_counterpart(knowledge_items)
    memory_id = db.save_chapter_memory(
        state, title=title, body=body, tags=tags,
        knowledge_items=knowledge_items,
        public_body=public_body,
        commit=False,
    )
    tlog(f"[chapter-memory] saved id={memory_id} turn={state.turn}")
    return memory_id
