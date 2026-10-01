"""国库指标（``metric_delta``）落库段。

指标是「账面上的国力读数」，段只把已落账的净增减交回编排器；上限 clamp 由
``state.clamp()`` 在全批落定后统一做，段内不自行封顶（否则同批多项各自 clamp
会互相吃掉余量）。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    """把本笔（整批或 effects 单笔）的 metric_delta 收成净增减。"""
    from ming_sim.issues import _apply_metric_dict

    totals: dict = {}
    for key, value in run.current_ordered.get("metric_delta") or []:
        for metric, delta in _apply_metric_dict(run.state, {key: value}, db=run.db).items():
            totals[metric] = totals.get(metric, 0) + delta
    return SectionResult(applied=list(totals.items()), rejected=[])
