"""关系摘要层 S5：月末增量重酿腿（#636，ADR 0080/0083 一脉）。

两段式摘要＝奠基段（机械保留、只增不改）＋近况段（每次增量重酿整段重写）。
本模块只负责选中判据、酿制输入/输出契约与持久化编排；不解析 LLM 自由散文的
语义（ADR 0142）——结构化后果只走显式 JSON 契约通道；对产出零裁剪零 clamp
（庭裁 r1 F2），长度约束只走 prompt 正向输入契约。

编排约束：
- 选中判据＝该关系有未酿新边事件（id > 水位）∨ 存在 pending 失败（庭裁 r1 F1）。
- 输入依赖边界（ID-10）：本月边事件集定型后方启酿；腿内批内条目无依赖必并行（P5）。
- 单条失败降级：保旧摘要＋事件已在流水，进持久 pending-backlog，不阻塞结算。
- 成功路径＝摘要写入与 pending 清除同一 DB 事务原子落定（庭裁 r2 F1）。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from ming_sim.agents import parse_agent_json
from ming_sim.models import GameState
from ming_sim.relations import EMPEROR_NODE
from ming_sim.token_stats import tlog

DIMENSION_JUNXIN = "君臣"
DIMENSION_DACHEN = "大臣"

# 酿制输出契约字段（显式结构化契约，非散文解析）。
FOUNDINGS_KEY = "new_foundings"
RECENT_KEY = "recent_segment"


def relation_dimension(source: str, target: str) -> str:
    """维度标记：任一端为皇帝节点即君臣边，否则大臣边。"""
    return DIMENSION_JUNXIN if EMPEROR_NODE in (source, target) else DIMENSION_DACHEN


def select_brew_targets(db: Any) -> List[Dict[str, Any]]:
    """选中判据（庭裁 r1 F1）：未酿新边事件 ∨ pending 失败。

    「新」以该关系摘要的 last_event_id 水位计——崩溃缝里已落库但未酿的事件
    （庭裁 r3 F1② fresh claim→durable pending 缝）重启后仍是新事件，仍被选中。
    既无新事件又无 pending 的关系不入选（TD-3 无事不变）。"""
    summaries = {
        (row["source"], row["target"]): row for row in db.get_relation_summaries()
    }
    pending = {
        (row["source"], row["target"]): row for row in db.get_relation_brew_pending()
    }
    latest_event_id: Dict[Tuple[str, str], int] = {}
    for row in db.conn.execute(
        "SELECT source, target, MAX(id) AS max_id FROM relation_edge_events "
        "GROUP BY source, target"
    ).fetchall():
        latest_event_id[(row["source"], row["target"])] = int(row["max_id"])

    targets: List[Dict[str, Any]] = []
    for pair in sorted(set(latest_event_id) | set(pending)):
        summary = summaries.get(pair)
        watermark = int(summary["last_event_id"]) if summary is not None else 0
        has_new_events = latest_event_id.get(pair, 0) > watermark
        has_pending = pair in pending
        if not (has_new_events or has_pending):
            continue
        targets.append({
            "source": pair[0],
            "target": pair[1],
            "dimension": relation_dimension(pair[0], pair[1]),
            "summary": summary,
            "watermark": watermark,
            "has_new_events": has_new_events,
            "has_pending": has_pending,
        })
    return targets


def collect_new_edge_events(db: Any, *, source: str, target: str, watermark: int) -> List[Dict[str, Any]]:
    """水位之上的新边事件（TD-4：重酿输入必含新事件；翻转可回溯的依据）。"""
    return [
        row
        for row in db.get_relation_edge_events(source=source, target=target)
        if int(row["id"]) > int(watermark)
    ]


def build_brew_input(
    *,
    source: str,
    target: str,
    dimension: str,
    year: int,
    period: int,
    summary: Optional[Dict[str, Any]],
    new_events: List[Dict[str, Any]],
    has_pending: bool,
) -> Dict[str, Any]:
    """单条关系的酿制输入（旧摘要＋新边事件＋当前年月，ADR 0083 口径）。"""
    return {
        "source": source,
        "target": target,
        "dimension": dimension,
        "year": int(year),
        "period": int(period),
        "founding_segment": str(summary["founding_segment"]) if summary else "",
        "recent_segment": str(summary["recent_segment"]) if summary else "",
        "new_events": [
            {
                "event_kind": event["event_kind"],
                "context": event["context"],
                "origin": event["origin"],
                "year": int(event["year"]),
                "period": int(event["period"]),
            }
            for event in new_events
        ],
        "has_pending_failure": bool(has_pending),
    }


def render_brew_user_payload(brew_input: Dict[str, Any]) -> str:
    """酿制 user payload：JSON 序列化的确定性输入（供 extractor 式缓存前缀复用）。"""
    return json.dumps(brew_input, ensure_ascii=False, sort_keys=False)


def parse_brew_output(raw: str, stage: str = "关系酿制") -> Dict[str, Any]:
    """酿制输出契约：{"new_foundings": [...], "recent_segment": "..."}。

    只验形不验义、零长度管辖（庭裁 r1 F2/r3 F2）：recent_segment 原样存储，
    不截断不 clamp；new_foundings 逐句原样追加。"""
    parsed = parse_agent_json(raw, stage)
    if not isinstance(parsed, dict):
        raise ValueError(f"{stage}: 酿制输出顶层不是 object")
    recent = parsed.get(RECENT_KEY)
    if not isinstance(recent, str):
        raise ValueError(f"{stage}: {RECENT_KEY} 缺失或不是字符串")
    foundings = parsed.get(FOUNDINGS_KEY, [])
    if not isinstance(foundings, list) or any(
        not isinstance(line, str) for line in foundings
    ):
        raise ValueError(f"{stage}: {FOUNDINGS_KEY} 必须是字符串列表")
    return {FOUNDINGS_KEY: list(foundings), RECENT_KEY: recent}


def merge_founding_segment(old_founding: str, new_foundings: List[str]) -> str:
    """奠基段机械只增不改（ID-9）：旧字节永不丢不改，新奠基句原样追加。

    与既有奠基句逐字相同的行不再重复追加（补酿不重复记账，覆盖式幂等）。"""
    lines = [line for line in old_founding.split("\n") if line]
    for line in new_foundings:
        text = str(line).strip()
        if not text:
            continue
        if text not in lines:
            lines.append(text)
    return "\n".join(lines)


def run_month_end_relation_brew(
    db: Any,
    state: GameState,
    brew_fn: Callable[[str], str],
    *,
    max_workers: int = 4,
    parallel: bool = True,
) -> Dict[str, Any]:
    """月末增量重酿腿。

    brew_fn(rendered_payload) -> LLM 原始文本（生产＝run_agent_text 闭包；
    测试注入确定性假手）。批内条目间无依赖必并行（P5）；单条失败降级进
    pending-backlog、保旧摘要，绝不向上抛（不阻塞结算）；返回机械报告。"""
    turn, year, period = int(state.turn), int(state.year), int(state.period)
    targets = select_brew_targets(db)
    report: Dict[str, Any] = {
        "selected": len(targets),
        "brewed": [],
        "degraded": [],
        "skipped_events": 0,
    }
    if not targets:
        return report

    # 输入先串行备好（纯计算、确定性，不含 LLM 调用），再批内并行酿制。
    jobs: List[Dict[str, Any]] = []
    for item in targets:
        new_events = collect_new_edge_events(
            db, source=item["source"], target=item["target"],
            watermark=item["watermark"],
        )
        jobs.append({
            **item,
            "new_events": new_events,
            "input": build_brew_input(
                source=item["source"], target=item["target"],
                dimension=item["dimension"], year=year, period=period,
                summary=item["summary"], new_events=new_events,
                has_pending=item["has_pending"],
            ),
        })

    def _brew_one(job: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[Exception]]:
        try:
            raw = brew_fn(render_brew_user_payload(job["input"]))
            return job, parse_brew_output(raw), None
        except Exception as exc:  # noqa: BLE001 — 单条失败降级，不上抛
            return job, None, exc

    if parallel and len(jobs) > 1:
        workers = max(1, min(int(max_workers), len(jobs)))
        tlog(f"[relation-brew] 批内并行酿制 {len(jobs)} 条关系（workers={workers}）")
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="relation-brew") as pool:
            outcomes = list(pool.map(_brew_one, jobs))
    else:
        outcomes = [_brew_one(job) for job in jobs]

    for job, parsed, exc in outcomes:
        source, target = job["source"], job["target"]
        if exc is not None or parsed is None:
            reason = str(exc) if exc is not None else "空结果"
            tlog(f"[relation-brew] {source}→{target} 酿制失败降级（保旧摘要）：{reason}")
            try:
                db.mark_relation_brew_pending(
                    source=source, target=target, year=year, period=period, reason=reason,
                )
            except Exception as mark_exc:  # noqa: BLE001 — pending 未持久即崩（庭裁 r3 F1②缝）：
                # 降级标记自身失败不再上抛；该关系仍凭水位新事件判据在下次结算被选中。
                tlog(f"[relation-brew] {source}→{target} pending 标记未持久：{mark_exc}")
            report["degraded"].append({"source": source, "target": target, "reason": reason})
            continue
        # 成功路径：摘要写入＋pending 清除同事务原子落定（庭裁 r2 F1）。
        # 奠基段只增不改在此拼定；近况段覆盖式幂等；水位推进到本批最大事件 id。
        last_event_id = max(
            [int(event["id"]) for event in job["new_events"]] + [int(job["watermark"])]
        )
        try:
            db.apply_relation_brew_result(
                source=source, target=target, dimension=job["dimension"],
                founding_segment=merge_founding_segment(
                    str(job["summary"]["founding_segment"]) if job["summary"] else "",
                    parsed[FOUNDINGS_KEY],
                ),
                recent_segment=parsed[RECENT_KEY],
                last_event_id=last_event_id,
                turn=turn, year=year, period=period,
            )
        except Exception as apply_exc:  # noqa: BLE001 — 落定失败同走单条降级，不上抛
            tlog(f"[relation-brew] {source}→{target} 落定失败降级（保旧摘要）：{apply_exc}")
            try:
                db.mark_relation_brew_pending(
                    source=source, target=target, year=year, period=period,
                    reason=str(apply_exc),
                )
            except Exception as mark_exc:  # noqa: BLE001 — 同上，水位判据兜底
                tlog(f"[relation-brew] {source}→{target} pending 标记未持久：{mark_exc}")
            report["degraded"].append(
                {"source": source, "target": target, "reason": str(apply_exc)}
            )
            continue
        report["brewed"].append({"source": source, "target": target})
        tlog(f"[relation-brew] {source}→{target} 酿制落定（pending 同事务清除）")
    return report
