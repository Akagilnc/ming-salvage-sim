"""哭谏条消费段（#623）。

召对 extraction 的真入口：反悔/坚持消费哭谏条。**必须先于 cancels 物化**，使
persist 先结账，cancels 环看到已非 active 而跳过——防同一反悔走两条路径双写。
该顺序约束由登记表把它排在最前承载。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run):
    from ming_sim.breach_plea import resolve_breach_pleas_from_extraction

    resolutions, rejections = resolve_breach_pleas_from_extraction(
        run.db, run.state, run.current_extracted, source=run.ctx.source, commit=False,
    )
    return SectionResult(applied=resolutions, rejected=rejections)
