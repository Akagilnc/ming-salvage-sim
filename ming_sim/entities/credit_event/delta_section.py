"""信用事件段（#628 / 0079）。

**位置纪律**：写端必须后置于各段校验落格之后，只消费实际落账的源项。
回执上的 ``source_item`` 指回产生该回执的源对象；``applied is False`` 的
未落地回执不进信用。被拒项不在 applied 里，不再另做拒收求差。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import SectionResult


def _placed(run, *names: str) -> SectionResult:
    acc = SectionResult(applied=[], rejected=[])
    for name in names:
        found = run.outcomes.get(name)
        if found is not None:
            acc = acc.merge(found)
    return acc


def _landed_sources(section: SectionResult) -> List[Dict[str, object]]:
    """实际落地回执上的源项。同一源项的多笔分录只计一次。"""
    seen: set[int] = set()
    out: List[Dict[str, object]] = []
    for row in section.applied:
        if not isinstance(row, dict) or row.get("applied") is False:
            continue
        source = row.get("source_item")
        if not isinstance(source, dict):
            continue
        marker = id(source)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(source)
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
    issue = run.outcomes.get("issue")
    credit_applied: Dict[str, object] = {
        "dossier_executions": _landed_sources(_placed(run, "dossier_executions")),
        "人物变更": [
            row for row in person.applied
            if isinstance(row, dict) and not row.get("cascade_echo")
        ],
        "economy_moves": _landed_sources(_placed(run, "economy")),
        "fiscal_creates": _landed_sources(_placed(run, "fiscal_creates")),
        "fiscal_changes": _landed_sources(_placed(run, "fiscal_changes")),
        "cancels": list(issue.cancels) if issue is not None else [],
    }
    resolutions, rejections = resolve_credit_events_from_extraction(
        run.db, run.state, credit_applied, source=run.ctx.source, commit=False,
    )
    return SectionResult(applied=_resolution_rows(resolutions), rejected=rejections)
