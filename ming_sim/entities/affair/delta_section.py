"""事务（R1 affair）结清段（``affair_declarations``）。

**为什么排在局势段之后、人物 post 段之前**：结清看的是本批最终局势态——同批挂靠
的局势必须能阻止结清，否则已闭的事务会指向仍在进行的活。这条顺序约束由登记表
承载，不再是编排器里的一句注释。

授权 fail-closed：只结清本批冻结输入闭集内的事务。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, SectionResult
from ming_sim.entities.affair import ATTACH_RESULT_CLOSE, parse_affair_declaration


def apply(run):
    applied = []
    rejected: list[RejectedItem] = []
    source = run.ctx.source

    def _refuse(raw: object, reason: str, category: str) -> None:
        rejected.append(RejectedItem(
            item={"raw_value": raw},
            reason=reason,
            category=category,
            source=source,
        ))

    for raw in run.current_extracted.get("affair_declarations") or []:
        try:
            if not isinstance(raw, dict):
                raise ValueError("事务声明须为对象")
            parsed = parse_affair_declaration(raw, allowed=ATTACH_RESULT_CLOSE)
            affair_id = int(parsed["affair_id"])
        except (TypeError, ValueError) as exc:
            _refuse(raw, str(exc), "invalid_shape")
            continue
        if affair_id not in run.frozen_open_affairs:
            _refuse(raw, "事务不在本批可见输入", "unauthorized_affair_origin")
            continue
        active_issue = run.db.conn.execute(
            "SELECT 1 FROM issues WHERE affair_id=? AND status='active' LIMIT 1",
            (affair_id,),
        ).fetchone()
        if active_issue is not None:
            _refuse(raw, "事务尚有未了局势", "invalid_shape")
            continue
        exists = run.db.conn.execute(
            "SELECT 1 FROM affairs WHERE id=?", (affair_id,),
        ).fetchone()
        if exists is None:
            _refuse(raw, "事务不存在", "invalid_shape")
            continue
        closed = run.db.affairs.declare_closed(affair_id, turn=int(run.state.turn))
        applied.append({"affair_id": closed.id, "declaration": raw})
    return SectionResult(applied=applied, rejected=rejected)
