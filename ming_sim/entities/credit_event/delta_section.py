"""信用事件段（#628 / 0079）。

**位置纪律**：写端必须后置于各段校验落格之后，只消费**未 rejected** 的落格项
——禁为被拒的 fulfilled / 人事立伪信用档。故本段排在登记表末段。

被拒项的求差在本段一处做：财政/经济段的落格摘要会丢 ``purpose``/``issue_id``，
故对拒收项（带 ``item``＝源对象）求差、保留源项叙事字段供识别，且不把被拒项
喂进信用写端。此即「单一保护点在落库层」——信用段不再二次过滤。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import SectionResult, section_from_rows


def _placed(run, *names: str) -> SectionResult:
    acc = SectionResult(applied=[], rejected=[])
    for name in names:
        found = run.outcomes.get(name)
        if found is not None:
            acc = acc.merge(found)
    return acc


def _source_minus_rejections(originals: object, rejected) -> List[Dict[str, object]]:
    """源项减去被拒项（按对象同一性，非字段相等）。"""
    rejected_obj_ids = {
        id(item.item) for item in rejected
        if isinstance(getattr(item, "item", None), dict)
    }
    out: List[Dict[str, object]] = []
    for item in originals or []:
        if not isinstance(item, dict) or id(item) in rejected_obj_ids:
            continue
        out.append(item)
    return out


def _resolution_rows(resolutions) -> List[Dict[str, object]]:
    if isinstance(resolutions, dict):
        rows: List[Dict[str, object]] = []
        for key in ("fulfillment", "dispositions", "urge"):
            for row in resolutions.get(key) or []:
                if isinstance(row, dict):
                    rows.append(row)
        return rows
    return [row for row in (resolutions or []) if isinstance(row, dict)]


def apply(run):
    from ming_sim.credit_events import resolve_credit_events_from_extraction

    person = _placed(run, "person_pre", "person_issue", "person_post")
    issue = run.issue_result
    credit_applied: Dict[str, object] = {
        "dossier_executions": _source_minus_rejections(
            run.current_extracted.get("dossier_executions"),
            _placed(run, "dossier_executions").rejected,
        ),
        "人物变更": [
            row for row in person.applied
            if isinstance(row, dict) and not row.get("rejected") and not row.get("cascade_echo")
        ],
        "economy_moves": _source_minus_rejections(
            run.current_extracted.get("economy_moves"),
            _placed(run, "economy").rejected,
        ),
        "fiscal_creates": _source_minus_rejections(
            run.current_extracted.get("fiscal_creates"),
            _placed(run, "fiscal_creates").rejected,
        ),
        "fiscal_changes": _source_minus_rejections(
            run.current_extracted.get("fiscal_changes"),
            _placed(run, "fiscal_changes").rejected,
        ),
        "cancels": list(issue.cancels) if issue is not None else [],
    }
    resolutions = resolve_credit_events_from_extraction(
        run.db, run.state, credit_applied, commit=False,
    )
    return section_from_rows(
        _resolution_rows(resolutions), run.ctx.source,
        category="credit_event_resolutions",
    )
