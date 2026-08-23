"""派系态势摘要层 S6：涉派事件驱动的聚合视图（#637，ADR 0084 一脉）。

边流之上的派系级定性聚合视图：本月有涉派边事件才重酿该派，与关系摘要同批
（ID-10）。本模块只负责涉派目标集合的 canonical 投影、选中判据、酿制输入/输出
契约；持久化与编排复用 #636 已落机制（庭裁 r1 F2：同一 claim/watermark/apply+clear
所有者、同一受管 brew 批次），不建第二套。

三不碰红线（ADR 0084）：不写 factions 真源数值、不动满意度/影响力、不建认同度；
零数值强度字段（P4/ADR 0083 一脉）。

庭裁 r1 F1：涉派目标集合唯一化——「该派」判定＝既有人物党籍→canonical 派系投影
（characters.faction 经现行 canonical 归一到 factions 表现存派系集合；faction 值在
factions 表外→该事件不入任何派系视图，不猜不建新映射表）。涉派事件＝边任一端
人物党籍归一后命中该派；皇帝端不投影（皇帝不是 characters 行）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ming_sim.exceptions import LLMContractError

# 派系工作项身份（relation_brew_pending.item_kind；庭裁 r1 F2 泛化身份）。
KIND_FACTION = "派系"
# 酿制输入 view 标记（生产 _brew_fn 据此分派 agent；同批单编排腿不变）。
VIEW_FACTION_STANCE = "faction_stance"
# 酿制输出契约字段（显式结构化契约，非散文解析；ADR 0142）。
STANCE_KEY = "stance_segment"


def project_character_factions(db: Any) -> Dict[str, str]:
    """canonical 党籍投影（庭裁 r1 F1，纯投影、不持久化任何映射表）。

    characters.faction ∩ factions 表现存派系集合：命中者入映射；表外党籍
    （中宫/后金/嫔妃等真实种子）与皇帝节点不入。每次现算——党籍/派系集合
    随引擎演化，投影永远对表当前态。"""
    in_table = {
        row["name"] for row in db.conn.execute("SELECT name FROM factions").fetchall()
    }
    projection: Dict[str, str] = {}
    for row in db.conn.execute("SELECT name, faction FROM characters").fetchall():
        faction = row["faction"]
        if faction in in_table:
            projection[row["name"]] = faction
    return projection


def select_faction_brew_targets(db: Any, *, year: int, period: int) -> List[Dict[str, Any]]:
    """选中判据（庭裁 r1 F2，与 #636 select_brew_targets 同构）：该 settled 年月
    涉派新事件（id 在该派态势摘要水位之上）∨ 该派 durable pending。

    「本月新增」双条件与关系腿同一口径：历史月份的旧事件不得把无本月新事件的
    派选中；既无本月新涉派事件又无 pending 的派不入选（无事字节不变）。两端
    不同派均入选、两端同派去重（GROUP 语义由 max 归并保证）。"""
    projection = project_character_factions(db)
    summaries = {
        row["faction"]: row for row in db.get_faction_stance_summaries()
    }
    pending = {
        row["faction"]: row for row in db.get_faction_brew_pending()
    }
    latest_event_id: Dict[str, int] = {}
    for row in db.conn.execute(
        "SELECT source, target, MAX(id) AS max_id FROM relation_edge_events "
        "WHERE year = ? AND period = ? GROUP BY source, target",
        (int(year), int(period)),
    ).fetchall():
        max_id = int(row["max_id"])
        for endpoint in (row["source"], row["target"]):
            faction = projection.get(endpoint)
            if faction is not None and max_id > latest_event_id.get(faction, 0):
                latest_event_id[faction] = max_id

    targets: List[Dict[str, Any]] = []
    for faction in sorted(set(latest_event_id) | set(pending)):
        summary = summaries.get(faction)
        watermark = int(summary["last_event_id"]) if summary is not None else 0
        has_new_events = latest_event_id.get(faction, 0) > watermark
        has_pending = faction in pending
        if not (has_new_events or has_pending):
            continue
        targets.append({
            "faction": faction,
            "summary": summary,
            "watermark": watermark,
            "has_new_events": has_new_events,
            "has_pending": has_pending,
        })
    return targets


def collect_new_edge_events_for_faction(
    db: Any, *, faction: str, watermark: int
) -> List[Dict[str, Any]]:
    """水位之上的涉派新边事件（TD-4 同构：重酿输入必含新事件；翻转可回溯）。

    任一端 canonical 投影命中该派即涉派（庭裁 r1 F1：任一端口径，含皇帝端
    另一端命中的君臣边）。返回行附带 source_faction/target_faction 现算投影
    （皇帝端与表外党籍显式 None，不猜不建映射）。"""
    projection = project_character_factions(db)
    enriched: List[Dict[str, Any]] = []
    for row in db.get_relation_edge_events():
        if int(row["id"]) <= int(watermark):
            continue
        if faction not in (projection.get(row["source"]), projection.get(row["target"])):
            continue
        enriched_row = dict(row)
        enriched_row["source_faction"] = projection.get(row["source"])
        enriched_row["target_faction"] = projection.get(row["target"])
        enriched.append(enriched_row)
    return enriched


def build_faction_brew_input(
    *,
    faction: str,
    year: int,
    period: int,
    summary: Any,
    new_events: List[Dict[str, Any]],
    has_pending: bool,
    db: Any = None,
    character_factions: Any = None,
) -> Dict[str, Any]:
    """单派的酿制输入（旧态势段＋涉派新边事件＋当前年月，ADR 0083/0084 口径）。

    新增 source_faction/target_faction 纯数据字段（庭裁 r1 F1＋F2 缝合）：
    取 project_character_factions() 现算投影，皇帝端与表外党籍显式 None，不猜
    不建映射表；禁任何拼接串（ADR 0142/P6，给数据不给话术）。若调用方已通过
    collect_new_edge_events_for_faction 取数，事件行自带两字段则直接透传；
    否则若显式传入 db/character_factions 则现算，否则按 None 兜底（显式 null）。
    """
    # 现算投影（若提供）：优先显式映射，其次 db 现算；未提供则依赖事件自带或 None。
    projection: Any = None
    if character_factions is not None:
        projection = dict(character_factions)
    elif db is not None:
        projection = project_character_factions(db)
    new_events_projected: List[Dict[str, Any]] = []
    for event in new_events:
        if projection is not None:
            sf = projection.get(event["source"])
            tf = projection.get(event["target"])
        else:
            sf = event.get("source_faction") if "source_faction" in event else None
            tf = event.get("target_faction") if "target_faction" in event else None
        new_events_projected.append({
            "event_kind": event["event_kind"],
            "context": event["context"],
            "origin": event["origin"],
            "year": int(event["year"]),
            "period": int(event["period"]),
            "source": event["source"],
            "target": event["target"],
            "source_faction": sf,
            "target_faction": tf,
        })
    return {
        "view": VIEW_FACTION_STANCE,
        "faction": faction,
        "year": int(year),
        "period": int(period),
        "stance_segment": str(summary["stance_segment"]) if summary else "",
        # source/target/source_faction/target_faction 为 relation_edge_events 既有列
        # 与现算投影的只读透传（#637 缝合 P2）：context 不含参与方名字时（如收权·罢
        # 差），方向事实只能靠结构字段携带；纯数据字段，不在此拼接任何散文（ADR 0142：
        # 给数据不给话术）。皇帝端不在 characters 表→显式 null，表外党籍亦显式 null。
        "new_events": new_events_projected,
        "has_pending_failure": bool(has_pending),
    }


def parse_faction_stance_output(raw: str, stage: str = "派系态势酿制") -> Dict[str, Any]:
    """酿制输出契约：{"stance_segment": "..."}。

    与 parse_brew_output 同一严格解析边界（庭裁 Z1 同型）：raw 必须本身就是唯一、
    完整、合法的 JSON object——不做任何 fence 剥离/控制字节清洗/首对象截取等修补；
    畸形产出一律契约错拒收（LLMContractError/ValueError），沿单条降级保旧摘要与
    pending；绝不把改写/择取后的散文当模型产出落库（ADR 0142 零删改）。零长度
    管辖：stance_segment 原样存储，不截断不 clamp。"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LLMContractError(
            f"{stage} 输出不是唯一、完整、合法的 JSON object：{error}\n原始输出：{raw[:800]}"
        ) from error
    if not isinstance(parsed, dict):
        raise LLMContractError(f"{stage} 酿制输出顶层不是 object\n原始输出：{raw[:800]}")
    stance = parsed.get(STANCE_KEY)
    if not isinstance(stance, str):
        raise ValueError(f"{stage}: {STANCE_KEY} 缺失或不是字符串")
    return {STANCE_KEY: stance}
