"""委任授权（``authority_changes``）落库段。

授予/收权走既有 ``_apply_authority_change_item`` 单一落地核；本段只负责把失败
按真实原因归类成拒收项——分类口径集中在此，拒收类别不拿宽 catch 统一冒称。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import section_from_rows

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
    from ming_sim.issues import _apply_authority_change_item

    results: List[Dict[str, object]] = []
    for item in run.current_extracted.get("authority_changes") or []:
        if not isinstance(item, dict):
            results.append({
                "rejected": True, "category": "invalid_shape", "item": item,
                "reason": "授权变更项必须为对象",
            })
            continue
        try:
            results.append(_apply_authority_change_item(run.db, run.state, item))
        except ValueError as exc:
            reason = str(exc)
            results.append({
                "rejected": True,
                "category": reason if reason in _KNOWN_CATEGORIES
                else "invalid_authority_change",
                "reason": reason, "item": item,
            })
    return section_from_rows(results, run.ctx.source, category="authority_changes")
