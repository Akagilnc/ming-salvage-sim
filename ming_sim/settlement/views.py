"""SettlementOutcome 的具名段视图（ADR 0150 §4 投影表的运行态实现）。

消费端问「这段落了哪些」直接读 :meth:`SettlementOutcome.sections`，禁各自手写字段路径——
手写等于把投影表复制到十几处，改一处漏一处。

这不是 dict 兼容层：它不还原旧 39 键 dict、不支持 ``[]`` 取键、不带恒空键与双份
键。标签即 ``sections()`` 的段名；取到的仍是 typed 段结果。
"""

from __future__ import annotations

from typing import Any, List, Optional

from ming_sim.applier import SectionResult


def section(outcome: Any, key: str) -> Optional[SectionResult]:
    """取某标签对应的 typed 段；标签未知或 outcome 缺省返回 ``None``。"""
    if outcome is None or not hasattr(outcome, "sections"):
        return None
    return outcome.sections().get(key)


def view(outcome: Any, key: str) -> List[Any]:
    """取某标签的**已落项**列表。"""
    found = section(outcome, key)
    return list(found.applied) if found is not None else []
