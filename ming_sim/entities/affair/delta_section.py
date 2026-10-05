"""事务（R1 affair）顶层声明段。

ADR 0154（2026-09-30）撤销「宣布了结」动作及拒绝该动作的守门：事务成为往事
由世界记录据事项实况自然承接，本段不再解析/执行 close，也不再以未了局势守门。
顶层若仍投递了结声明，按通用 attach 不在本阶段拒收，不另立专属守门。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, SectionResult
from ming_sim.entities.affair import parse_affair_declaration
from ming_sim.exceptions import DeclarationDataError


def apply(run):
    applied = []
    rejected: list[RejectedItem] = []
    source = run.ctx.source

    for raw in run.current_extracted.get("affair_declarations") or []:
        try:
            if not isinstance(raw, dict):
                raise DeclarationDataError("事务声明须为对象")
            # 空允许集：close/birth 均不在本段执行；通用「不在本阶段」而非未了局势守门。
            parse_affair_declaration(raw, allowed=frozenset())
        except DeclarationDataError as exc:
            rejected.append(RejectedItem(
                item={"raw_value": raw},
                reason=str(exc),
                category="invalid_shape",
                source=source,
            ))
            continue
    return SectionResult(applied=applied, rejected=rejected)
