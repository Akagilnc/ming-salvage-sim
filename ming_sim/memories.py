"""结构化结算效果摘要与历月邸报时间线读模型。"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.population_pressure import is_actual_population_transfer


def _short(text: object, limit: int = 80) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _directive_summary(text: str) -> str:
    s = re.sub(r"奉天承运皇帝诏曰[:：]?", "", text or "").strip()
    s = s.replace("钦此。", "").replace("钦此", "").strip()
    return _short(s, 80)


# ── 结构化效果摘要：从 applied（已落库增量）拼结算效果与时间线 ──

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
        if is_actual_population_transfer(t)
    ]
    if transfers:
        transfer_bits = []
        for t in transfers[:3]:
            # #649 F2：省名随 applied 记录（applier 落 region_name，真源＝regions 表）；
            # 旧留痕无此槽时退回 region_id，不炸。
            region = str(t.get("region_name") or t.get("region_id") or "")
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
    """从已落库月档逐回合抽「干了啥 + 效果」，供结局时间线 / 总结 agent。

    decree_text 取诏书摘要；extractor_output 解析后走 effect_brief 拼效果。
    #1845：章节记忆退役后，叙事优先用历月邸报正文，不再读 chapter_summary。
    """
    gazettes = {
        int(r["turn"]): r
        for r in (db.list_turn_reports() if hasattr(db, "list_turn_reports") else ())
    }
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
        gazette = gazettes.get(turn) or {}
        gazette_body = str(gazette.get("report") or gazette.get("body") or "")
        timeline.append({
            "turn": turn,
            "year": int(meta["year"]),
            "period": int(meta["period"]),
            "decree_brief": decree_brief,
            "effect_brief": effect,
            "gazette": gazette_body,
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
