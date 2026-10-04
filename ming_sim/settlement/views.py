"""SettlementOutcome 的具名段视图（ADR 0150 §4 投影表的运行态实现）。

消费端问「这段落了哪些」直接读 :meth:`SettlementOutcome.sections`，禁各自手写字段路径——
手写等于把投影表复制到十几处，改一处漏一处。

这不是 dict 兼容层：它不还原旧 39 键 dict、不支持 ``[]`` 取键、不带恒空键与双份
键。标签即 ``sections()`` 的段名；取到的仍是 typed 段结果。
"""

from __future__ import annotations

from typing import Any, List, Optional

from ming_sim.applier import RejectedItem, SectionResult


def section(outcome: Any, key: str) -> Optional[SectionResult]:
    """取某标签对应的 typed 段；标签未知或 outcome 缺省返回 ``None``。"""
    if outcome is None or not hasattr(outcome, "sections"):
        return None
    return outcome.sections().get(key)


def view(outcome: Any, key: str) -> List[Any]:
    """取某标签的**已落项**列表。"""
    found = section(outcome, key)
    return list(found.applied) if found is not None else []


def rejected_view(outcome: Any, key: str):
    """取某标签的拒收项（canonical ``RejectedItem``）。"""
    found = section(outcome, key)
    return list(found.rejected) if found is not None else []


def shape_rejections(outcome: Any) -> List[RejectedItem]:
    """框架前置闸（sanitize / 误投 / 同批 identity 冲突）的拒收项。

    这些不是段落格产物，故不经 :meth:`SettlementOutcome.sections`；旧报告里的
    ``validate_shape_rejections`` 键即此。
    """
    return list(getattr(outcome, "shape_rejections", []) or [])


def issue_rows(outcome: Any, subkey: str) -> List[Any]:
    """局势段某一子表的行（旧 ``report["issue_summary"][subkey]``）。

    ``subkey`` ∈ advances / new_issues / closes / cancels。
    """
    issue = getattr(outcome, "issue", None)
    return list(getattr(issue, subkey, []) or []) if issue is not None else []


def issue_applied_person_changes(outcome: Any) -> List[Any]:
    """局势路自带的人物变更（与人物段 applied 分列，不合并）。"""
    issue = getattr(outcome, "issue", None)
    return list(getattr(issue, "applied_person_changes", []) or []) if issue is not None else []


def metric_deltas(outcome: Any) -> dict:
    """国库指标净增减（旧 ``report["metric_delta"]``）。"""
    return dict(getattr(getattr(outcome, "metric", None), "applied", []) or [])


def faction_deltas(outcome: Any) -> dict:
    """派系满意度净增减（旧 ``report["faction_delta"]``）。"""
    return {k: v for k, v in (getattr(getattr(outcome, "faction", None), "applied", []) or [])}


def class_deltas(outcome: Any) -> dict:
    """阶级满意度净增减（旧 ``report["class_delta"]``）。"""
    return {k: v for k, v in (getattr(getattr(outcome, "social_class", None), "applied", []) or [])}


def victory_status_of(outcome: Any) -> dict:
    """结局判定附加结果（叙事型优先；ongoing 不入）。"""
    return dict(getattr(outcome, "victory_status", None) or {})


def describe(outcome: Any, key: str) -> str:
    """段结果的简短可读摘要，供断言消息 / 报错文本使用。

    断言消息常写成 f-string（``f"…实得 {applied['fiscal_changes']}"``）——那里
    不能塞函数调用之外的复杂表达式，故本函数给出单调用形态：把该段的已落项与
    拒收项并看成人读摘要。

    这是**诊断文本**，不是数据口：消费端判「落了没有」仍读 :func:`view` /
    :func:`rejected_view`。
    """
    landed = view(outcome, key)
    refused = rejected_view(outcome, key)
    if not refused:
        return repr(landed)
    return f"{landed!r} + {len(refused)} rejected"
