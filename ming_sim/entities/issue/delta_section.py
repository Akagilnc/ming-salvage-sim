"""局势落库段：``issue_advances`` / ``new_issues`` / ``close_issues`` / ``cancels``。

本段还承接**战略/外敌事件的战果物化与压制**——那是局势路的一部分（事件触发的
判定发生在 new_issues 里，战果落账必须与该判定同一批次、同一事务，故不放独立
段）。跨类逐笔核算与共同资源占用归 #1844，本段只管「事件未触发则其从属战果整组
不落主账」这一条归属纪律。

事件未触发时逐项拒收留痕（不是整批丢弃）：同批独立好项不受牵连（ADR 0015）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem

from typing import Dict, List

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    from ming_sim.entities.issue.tracker import apply_issue_tracker_output
    from ming_sim.models import loads_effect_dict
    from ming_sim.entities.issue.effects import _monthly_economy_items
    from ming_sim.settlement.preflight import _strategic_event_outcome_label_or_error

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
        candidate_event_ids_at_input=run.candidate_event_ids_at_input,
        candidate_event_ids_authoritative=run.candidate_event_ids_authoritative,
        impeachment_surge_candidates_at_input=run.ctx.impeachment_surge_candidates_at_input,
        event_result_delta_event_ids=run.strategic_event_result_delta_event_ids,
        defer_event_trigger_ids=run.strategic_event_pool_ids,
        open_affair_ids_at_input=run.authorized_open_affairs,
    source=run.ctx.source)
    # 承诺月支载体：同批新建的承诺局势其 ongoing 月支被财政段用作 dedup 依据
    # （ADR 0027 承诺是主载体）。
    carriers: List[Dict[str, object]] = []
    for item in issue_summary.new_issues:
        if not (
            isinstance(item, dict)
            and str(item.get("commitment_kind") or "").strip()
            and item.get("issue_id") is not None
        ):
            continue
        row = run.db.conn.execute(
            'SELECT ongoing_effects FROM issues WHERE id=?',
            (int(item['issue_id']),),
        ).fetchone()
        if row is None:
            continue
        carriers.extend(_monthly_economy_items(loads_effect_dict(row["ongoing_effects"])))
    run.commitment_economy_carriers = carriers

    extras = _resolve_strategic_events(run, issue_summary)
    from ming_sim.settlement.run import _store
    for extra_name, extra in extras.items():
        if extra_name == "issue":
            issue_summary.rejected.extend(extra.rejected)
        else:
            _store(run, extra_name, extra)
    return issue_summary


def _suppressed_rows(run, event_id: str, event_title: str, reason: str = "") -> Dict[str, list]:
    """未触发事件的从属战果逐项留痕，不落主账。"""
    reason = reason or f"战略/外敌事件「{event_title or event_id}」未触发，战果不落主账"
    rows: Dict[str, list] = {
        "region_changes": [], "army_changes": [], "power": [],
        "person_issue": [], "new_armies": [],
    }
    for region_id, raw_changes in run.ordered_strategic_items("region_delta", event_id):
        rows["region_changes"].append(RejectedItem(item={"event_id": event_id, "region_id": region_id, "changes": raw_changes}, reason=reason, category="event_rejected", source=run.ctx.source))
    for army_id, raw_changes in run.ordered_strategic_items("army_delta", event_id):
        rows["army_changes"].append(RejectedItem(item={"event_id": event_id, "army_id": army_id, "changes": raw_changes}, reason=reason, category="event_rejected", source=run.ctx.source))
    for power_id, raw_changes in run.ordered_strategic_items("power_updates", event_id):
        rows["power"].append(RejectedItem(item={"event_id": event_id, "power_id": power_id, "changes": raw_changes}, reason=reason, category="event_rejected", source=run.ctx.source))
    for item in run.event_person_changes(event_id):
        rows["person_issue"].append(RejectedItem(item=dict(item), reason=reason, category="event_rejected", source=run.ctx.source))
    for item in run.event_new_armies(event_id):
        raw_item = dict(item) if isinstance(item, dict) else item
        rows["new_armies"].append(RejectedItem(item={"event_id": event_id, "new_army": raw_item}, reason=reason, category="event_rejected", source=run.ctx.source))
    from ming_sim.settlement import registry
    sections = {key: spec.name for spec in registry.section_specs() for key in spec.delta_keys}
    sections["bandit_absorptions"] = "bandit_absorptions"
    for payload, _ordered, _owners, _event_id in run.deferred_event_effects.get(event_id, []):
        for key, value in payload.items():
            if value:
                refusal = RejectedItem(
                    item={"event_id": event_id, key: value}, reason=reason,
                    category="event_rejected", source=run.ctx.source,
                )
                if key in sections:
                    rows.setdefault(sections[key], []).append(refusal)
                else:
                    run.shape_rejections.append((key, refusal))
    return rows


def _extend_bucket(bucket: Dict[str, list], extra: Dict[str, list]) -> None:
    for key, rows in extra.items():
        bucket.setdefault(key, []).extend(rows)


def _resolve_strategic_events(run, issue_summary) -> Dict[str, SectionResult]:
    """已触发事件物化战果；未触发者其从属战果整组不落主账。

    归属与信封预检已由 ``preflight_declared_event_effects`` 在写入前判定一次，
    故此处不再重判已通过的 admitted 事件——重复判会出现第二真源。
    """
    from ming_sim.entities.army.delta_section import (
        apply_army_delta_with_cannon_transfer,
    )
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef
    from ming_sim.entities.issue.event_terminal import apply_event_cascading_invalidations
    from ming_sim.settlement.preflight import _strategic_event_outcome_label_or_error

    bucket: Dict[str, list] = {
        "region_changes": [], "army_changes": [], "power": [],
        "person_issue": [], "new_armies": [],
    }
    reject_bucket = {name: [] for name in bucket}
    new_issues = issue_summary.new_issues
    seen = {str(row.get("id") or "").strip() for row in new_issues}
    for refusal in issue_summary.rejected:
        original = refusal.item
        if not isinstance(original, dict):
            continue
        event_id = str(original.get("id") or original.get("origin_ref") or "").strip()
        if event_id not in run.strategic_event_referenced_ids:
            continue
        seen.add(event_id)
        _extend_bucket(reject_bucket, _suppressed_rows(
            run, event_id, str(original.get("title") or ""),
        ))

    for event_id in sorted(run.strategic_event_delta_ids - seen):
        ev = run.runtime_content.event_by_id.get(event_id)
        _extend_bucket(reject_bucket, _suppressed_rows(
            run, event_id, ev.title if ev is not None else event_id,
        ))

    for new_issue in list(new_issues):
        if not (
            isinstance(new_issue, dict)
            and new_issue.get("deferred_trigger")
        ):
            continue
        event_id = str(new_issue.get("id") or "").strip()
        if event_id not in run.strategic_event_pool_ids:
            continue
        outcome_label, outcome_error = _strategic_event_outcome_label_or_error(
            event_id, run.extracted, run.runtime_content,
        )
        if outcome_error:
            issue_summary.rejected.append(RejectedItem(item=new_issue, reason=outcome_error, category="missing_event_outcome", source=run.ctx.source))
            new_issues.remove(new_issue)
            _extend_bucket(reject_bucket, _suppressed_rows(
                run, event_id, str(new_issue.get("title") or ""),
            ))
            continue
        from ming_sim.simulation import lift_identity_field_aliases

        for raw in run.event_new_armies(event_id):
            if not isinstance(raw, dict):
                continue
            item = lift_identity_field_aliases(raw)
            origin_ref = str(item.get("origin_ref") or "").strip()
            landed, refused = run.db.create_armies_from_extraction(
                run.state, [item], actor="档房", commit=False,
                origin_ref=origin_ref, require_origin=True,
            source=run.ctx.source)
            bucket["new_armies"].extend(landed)
            reject_bucket["new_armies"].extend(refused)
        for region_id, raw_changes in run.ordered_strategic_items("region_delta", event_id):
            if not isinstance(raw_changes, dict):
                continue
            changes = lift_identity_field_aliases(raw_changes)
            origin_ref = str(changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in changes.items() if k != "origin_ref"}
            landed, refused = run.db.apply_region_deltas(
                run.state, run.pseudo_event, None, "档房", {region_id: payload},
                commit=False, origin_ref=origin_ref, require_origin=True,
            source=run.ctx.source)
            bucket["region_changes"].extend(landed)
            reject_bucket["region_changes"].extend(refused)
        for army_id, raw_changes in run.ordered_strategic_items("army_delta", event_id):
            landed, refused = apply_army_delta_with_cannon_transfer(
                run.db, run.state, run.pseudo_event, army_id, raw_changes,
            source=run.ctx.source)
            bucket["army_changes"].extend(landed)
            reject_bucket["army_changes"].extend(refused)
        for item in run.event_person_changes(event_id):
            try:
                origin_ref = run.origin_ref_from_result_item(item)
            except UnauthorizedAffairOriginRef as exc:
                reject_bucket["person_issue"].append(RejectedItem(item=dict(item), reason=str(exc), category="unauthorized_affair_origin", source=run.ctx.source))
                continue
            results, refused = run.land_person_item(
                dict(item),
                origin_ref=origin_ref,
                require_origin=True,
            )
            bucket["person_issue"].extend(results)
            reject_bucket["person_issue"].extend(refused)
        for power_id, raw_changes in run.ordered_strategic_items("power_updates", event_id):
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            landed, refused = run.db.apply_power_deltas(
                run.state, {power_id: payload}, commit=False,
                origin_ref=origin_ref, require_origin=True,
            source=run.ctx.source)
            bucket["power"].extend(landed)
            reject_bucket["power"].extend(refused)
        run.db.mark_event_triggered(
            run.state, event_id, terminal_reason=outcome_label, commit=False,
        )
        apply_event_cascading_invalidations(run.state, run.db)
        new_issue["reason"] = "事件已记为触发，软判结果已落主账"
        from ming_sim.settlement.run import apply_deferred_event_fields
        apply_deferred_event_fields(run, event_id, issue_summary)
    return {
        name: SectionResult(applied=bucket.get(name, []), rejected=reject_bucket.get(name, []))
        for name in bucket.keys() | reject_bucket.keys()
        if bucket.get(name) or reject_bucket.get(name)
    }
