"""信用事件段（#628 / 0079）。

**位置纪律**：写端必须后置于各段校验落格之后，只消费**未 rejected** 的落格项
——禁为被拒的 fulfilled / 人事立伪信用档。故本段排在登记表末段。

被拒项的求差在本段一处做：财政/经济段的落格摘要会丢 ``purpose``/``issue_id``，
故对拒收项（带 ``item``＝源对象）求差、保留源项叙事字段供识别，且不把被拒项
喂进信用写端。此即「单一保护点在落库层」——信用段不再二次过滤。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import SectionResult


def _source_minus_rejections(
    originals: object, rejections: object,
) -> List[Dict[str, object]]:
    """源项减去被拒项（按对象同一性，非字段相等）。"""
    rejected_obj_ids = {
        id(r.get("item"))
        for r in (rejections or [])
        if isinstance(r, dict) and isinstance(r.get("item"), dict)
    }
    out: List[Dict[str, object]] = []
    for item in originals or []:
        if not isinstance(item, dict) or id(item) in rejected_obj_ids:
            continue
        out.append(item)
    return out


def apply(run) -> SectionResult:
    from ming_sim.credit_events import resolve_credit_events_from_extraction

    issue_sum = run.issue_summary if isinstance(run.issue_summary, dict) else {}
    credit_applied: Dict[str, object] = {
        # 返回契约仅 {dossier_id, outcome}；兑付语境承接 extracted 源项（含 note）
        # minus 被拒项，与 economy_moves 同形，禁外溢返回契约。
        "dossier_executions": _source_minus_rejections(
            run.current_extracted.get("dossier_executions"), run.dossier_execution_results,
        ),
        # cascade_echo：合成级联回声（放归/被顶替等）在生产点打标，此处唯一滤除；
        # 禁在 credit_events 另设第二闸或盯 derived_from 文本。
        "人物变更": [
            r for r in run.applied_person_changes
            if isinstance(r, dict) and not r.get("rejected") and not r.get("cascade_echo")
        ],
        "economy_moves": _source_minus_rejections(
            run.current_extracted.get("economy_moves"), run.economy_rejections,
        ),
        "fiscal_creates": _source_minus_rejections(
            run.current_extracted.get("fiscal_creates"),
            [r for r in run.applied_fiscal_creates
             if isinstance(r, dict) and r.get("rejected")],
        ),
        "fiscal_changes": _source_minus_rejections(
            run.current_extracted.get("fiscal_changes"),
            [r for r in run.applied_fiscal
             if isinstance(r, dict) and r.get("rejected")],
        ),
        "cancels": [
            r for r in (issue_sum.get("cancels") or [])
            if isinstance(r, dict) and not r.get("rejected")
        ],
    }
    run.credit_event_resolutions = resolve_credit_events_from_extraction(
        run.db, run.state, credit_applied, commit=False,
    )
    return SectionResult(applied=[], rejected=[])
