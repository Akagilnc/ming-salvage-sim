"""人物变更落库段：``apply_pre_issue`` 与 ``apply_post_issue`` 两条登记。

**为什么拆两条**（ADR 0150 决定 4）：人物变更里「评定」驱动局势门闩，必须在局势
段之前落；其余动作（任免、易主、行止、奏对…）要与局势段交错——局势结案时要读
刚落的人物态。拆成两条登记后这个顺序约束是可审的数据，不再是编排器里的注释。

本段是人物实体的**唯一**写流：旧四键（``appointments`` / ``office_changes`` /
``character_status_changes`` / ``character_power_changes``）已随 C0 声明契约退役
（#1835 F1），声明若仍带旧键由 ``sanitize_delta_shape`` 逐段拒收留痕，不再静默
翻成平行写路。

项级事务边界由本编排段独占（ADR 0150 决定 3）：逐条 SAVEPOINT + 运行态快照，
实体核 ``apply_person_changes`` 只写、不自包事务/快照/恢复。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ming_sim.applier import (
    ItemAtomicReject,
    Provenance,
    RejectedItem,
    SectionResult,
    item_savepoint_scope,
    register_runtime_rollback_snapshot,
)


def _align_person_memory_to_db(db: Any, content: Any, item: Dict[str, object]) -> None:
    """写前把本项人物内存对齐到 DB 行，供项级快照以库为真源。"""
    if content is None:
        return
    from ming_sim.entities.character.names import _person_change_name

    name = str(_person_change_name(item) or "").strip()
    if not name or name not in content.characters:
        return
    row = db.conn.execute(
        "SELECT status, office, office_type, status_reason, reason_code, "
        "transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    if row is None:
        return
    ch = content.characters[name]
    ch.status = str(row["status"] or "")
    ch.office = str(row["office"] or "")
    ch.office_type = str(row["office_type"] or ch.office_type)
    ch.status_reason = str(row["status_reason"] or "")
    ch.reason_code = str(row["reason_code"] or "")
    ch.transit_to = str(row["transit_to"] or "")
    ch.transit_distance_remaining = row["transit_distance_remaining"]
    ch.transit_speed_factor = row["transit_speed_factor"]
    ch.transit_start_turn = int(row["transit_start_turn"] or 0)


def land_person_changes_isolated(
    db: Any,
    state: Any,
    changes: List[Dict[str, object]],
    *,
    content=None,
    llm_config: Any = None,
    origin_ref: str = "",
    require_origin: bool = False,
    source: Provenance = Provenance.system_simulation,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """编排侧逐条落人物变更：项级 SAVEPOINT + 共享运行态回调。

    拒收整项回滚（含关联案卷副作用），合法 sibling 不受牵连。实体核只写。
    """
    from ming_sim.entities.character.apply import apply_person_changes

    rows: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    runtime_content = content if content is not None else getattr(db, "content", None)
    for person_change in changes:
        item = dict(person_change)
        refused: List[RejectedItem] = []
        try:
            with item_savepoint_scope(db, f"person_item_{abs(id(item)) & 0xFFFFFFFF:x}"):
                _align_person_memory_to_db(db, runtime_content, item)
                register_runtime_rollback_snapshot(db, state, runtime_content)
                results, refused = apply_person_changes(
                    db,
                    state,
                    [item],
                    content=runtime_content,
                    llm_config=llm_config,
                    origin_ref=origin_ref,
                    require_origin=require_origin,
                    source=source,
                )
                if refused:
                    raise ItemAtomicReject(refused[0].reason, refused[0].category)
                if origin_ref:
                    for result in results:
                        result.setdefault("origin_ref", origin_ref)
                rows.extend(results)
        except ItemAtomicReject as exc:
            if refused:
                rejections.extend(refused)
            else:
                rejections.append(
                    RejectedItem(
                        item=item,
                        reason=exc.reason,
                        category=exc.category,
                        source=source,
                    )
                )
    return rows, rejections


def apply_declared_person_changes(run, changes):
    """人物项逐条落账。归属非法只在写前解析处拒收。

    代码异常由外层事务回滚，不记成拒收（ADR 0005）。落库核在本实体；
    项级隔离在本编排函数。
    """
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef

    rows = []
    rejections = []
    for person_change in changes:
        try:
            origin_ref = run.origin_ref_from_result_item(person_change)
        except UnauthorizedAffairOriginRef as exc:
            rejections.append(
                RejectedItem(
                    item=dict(person_change),
                    reason=str(exc),
                    category="unauthorized_affair_origin",
                    source=run.ctx.source,
                )
            )
            continue
        landed, refused = land_person_changes_isolated(
            run.db,
            run.state,
            [dict(person_change)],
            source=run.ctx.source,
            content=run.ctx.content,
            llm_config=run.ctx.llm_config,
            origin_ref=origin_ref,
            require_origin=True,
        )
        rows.extend(landed)
        rejections.extend(refused)
    return SectionResult(applied=rows, rejected=rejections)


def apply_pre_issue(run):
    """局势段之前落的「评定」等前置人物变更。"""
    return apply_declared_person_changes(run, run.pre_issue_person_changes)


def apply_post_issue(run):
    """局势段之后落的其余人物变更。"""
    return apply_declared_person_changes(run, run.post_issue_person_changes)
