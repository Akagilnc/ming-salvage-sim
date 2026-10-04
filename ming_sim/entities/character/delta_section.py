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

from ming_sim.applier import RejectedItem, Provenance

from typing import Dict, List, Set

from ming_sim.applier import SectionResult


def apply_declared_person_changes(run, changes, *, phase: str):
    """人物项逐条落账。归属非法只在写前解析处拒收。

    代码异常由外层事务回滚，不记成拒收（ADR 0005）。落库核在本实体。
    """
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef
    from ming_sim.entities.character.apply import apply_person_changes

    del phase
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
    return apply_declared_person_changes(
        run, run.pre_issue_person_changes, phase="pre",
    )


def apply_post_issue(run):
    """局势段之后落的其余人物变更。"""
    return apply_declared_person_changes(
        run, run.post_issue_person_changes, phase="post",
    )


def amnesty_conflict_power_ids(
    person_changes: List[Dict[str, object]],
    db,
    content,
    state,
) -> Set[str]:
    """同批已有招安易主时，须随易主反噬落账的旧势力 id 集合。

    同一股同一时段已有招安易主，顶层 ``power_updates`` 再剿一次就是两处写同一次
    削弱；此时顶层申报被拒，削弱只认反噬那一处。合法易主的识别复用既有
    ``resolve_person_transition`` 守门，不在本段另立政策。
    """
    from ming_sim.person_archive_contract import PERSON_IDENTITY_TITLES, resolve_person_transition

    power_ids: Set[str] = set()
    for item in person_changes:
        if str(item.get("动作") or "").strip() != "易主":
            continue
        if str(item.get("方式") or item.get("way") or "").strip() != "主动归附":
            continue
        if str(item.get("new_power") or "").strip() != "ming":
            continue
        backlash = item.get("反噬", item.get("backlash"))
        if not isinstance(backlash, dict):
            continue
        if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
            continue
        name = str(item.get("name") or "").strip()
        if content is not None:
            from ming_sim.session import _find_existing_minister

            name = _find_existing_minister(content, name, db) or name
        row = db.conn.execute(
            "SELECT status, power_id, reason_code FROM characters WHERE name=?",
            (name,),
        ).fetchone()
        if row is None:
            continue
        old_power = str(row["power_id"] or "").strip()
        if old_power in {"", "ming"}:
            continue
        transition = resolve_person_transition(
            str(row["status"] or "active"), "易主",
            reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
        )
        if transition.startswith("reject:"):
            continue
        backlash_power_ids = {
            str(power_id).strip()
            for power_id in backlash.keys()
            if str(power_id).strip()
        }
        if any(power_id != old_power for power_id in backlash_power_ids):
            continue
        explicit_title = str(item.get("new_title") or item.get("title") or "").strip()
        if explicit_title and explicit_title not in PERSON_IDENTITY_TITLES:
            continue
        # 同期的合法招安本就主张旧存量——哪怕 LLM 忘了把削弱写进反噬，
        # 顶层再申报也是压制性记账。故此处记下旧股 id。
        power_ids.add(old_power)
    return power_ids
