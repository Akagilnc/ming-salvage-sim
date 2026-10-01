"""事务（R1 affair）结清段（``affair_declarations``）。

**为什么排在局势段之后、人物 post 段之前**：结清看的是本批最终局势态——同批挂靠
的局势必须能阻止结清，否则已闭的事务会指向仍在进行的活。这条顺序约束由登记表
承载，不再是编排器里的一句注释。

授权 fail-closed：只结清本批冻结输入闭集内的事务。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    for raw in run.current_extracted.get("affair_declarations") or []:
        try:
            if not isinstance(raw, dict):
                raise ValueError("事务声明须为对象")
            run.db.affairs.close_from_declaration(
                raw, turn=int(run.state.turn),
                authorized_ids=run.frozen_open_affairs,
            )
        except (TypeError, ValueError, KeyError) as exc:
            run.shape_rejections.append(
                ("affair_declarations", {"raw_value": raw}, str(exc)),
            )
    return SectionResult(applied=[], rejected=[])
