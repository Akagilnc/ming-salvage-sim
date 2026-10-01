"""朝堂派系（``faction_delta``）落库段。

派系满意度是账面读数；联动靠 LLM 判断，代码不替角色做决定（P6）。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult, merge_delta_maps, section_from_rows


def apply(run) -> SectionResult:
    from ming_sim.issues import _apply_faction_dict

    totals: dict = {}
    rejected_rows = []
    for key, value in run.current_ordered.get("faction_delta") or []:
        applied, rejected = _apply_faction_dict(
            run.db, {key: value}, commit=False,
        )
        merge_delta_maps(totals, applied)
        rejected_rows.extend(rejected)
    refused = section_from_rows(
        rejected_rows, run.ctx.source, category="faction_delta",
    )
    return SectionResult(applied=list(totals.items()), rejected=refused.rejected)
