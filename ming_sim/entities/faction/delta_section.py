"""朝堂派系（``faction_delta``）落库段。

派系满意度是账面读数；联动靠 LLM 判断，代码不替角色做决定（P6）。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    from ming_sim.issues import _apply_faction_dict

    for key, value in run.current_ordered.get("faction_delta") or []:
        applied, rejected = _apply_faction_dict(
            run.db, {key: value}, commit=run.commit_now,
        )
        run.merge_applied_deltas(run.applied_factions, applied)
        run.faction_rejections.extend(rejected)
    return SectionResult(applied=[], rejected=[])
