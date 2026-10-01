"""州县（``region_delta``）落库段。

州府是账面行政单位；段只写声明带来的存量变动，不代拟治理评价（P4：DB 有数、
皇帝无表——评价由转译 LLM 写，段不合成玩家可感文案）。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult
from ming_sim.issues import _effect_event_ids


def apply(run) -> SectionResult:
    for index, (region_id, raw_changes) in enumerate(
        run.current_ordered.get("region_delta") or []
    ):
        if _effect_event_ids(
            "region_delta", index, run.strategic_event_referenced_ids,
            run.current_event_ids,
        ):
            continue
        origin_ref = str(raw_changes.get("origin_ref") or "").strip()
        payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
        run.region_changes.extend(run.db.apply_region_deltas(
            run.state, run.pseudo_event, None, "档房", {region_id: payload},
            commit=run.commit_now, origin_ref=origin_ref, require_origin=True,
        ))
    return SectionResult(applied=[], rejected=[])
