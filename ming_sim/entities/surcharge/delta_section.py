"""明渠加派旨（``surcharge_decrees``）落库段（#650 / 0089，P1）。

下旨加派逐省累积账。落下的加派认领（``(origin_ref, region_id)``）由编排器交给人口
段做「同一道加派旨的人口后果已由加派账唯一拥有」去重——两段的先后由登记表承
载，段间不直接调用。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run):
    from ming_sim.entities.surcharge.apply import _apply_surcharge_decrees

    applied_surcharges, surcharge_rejections = _apply_surcharge_decrees(
        run.db, run.current_extracted.get("surcharge_decrees") or [], source=run.ctx.source,
    )
    # 逐笔交错时跨信封累加：后笔人口段仍能见到先笔已落加派认领。
    run.surcharge_claims.update({
        (str(item.get("origin_ref") or ""), str(item.get("region_id") or ""))
        for item in applied_surcharges
    })
    return SectionResult(applied=applied_surcharges, rejected=surcharge_rejections)
