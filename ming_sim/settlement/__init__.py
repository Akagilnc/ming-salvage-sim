"""结算落库编排器包（ADR 0150 决定 1/2/4/6；承接 #1835 与 #1572）。

内层落库子核的唯一入口是 :func:`settle_delta`，返回 typed
:class:`SettlementOutcome`。旧单体入口 ``apply_score_extraction`` 已整体退役，
不留 deprecated 壳、不保留五格包装（ADR 0150 决定 6；#1835 F1）。

段适配器按实体入住 ``ming_sim/entities/<entity>/delta_section.py``，段序真源是
:mod:`ming_sim.settlement.registry` 的有序登记表（决定 4）——先建军再 army_delta、
人物 pre/post-issue 拆分、财政 removes→creates→changes 等顺序约束不再只活在
编排器注释里。登记走 lazy 路径字符串，不在 import 期同步加载重模块（防与
``GameDB`` 循环依赖；沿 ADR 0010 决定 1 的验收口径）。
"""

from ming_sim.settlement.outcome import (
    FiscalSectionResult,
    IssueSectionResult,
    SettlementOutcome,
)
from ming_sim.settlement.registry import (
    SectionSpec,
    ordered_sections,
    section_specs,
)
from ming_sim.settlement.run import (
    SettlementContext,
    SettlementRun,
    settle_delta,
    to_rejected_items,
)

__all__ = [
    "FiscalSectionResult",
    "IssueSectionResult",
    "SettlementContext",
    "SettlementOutcome",
    "SettlementRun",
    "SectionSpec",
    "ordered_sections",
    "section_specs",
    "settle_delta",
    "to_rejected_items",
]
