"""SettlementOutcome 的具名段视图（ADR 0150 §4 投影表的运行态实现）。

消费端问「这段落了哪些」在本模块一处映射到 typed 段，禁各自手写字段路径——
手写等于把投影表复制到十几处，改一处漏一处。

这不是 dict 兼容层：它不还原旧 39 键 dict、不支持 ``[]`` 取键、不带恒空键与双份
键。旧键名只作为**具名视图的标签**存在，取到的仍是 typed 段结果；标签集就是
:func:`view_keys`，多一个标签即多一条无主投影，是漂移。
"""

from __future__ import annotations

from typing import Any, List, Optional

from ming_sim.applier import RejectedItem, SectionResult

# 标签 → SettlementOutcome.sections() 的段名。
_VIEW_TO_SECTION = {
    "metric_delta": "metric_delta",
    "economy_moves": "economy_moves",
    "faction_delta": "faction_delta",
    "class_delta": "class_delta",
    "surcharge_decrees": "surcharge_decrees",
    "population_transfers": "population_transfers",
    "region_changes": "region_changes",
    "army_changes": "army_changes",
    "power_changes": "power_changes",
    "bandit_absorptions": "power_changes",
    "applied_person_changes": "applied_person_changes",
    "secret_order_updates": "secret_order_updates",
    "breach_plea_resolutions": "breach_plea_resolutions",
    "credit_event_resolutions": "credit_event_resolutions",
    "relation_edge_event_resolutions": "relation_edge_event_resolutions",
    "authority_changes": "authority_changes",
    "dossier_executions": "dossier_executions",
    "dossier_participants": "dossier_participants",
    "secret_dossier_participants": "secret_dossier_participants",
    "issue_summary": "issue_summary",
    "fiscal_removes": "fiscal_removes",
    "fiscal_creates": "fiscal_creates",
    "fiscal_changes": "fiscal_changes",
}


def view_keys() -> frozenset:
    """全部合法视图标签。"""
    return frozenset(_VIEW_TO_SECTION)


def section(outcome: Any, key: str) -> Optional[SectionResult]:
    """取某标签对应的 typed 段；标签未知或 outcome 缺省返回 ``None``。"""
    if outcome is None or not hasattr(outcome, "sections"):
        return None
    section_name = _VIEW_TO_SECTION.get(key)
    if section_name is None:
        return None
    return outcome.sections().get(section_name)


def _is_absorption_applied(row: Any) -> bool:
    """流民投贼落账行带 actual_count；同段的实力增减行没有这个键。"""
    return isinstance(row, dict) and "actual_count" in row


def _is_absorption_rejected(item: RejectedItem) -> bool:
    """投贼拒收的原件带 requested_count；非法形状的原因以段名前缀起句。

    自由实力正增的拒收原因里也会提到 bandit_absorptions，那是势力段的拒收，
    不按子串归到投贼。
    """
    inner = item.item
    if isinstance(inner, dict) and (
        "requested_count" in inner or "actual_count" in inner
    ):
        return True
    return str(item.reason or "").startswith("bandit_absorptions")


def view(outcome: Any, key: str) -> List[Any]:
    """取某标签的**已落项**列表。"""
    found = section(outcome, key)
    rows = list(found.applied) if found is not None else []
    if key == "bandit_absorptions":
        return [row for row in rows if _is_absorption_applied(row)]
    if key == "power_changes":
        return [row for row in rows if not _is_absorption_applied(row)]
    return rows


def rejected_view(outcome: Any, key: str) -> List[RejectedItem]:
    """取某标签的拒收项（canonical ``RejectedItem``）。"""
    found = section(outcome, key)
    rows = list(found.rejected) if found is not None else []
    if key == "bandit_absorptions":
        return [row for row in rows if _is_absorption_rejected(row)]
    if key == "power_changes":
        return [row for row in rows if not _is_absorption_rejected(row)]
    return rows


def shape_rejections(outcome: Any) -> List[RejectedItem]:
    """框架前置闸（sanitize / 误投 / 同批 identity 冲突）的拒收项。

    这些不是段落格产物，故不经 :meth:`SettlementOutcome.sections`；旧报告里的
    ``validate_shape_rejections`` 键即此。
    """
    return list(getattr(outcome, "shape_rejections", []) or [])


def issue_rows(outcome: Any, subkey: str) -> List[Any]:
    """局势段某一子表的行（旧 ``report["issue_summary"][subkey]``）。

    ``subkey`` ∈ advances / new_issues / closes / cancels / pairing_warnings。
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
