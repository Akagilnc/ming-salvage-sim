"""委任授权（``authority_changes``）落库段。

授予/收权先做无写校验，校验失败才归成拒收项。写库在 catch 之外，
写后故障由外层事务回滚。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

from typing import Dict, List

from ming_sim.applier import SectionResult

# 与落地核同义的失败原因 → 拒收类别（供机读聚合；其余归 invalid_authority_change）。
_KNOWN_CATEGORIES = frozenset({
    "missing_dossier_source",
    "dossier_not_effect_eligible",
    "duplicate_active_authority",
    "invalid_authority_scope",
    "unknown_authority_id",
    "already_revoked",
})


def apply(run):
    from ming_sim.issues import (
        _prepare_authority_change_item,
        _write_authority_change_item,
    )

    results: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    for item in run.current_extracted.get("authority_changes") or []:
        if not isinstance(item, dict):
            rejections.append(RejectedItem(item=item, reason="授权变更项必须为对象", category="invalid_shape", source=run.ctx.source))
            continue
        try:
            prepared = _prepare_authority_change_item(run.db, run.state, item)
        except ValueError as exc:
            reason = str(exc)
            rejections.append(RejectedItem(item=item, reason=reason, category=reason if reason in _KNOWN_CATEGORIES
                else "invalid_authority_change", source=run.ctx.source))
            continue
        applied = prepared.get("applied")
        if applied is None:
            applied = _write_authority_change_item(run.db, run.state, prepared)
        results.append(applied)
    return SectionResult(applied=results, rejected=rejections)
