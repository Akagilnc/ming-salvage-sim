"""#640 S9 读端交付形态＋判官读面（ID-11/ID-12；庭裁 r1-r3）。

单一 DTO、单一查询/投影核心（庭裁 r1 F2）：角色视角与全知判官机面共用
project_relation_ledger，仅授权参数 ``viewer`` 不同——``viewer=None`` 即全知
机面（权限超集），``viewer=人名`` 即角色视角（参与即知，ADR 0034）。禁平行表/
平行摘要/第二套序列化/缓存。

边界：
- 本轴只交可裁切形态；公开/风闻层的见闻裁切语义归 #472 线消费。
- 召对判官接入归 #634 线——本模块只供其读面数据，不接判官、不造第二判官。
- 本 DTO 是确定性输入投影/装配面（ADR 0143），不是玩家最终渲染面；
  摘要原文零裸露进玩家呈现的终验在呈现通道侧。

DTO 冻结白名单（庭裁 r2/r3，唯一真源在冻结票面，变更须回票庭）：
``source`` / ``target`` / ``summary`` / ``recent_context`` / ``updated_at_period``
恰此五字段。``event_kind`` / 结构键 / origin / 水位等一律名单外（TD-7 哨兵咬点）。

内容口径（ID-1/ID-11，ADR 0080）：summary＝两段式酿制摘要原文（奠基段＋近况段
零改写拼接）；recent_context＝最近原始事件语境原文＋纪年时点回指；
updated_at_period＝更新纪年语义标识（天启七年十月式，非裸 turn 数）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ming_sim.models import reign_period_label


def project_relation_ledger(db: Any, *, viewer: str | None) -> List[Dict[str, str]]:
    """按授权参数投影关系账读面（#640 单一读取接缝，庭裁 r1 F2）。

    viewer 为必填 keyword-only 参数：全知判官机面（ID-12）必须显式传
    ``viewer=None``；viewer=人名 → 角色视角，参与即知
    （边任一端为该人即可见）。空白（空串/纯空白）viewer 非法，抛 ValueError
    ——绝不静默当全知或当任意角色（fail-closed）。返回形态＝可见边的五字段
    DTO 列表，按 (source, target) 字典序稳定排序。"""
    # 授权边界 fail-closed（冻结票面“非参与者默认不可见”/ADR 0034）：仅
    # viewer is None 可进全知机面；非 None 的空白 viewer 是 malformed 授权
    # 参数，绝不静默当全知或当任意角色，直接拒绝。有效人名一律参与边过滤。
    if viewer is None:
        name = None
    else:
        name = str(viewer).strip()
        if not name:
            raise ValueError(
                "viewer 必须为 None（全知机面）或有效人名；空白授权参数拒绝（fail-closed）"
            )
    pairs = {
        (str(row["source"]), str(row["target"]))
        for row in db.get_relation_summaries()
    }
    for row in db.conn.execute(
        "SELECT DISTINCT source, target FROM relation_edge_events"
    ).fetchall():
        pairs.add((str(row["source"]), str(row["target"])))
    if name is not None:
        pairs = {pair for pair in pairs if name in pair}
    return [_relation_dto(db, source, target) for source, target in sorted(pairs)]


def _relation_dto(db: Any, source: str, target: str) -> Dict[str, str]:
    """单条关系的五字段 DTO（冻结白名单，r3；字段增删须回票庭）。

    只消费 #636 两段式存储（relation_summaries）与边事件流水，不建平行表。
    摘要两段逐字拼接零改写（P6/ADR 0142）；时点一律走 reign_period_label
    纪年语义标识，不裸出 turn/水位。"""
    summary_row = db.get_relation_summary(source, target)
    events = db.get_relation_edge_events(source=source, target=target)

    summary_parts: List[str] = []
    if summary_row is not None:
        for segment in (summary_row["founding_segment"], summary_row["recent_segment"]):
            text = str(segment or "")
            if text:
                summary_parts.append(text)
    summary = "\n".join(summary_parts)

    recent_context = ""
    updated_at_period = ""
    if events:
        latest = max(events, key=lambda event: int(event["id"]))
        event_label = reign_period_label(int(latest["year"]), int(latest["period"]))
        # 最近原始事件语境原文＋纪年回指；语境本身逐字原样（写口已零改字）。
        recent_context = f"{latest['context']}（{event_label}）"
    if summary_row is not None:
        updated_at_period = reign_period_label(
            int(summary_row["last_brewed_year"]), int(summary_row["last_brewed_period"])
        )
    elif events:
        # 未酿先读（事件已在流水、摘要未落定）：更新纪年回落最近事件时点。
        latest = max(events, key=lambda event: int(event["id"]))
        updated_at_period = reign_period_label(int(latest["year"]), int(latest["period"]))

    return {
        "source": source,
        "target": target,
        "summary": summary,
        "recent_context": recent_context,
        "updated_at_period": updated_at_period,
    }
