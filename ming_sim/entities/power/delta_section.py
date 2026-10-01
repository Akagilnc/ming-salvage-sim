"""非明势力段：``power_updates``（三字段简表）与 ``bandit_absorptions``（流民投贼）。

两条同登记条目，因为「流寇实力正增只走吸收请求吃池顶」这条闸跨两者：自由
``power_updates`` 申报流寇正实力一律拒收（否则实力可绕过池顶凭空增长）。
另有招安易主同回合闸：同批已有招安易主时，顶层 ``power_updates`` 剿股被拒
（削股须随易主反噬一处落账，防两处写同一次削弱）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

from typing import Dict, List

from ming_sim.applier import SectionResult
from ming_sim.issues import POWER_FIELD_ALIASES, _effect_event_ids, _is_bandit_power_id


def apply(run) -> SectionResult:
    from ming_sim.issues import _apply_bandit_absorptions

    applied_absorptions, absorption_rejections, absorption_power_changes = (
        _apply_bandit_absorptions(
            run.db, run.state, run.current_extracted.get("bandit_absorptions") or [],
            commit=False, source=run.ctx.source,
        )
    )
    bandit_rows = applied_absorptions
    rejections: List[RejectedItem] = []
    power_changes: List[Dict[str, object]] = list(absorption_power_changes)

    power_items = (
        (power_id, changes) for index, (power_id, changes) in enumerate(
            run.current_ordered.get("power_updates") or []
        )
        if not _effect_event_ids(
            "power_updates", index, run.strategic_event_referenced_ids,
            run.current_event_ids,
        )
    )
    for power_id, raw_changes in power_items:
        if power_id in run.amnesty_conflict_power_ids:
            rejections.append(RejectedItem(item={"power_id": power_id, "changes": raw_changes}, reason="同一股同一时段已有招安易主，拒绝顶层 power_updates 剿股；削股须随易主反噬一处落账", category="invalid_transition", source=run.ctx.source))
            continue
        if not isinstance(raw_changes, dict):
            continue
        if _is_bandit_power_id(str(power_id)):
            # 只剥正实力；威望/经济等同包其它字段仍可落。
            stripped: Dict[str, object] = {}
            positive_ms_rejected = False
            ms_item: Dict[str, object] | None = None
            for k, v in raw_changes.items():
                if POWER_FIELD_ALIASES.get(str(k).strip(), str(k).strip()) != "military_strength":
                    stripped[k] = v
                    continue
                try:
                    if isinstance(v, bool) or isinstance(v, float):
                        raise ValueError("非整数")
                    ms_delta = int(v)
                except (TypeError, ValueError):
                    stripped[k] = v  # 交 apply_power_deltas 原样拒非整数
                    continue
                if ms_delta > 0:
                    positive_ms_rejected = True
                    ms_item = {"power_id": power_id, "field": str(k), "value": v}
                else:
                    stripped[k] = v
            if positive_ms_rejected:
                rejections.append(RejectedItem(item=ms_item or {"power_id": power_id, "changes": raw_changes}, reason="流寇实力正增须走 bandit_absorptions 吃池顶，禁止自由 power_updates 正实力", category="invalid_enum", source=run.ctx.source))
            if not stripped:
                continue
            raw_changes = stripped
        origin_ref = str(raw_changes.get("origin_ref") or "").strip()
        payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
        landed, refused = run.db.apply_power_deltas(
            run.state, {power_id: payload}, commit=False,
            origin_ref=origin_ref, require_origin=True,
        source=run.ctx.source)
        power_changes.extend(landed)
        rejections.extend(refused)

    from ming_sim.settlement.run import _store

    _store(
        run,
        "bandit_absorptions",
        SectionResult(applied=bandit_rows, rejected=absorption_rejections),
    )
    return SectionResult(applied=power_changes, rejected=rejections)
