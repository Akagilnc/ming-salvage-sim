"""社会阶级（``class_delta``）落库段。

#653 F3.2：财政事实只作为推演输入证据；最终方向与幅度由 LLM 结合事件、任免等同
回合事实综合判断，沿用既有 ``class_delta`` 契约原样接收，段内不做二次裁量。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult, merge_delta_maps


def apply(run) -> SectionResult:
    from ming_sim.entities.social_class.apply import _apply_class_dict

    totals: dict = {}
    rejected_rows = []
    for key, value in run.current_ordered.get("class_delta") or []:
        applied, rejected = _apply_class_dict(
            run.db, {key: value}, commit=False, source=run.ctx.source,
        )
        merge_delta_maps(totals, applied)
        rejected_rows.extend(rejected)
    return SectionResult(applied=list(totals.items()), rejected=rejected_rows)
