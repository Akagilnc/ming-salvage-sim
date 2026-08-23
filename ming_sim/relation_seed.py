"""#638 S7：开局前奠基事件导入器（ADR 0086 机械面）。

新开档导入关系 seed＝奠基边事件（天启年间/更早的开局前时间戳）＋可选初始摘要；
导入后与游戏内事件**同一套流水与酿制**：
- 流水＝record_relation_edge_event 唯一写口（S1），UNIQUE(source,target,event_kind,
  context,origin) 天然幂等——重复导入返回原 id 零新行。
- 摘要＝relation_summaries 两段式（S5）：seed 可选初始摘要只落奠基段；近况段留空、
  last_event_id 留 0——seed 边因此仍在水位之上，该对日后首次真实月末酿制照常把
  seed 边当输入语境（collect_new_edge_events 按 id>水位收取），ADR 0086「同一套
  酿制」由此机械成立，不另立第二套 seed 酿制腿。
- 时间戳＝开局前坐标。引擎 turn 刻度以默认开局（1627.10=turn 1）为锚线性反推，
  seed 边全落非正 turn（1627.9→-1、1625.4→-30）；流水时点真源是 year/period 列。

校验一律 fail-closed 整份拒收（seed 文档是人工史料素材，坏行不静默半导入，
ADR 0005 响亮失败）；语境/来源零改字存储（#633 F1 同一纪律，ADR 0142）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ming_sim.constants import DEFAULT_OPENING_PERIOD, DEFAULT_OPENING_YEAR
from ming_sim.paths import bundled_path
from ming_sim.relation_brew import merge_founding_segment, relation_dimension
from ming_sim.relations import validate_edge_kind

SEED_DOC_PARTS = ("content", "relation_seed.json")


def pregame_turn(year: int, period: int) -> int:
    """开局前时间戳 → 引擎 turn 刻度（≤0；与 load_state start_ym 同一映射式）。

    开局本身＝turn 1（1627.10）；本式减一格使 1627.9→0 的前一格为 -1……即任何
    早于默认开局的月份落非正 turn，与游戏内回合（≥1）机械可分。start_ym 后移的
    新开档下个别 seed turn 可为正，但流水时点真源是 year/period 列，turn 仅刻度。
    """
    y = _as_int(year, "seed 时间戳年份")
    m = _as_int(period, "seed 时间戳月份")
    if not 1 <= m <= 12:
        raise ValueError(f"seed 时间戳月份非法（须 1..12）：{period!r}")
    return (y - DEFAULT_OPENING_YEAR) * 12 + (m - DEFAULT_OPENING_PERIOD)


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}必须为整数，得 {value!r}")
    return int(value)


def _non_empty_str(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须为字符串，得 {type(value).__name__}")
    # strip 只作非空谓词；存储值原样（含首尾空白与换行，零归一零 clamp）。
    if not value.strip():
        raise ValueError(f"{label}不能为空")
    return value


def _identifier(value: Any, label: str) -> str:
    identifier = _non_empty_str(value, label)
    if identifier != identifier.strip():
        raise ValueError(f"{label}不得含首尾空白")
    return identifier


def validate_seed_document(
    doc: Any, *, opening_year: int, opening_period: int
) -> Dict[str, Any]:
    """fail-closed 校验并归一 seed 文档；任何违约整份 ValueError 拒收。

    文档形状：{"events": [...], "summaries": [...]}（events 必须为非空列表，
    summaries 可缺省为空表）。events 项＝有向对（source/target）＋受控词表
    event_kind＋一句故事级语境 context＋origin 回指＋开局前时间戳 year/period
    （严格早于开局）＋字面布尔 evidence。summaries
    项＝关系对＋founding_lines 字符串列表（奠基段初始素材）。"""
    if not isinstance(doc, dict):
        raise ValueError(f"seed 文档顶层必须是 object，得 {type(doc).__name__}")
    opening = (_as_int(opening_year, "开局年份"), _as_int(opening_period, "开局月份"))

    if "events" not in doc:
        raise ValueError("seed 文档必须包含 events")
    raw_events = doc["events"]
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError("seed 文档 events 必须是非空列表")
    events: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_events):
        if not isinstance(item, dict):
            raise ValueError(f"seed events[{index}] 必须是 object")
        source = _identifier(item.get("source"), f"seed events[{index}].source")
        target = _identifier(item.get("target"), f"seed events[{index}].target")
        if source == target:
            raise ValueError(f"seed events[{index}] 有向对两端不得相同：{source!r}")
        kind = validate_edge_kind(item.get("event_kind"))
        context = _non_empty_str(item.get("context"), f"seed events[{index}].context")
        origin = _non_empty_str(item.get("origin"), f"seed events[{index}].origin")
        evidence = item.get("evidence")
        if not isinstance(evidence, bool):
            raise ValueError(f"seed events[{index}].evidence 必须是布尔值")
        year = _as_int(item.get("year"), f"seed events[{index}].year")
        period = _as_int(item.get("period"), f"seed events[{index}].period")
        if year < 1:
            raise ValueError(f"seed events[{index}].year 非法（须 >= 1）：{year!r}")
        if not 1 <= period <= 12:
            raise ValueError(f"seed events[{index}].period 非法（须 1..12）：{period!r}")
        if (year, period) >= opening:
            raise ValueError(
                f"seed events[{index}] 时间戳必须早于开局"
                f"（得 {year}.{period}，开局 {opening[0]}.{opening[1]}）"
            )
        events.append({
            "source": source,
            "target": target,
            "event_kind": kind,
            "context": context,
            "origin": origin,
            "evidence": evidence,
            "year": year,
            "period": period,
            "turn": pregame_turn(year, period),
        })

    # 流水 id 是“最近事件”的既有读序；稳定排序既按史时写入，也保留同月素材次序。
    events.sort(key=lambda event: (event["year"], event["period"]))

    raw_summaries = doc.get("summaries", [])
    if not isinstance(raw_summaries, list):
        raise ValueError("seed 文档 summaries 必须是列表")
    summaries: List[Dict[str, Any]] = []
    summary_pairs = set()
    for index, item in enumerate(raw_summaries):
        if not isinstance(item, dict):
            raise ValueError(f"seed summaries[{index}] 必须是 object")
        source = _identifier(item.get("source"), f"seed summaries[{index}].source")
        target = _identifier(item.get("target"), f"seed summaries[{index}].target")
        if source == target:
            raise ValueError(f"seed summaries[{index}] 有向对两端不得相同：{source!r}")
        pair = (source, target)
        if pair in summary_pairs:
            raise ValueError(f"seed summaries[{index}] 有向对重复：{source!r}→{target!r}")
        summary_pairs.add(pair)
        lines = item.get("founding_lines", [])
        if not isinstance(lines, list) or any(not isinstance(x, str) for x in lines):
            raise ValueError(f"seed summaries[{index}].founding_lines 必须是字符串列表")
        summaries.append({
            "source": source,
            "target": target,
            "dimension": relation_dimension(source, target),
            "founding_lines": list(lines),
        })

    return {"events": events, "summaries": summaries}


def load_bundled_seed_document() -> dict:
    """读取必需的 bundled seed 文档；缺失或损坏时响亮失败。"""
    path = Path(bundled_path(*SEED_DOC_PARTS))
    return json.loads(path.read_text(encoding="utf-8"))


def import_relationship_seed(
    db: Any, doc: Any, *, opening_year: int, opening_period: int
) -> Dict[str, Any]:
    """导入一份 seed 文档（校验后的机械落库）；重复导入幂等不双写。

    边走 record_relation_edge_event 唯一写口（显式 turn/year/period 覆盖）；
    摘要走 apply_seed_founding_segment 窄写口（只落奠基段、近况段留空、水位留 0）。
    返回机械报告：events_imported/events_total/summaries_written。"""
    validated = validate_seed_document(
        doc, opening_year=opening_year, opening_period=opening_period
    )
    count_before = int(
        db.conn.execute("SELECT COUNT(*) AS c FROM relation_edge_events").fetchone()["c"]
    )
    for event in validated["events"]:
        db.record_relation_edge_event(
            source=event["source"],
            target=event["target"],
            event_kind=event["event_kind"],
            context=event["context"],
            origin=event["origin"],
            evidence=event["evidence"],
            turn=event["turn"],
            year=event["year"],
            period=event["period"],
        )
    count_after = int(
        db.conn.execute("SELECT COUNT(*) AS c FROM relation_edge_events").fetchone()["c"]
    )
    summaries_written = 0
    for summary in validated["summaries"]:
        existing = db.get_relation_summary(summary["source"], summary["target"])
        if existing is None:
            db.apply_seed_founding_segment(
                source=summary["source"],
                target=summary["target"],
                dimension=summary["dimension"],
                founding_segment=merge_founding_segment("", summary["founding_lines"]),
            )
            summaries_written += 1
    return {
        "events_imported": count_after - count_before,
        "events_total": len(validated["events"]),
        "summaries_written": summaries_written,
    }


def import_bundled_relationship_seed(
    db: Any, *, opening_year: int, opening_period: int
) -> Dict[str, Any]:
    """新开档入口：读取必需的 bundled seed 并导入。"""
    doc = load_bundled_seed_document()
    return import_relationship_seed(
        db, doc, opening_year=opening_year, opening_period=opening_period
    )
