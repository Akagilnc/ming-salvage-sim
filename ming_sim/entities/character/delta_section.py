"""人物变更落库段：``apply_pre_issue`` 与 ``apply_post_issue`` 两条登记。

**为什么拆两条**（ADR 0150 决定 4）：人物变更里「评定」驱动局势门闩，必须在局势
段之前落；其余动作（任免、易主、行止、奏对…）要与局势段交错——局势结案时要读
刚落的人物态。拆成两条登记后这个顺序约束是可审的数据，不再是编排器里的注释。

本段是人物实体的**唯一**写流：旧四键（``appointments`` / ``office_changes`` /
``character_status_changes`` / ``character_power_changes``）已随 C0 声明契约退役
（#1835 F1），声明若仍带旧键由 ``sanitize_delta_shape`` 逐段拒收留痕，不再静默
翻成平行写路。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, SectionResult


def apply_declared_person_changes(run, changes):
    """人物项逐条落账。归属非法只在写前解析处拒收。

    代码异常由外层事务回滚，不记成拒收（ADR 0005）。落库核在本实体。
    """
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef
    from ming_sim.entities.character.apply import apply_person_changes

    rows = []
    rejections = []
    for person_change in changes:
        try:
            origin_ref = run.origin_ref_from_result_item(person_change)
        except UnauthorizedAffairOriginRef as exc:
            rejections.append(RejectedItem(item=dict(person_change), reason=str(exc), category="unauthorized_affair_origin", source=run.ctx.source))
            continue
        results, refused = apply_person_changes(
            run.db, run.state, [dict(person_change)],
            source=run.ctx.source,
            content=run.ctx.content,
            llm_config=run.ctx.llm_config,
            origin_ref=origin_ref,
            require_origin=True,
        )
        if origin_ref:
            for result in results:
                result.setdefault("origin_ref", origin_ref)
        rows.extend(results)
        rejections.extend(refused)
    return SectionResult(applied=rows, rejected=rejections)

def apply_pre_issue(run):
    """局势段之前落的「评定」等前置人物变更。"""
    return apply_declared_person_changes(run, run.pre_issue_person_changes)


def apply_post_issue(run):
    """局势段之后落的其余人物变更。"""
    return apply_declared_person_changes(run, run.post_issue_person_changes)
