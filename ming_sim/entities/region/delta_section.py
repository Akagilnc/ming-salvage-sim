"""州县（``region_delta``）落库段。

州府是账面行政单位；段只写声明带来的存量变动，不代拟治理评价（P4：DB 有数、
皇帝无表——评价由转译 LLM 写，段不合成玩家可感文案）。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult
from ming_sim.settlement.preflight import _effect_event_ids


def apply(run):
    rows = []
    rejections = []
    for index, (region_id, raw_changes) in enumerate(
        run.current_ordered.get("region_delta") or []
    ):
        if _effect_event_ids(
            "region_delta", index, run.strategic_event_referenced_ids,
            run.current_event_ids,
        ):
            continue
        # 身份槽已由 sanitize_delta_shape 升格；本段只剥 origin_ref 交写核。
        changes = raw_changes if isinstance(raw_changes, dict) else {}
        origin_ref = str(changes.get("origin_ref") or "").strip()
        payload = {k: v for k, v in changes.items() if k != "origin_ref"}
        landed, refused = run.db.apply_region_deltas(
            run.state, run.pseudo_event, None, "档房", {region_id: payload},
            commit=False, origin_ref=origin_ref, require_origin=True, source=run.ctx.source,
        )
        rows.extend(landed)
        rejections.extend(refused)
    return SectionResult(applied=rows, rejected=rejections)
