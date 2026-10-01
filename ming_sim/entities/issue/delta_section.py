"""局势落库段：``issue_advances`` / ``new_issues`` / ``close_issues`` / ``cancels``。

本段还承接**战略/外敌事件的战果物化与压制**——那是局势路的一部分（事件触发的
判定发生在 new_issues 里，战果落账必须与该判定同一批次、同一事务，故不放独立
段）。跨类逐笔核算与共同资源占用归 #1844，本段只管「事件未触发则其从属战果整组
不落主账」这一条归属纪律。

事件未触发时逐项拒收留痕（不是整批丢弃）：同批独立好项不受牵连（ADR 0015）。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    from ming_sim.issues import (
        _monthly_economy_items,
        _strategic_event_outcome_label_or_error,
        apply_event_cascading_invalidations,
        apply_issue_tracker_output,
        loads_effect_dict,
    )

    # 静态门闩先响亮筛：只有真能过候选/结果闸的事件结局标签才 fail-loud，
    # 非候选幻觉留给后面的 event_pool 逐项拒收（免不相干 delta 一并被带走）。
    strategic_event_label_gate_ids = (
        run.strategic_event_pool_ids
        & run.strategic_event_result_delta_event_ids
        & run.candidate_event_ids_at_input
    )
    for event_id in sorted(strategic_event_label_gate_ids):
        _strategic_event_outcome_label_or_error(
            event_id, run.extracted, run.runtime_content,
        )

    issue_summary = apply_issue_tracker_output(
        run.db, run.state, {
            "advances": run.current_extracted.get("issue_advances") or [],
            "new_issues": run.current_extracted.get("new_issues") or [],
            "close_issues": run.current_extracted.get("close_issues") or [],
            "cancels": run.current_extracted.get("cancels") or [],
        },
        llm_config=run.ctx.llm_config,
        content=run.ctx.content,
        pending_person_changes_for_gates=run.post_issue_person_changes,
        candidate_event_ids_at_input=run.candidate_event_ids_at_input,
        candidate_event_ids_authoritative=run.candidate_event_ids_authoritative,
        impeachment_surge_candidates_at_input=run.ctx.impeachment_surge_candidates_at_input,
        event_result_delta_event_ids=run.strategic_event_result_delta_event_ids,
        defer_event_trigger_ids=run.strategic_event_pool_ids,
        open_affair_ids_at_input=run.authorized_open_affairs,
    )
    run.issue_summary = issue_summary

    # 承诺月支载体：同批新建的承诺局势其 ongoing 月支被财政段用作 dedup 依据
    # （ADR 0027 承诺是主载体）。
    carriers: List[Dict[str, object]] = []
    for item in issue_summary.get("new_issues") or []:
        if not (
            isinstance(item, dict)
            and not item.get("rejected")
            and str(item.get("commitment_kind") or "").strip()
            and item.get("issue_id") is not None
        ):
            continue
        row = run.db.conn.execute(
            "SELECT ongoing_effects FROM issues WHERE id=?", (int(item["issue_id"]),),
        ).fetchone()
        if row is None:
            continue
        carriers.extend(_monthly_economy_items(loads_effect_dict(row["ongoing_effects"])))
    run.commitment_economy_carriers = carriers

    _resolve_strategic_events(run)
    return SectionResult(applied=[], rejected=[])


def _resolve_strategic_events(run) -> None:
    """已触发事件物化战果；未触发者其从属战果整组不落主账。

    归属与信封预检已由 ``preflight_declared_event_effects`` 在写入前判定一次，
    故此处不再重判已通过的 admitted 事件——重复判会出现第二真源。
    """
    from ming_sim.entities.army.delta_section import (
        apply_army_delta_with_cannon_transfer,
    )
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef
    from ming_sim.issues import (
        _person_change_name,
        _strategic_event_outcome_label_or_error,
        apply_event_cascading_invalidations,
    )

    new_issues = run.issue_summary.get("new_issues") or []
    seen: set[str] = set()
    for new_issue in new_issues:
        if isinstance(new_issue, dict):
            event_id = str(new_issue.get("id") or "").strip()
            if event_id in run.strategic_event_referenced_ids:
                seen.add(event_id)
        if not isinstance(new_issue, dict) or not new_issue.get("rejected"):
            continue
        event_id = str(new_issue.get("id") or "").strip()
        if event_id not in run.strategic_event_referenced_ids:
            continue
        run.reject_suppressed_strategic_results(
            event_id, str(new_issue.get("title") or ""),
        )

    for event_id in sorted(run.strategic_event_delta_ids - seen):
        ev = run.runtime_content.event_by_id.get(event_id)
        run.reject_suppressed_strategic_results(
            event_id, ev.title if ev is not None else event_id,
        )

    for new_issue in new_issues:
        if not (
            isinstance(new_issue, dict)
            and new_issue.get("deferred_trigger")
            and not new_issue.get("rejected")
        ):
            continue
        event_id = str(new_issue.get("id") or "").strip()
        if event_id not in run.strategic_event_pool_ids:
            continue
        outcome_label, outcome_error = _strategic_event_outcome_label_or_error(
            event_id, run.extracted, run.runtime_content,
        )
        if outcome_error:
            new_issue["rejected"] = True
            new_issue["category"] = "missing_event_outcome"
            new_issue["reason"] = outcome_error
            run.reject_suppressed_strategic_results(
                event_id, str(new_issue.get("title") or ""),
            )
            continue
        for item in run.event_new_armies(event_id):
            origin_ref = str(item.get("origin_ref") or "").strip()
            run.created_armies.extend(run.db.create_armies_from_extraction(
                run.state, [item], actor="档房", commit=run.commit_now,
                origin_ref=origin_ref, require_origin=True,
            ))
        for region_id, raw_changes in run.ordered_strategic_items("region_delta", event_id):
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            run.region_changes.extend(run.db.apply_region_deltas(
                run.state, run.pseudo_event, None, "档房", {region_id: payload},
                commit=run.commit_now, origin_ref=origin_ref, require_origin=True,
            ))
        for army_id, raw_changes in run.ordered_strategic_items("army_delta", event_id):
            run.army_changes.extend(apply_army_delta_with_cannon_transfer(
                run.db, run.state, run.pseudo_event, army_id, raw_changes,
                commit_now=run.commit_now,
            ))
        event_person_results: List[Dict[str, object]] = []
        for item in run.event_person_changes(event_id):
            try:
                origin_ref = run.origin_ref_from_result_item(item)
            except UnauthorizedAffairOriginRef as exc:
                # 与逐项人物/经济路同一个窄授权失败信号，不与代码故障同流。
                event_person_results.append({
                    "name": _person_change_name(item),
                    "动作": str(item.get("动作") or item.get("action") or "").strip(),
                    "rejected": True, "category": "unauthorized_affair_origin",
                    "reason": str(exc), "item": dict(item),
                })
                continue
            event_person_results.extend(run.apply_normalized_person_changes(
                [dict(item)], origin_ref=origin_ref, require_origin=True,
            ))
        for power_id, raw_changes in run.ordered_strategic_items("power_updates", event_id):
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            run.power_changes.extend(run.db.apply_power_deltas(
                run.state, {power_id: payload}, commit=run.commit_now,
                origin_ref=origin_ref, require_origin=True,
            ))
        run.db.mark_event_triggered(
            run.state, event_id, terminal_reason=outcome_label, commit=run.commit_now,
        )
        apply_event_cascading_invalidations(run.state, run.db, commit=run.commit_now)
        new_issue["reason"] = "事件已记为触发，软判结果已落主账"
        # 成功的人物落账已由 apply_normalized_person_changes 并入
        # applied_person_changes；只有授权拒收活在 event_person_results ——
        # 提一次，免得物质兄弟把结构化痕迹抹掉。
        present = {id(row) for row in run.applied_person_changes}
        for row in event_person_results:
            if row.get("rejected") and id(row) not in present:
                run.applied_person_changes.append(row)
