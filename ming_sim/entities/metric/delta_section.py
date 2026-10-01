"""国库指标（``metric_delta``）落库段。

指标是「账面上的国力读数」，段只把已落账的净增减交回编排器；上限 clamp 由
``state.clamp()`` 在全批落定后统一做，段内不自行封顶（否则同批多项各自 clamp
会互相吃掉余量）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, SectionResult


def apply(run) -> SectionResult:
    """把本笔（整批或 effects 单笔）的 metric_delta 收成净增减。"""
    from ming_sim.entities.metric.apply import declare_metric_pairs

    totals, refused = declare_metric_pairs(
        run.state, list(run.current_ordered.get("metric_delta") or []), db=run.db,
    )
    source = run.ctx.source
    return SectionResult(
        applied=list(totals.items()),
        rejected=[
            RejectedItem(
                item={"metric": key, "value": raw},
                reason=reason,
                category=category,
                source=source,
            )
            for key, raw, reason, category in refused
        ],
    )
