"""案卷名册追加。公开与密令两路共用流程，字段与权威集合仍由调用方分开。"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ming_sim.applier import Provenance, RejectedItem


def apply_dossier_participant_items(
    db,
    state,
    extracted: Dict[str, object],
    *,
    source: Provenance,
    items_key: str,
    authority_set: set,
    not_in_batch_msg: str,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """追加参与人。权威集合缺省即空闭集，不从活库回推，两路集合不并。"""
    from ming_sim.strict_types import _parse_sqlite_id

    results: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    if not isinstance(authority_set, set):
        authority_set = set()
    for item in extracted.get(items_key) or []:
        if not isinstance(item, dict):
            rejections.append(RejectedItem(
                item={"raw_value": item},
                reason="参与人名册项须为对象",
                category="invalid_shape",
                source=source,
            ))
            continue
        try:
            dossier_id = _parse_sqlite_id(item.get("dossier_id"))
            if dossier_id not in authority_set:
                raise ValueError(not_in_batch_msg)
            character_id = str(item.get("character_id") or "").strip()
            delegator_id = str(item.get("delegator_id") or "").strip()
            tier = str(item.get("tier") or "").strip()
            role = str(item.get("role") or "")
            if not character_id:
                raise ValueError("追加参与人物不能为空")
            if tier not in {"主办", "协办", "知情"}:
                raise ValueError("追加参与层级必须为主办/协办/知情")
            if not delegator_id:
                raise ValueError("追加参与人必须注明委派人")
        except (TypeError, ValueError) as exc:
            rejections.append(RejectedItem(
                item=item,
                reason=str(exc),
                category="invalid_participant_roster",
                source=source,
            ))
            continue
        added = db.append_decree_dossier_participants(dossier_id, [{
            "character_id": character_id,
            "tier": tier,
            "role": role,
            "delegator_id": delegator_id,
        }], commit=False)
        if not added:
            existing = db.dossiers.get(dossier_id) or {}
            roster = existing.get("participant_roster") or []
            if not any(
                row.get("character_id") == character_id
                and row.get("tier") == tier
                and row.get("role") == role
                and row.get("delegator_id") == delegator_id
                for row in roster
            ):
                rejections.append(RejectedItem(
                    item=item,
                    reason="参与人未实际加入案卷",
                    category="invalid_participant_roster",
                    source=source,
                ))
                continue
        persisted = added[0] if added else {
            "character_id": character_id, "tier": tier,
        }
        results.append({
            "dossier_id": dossier_id,
            "character_id": persisted["character_id"],
            "tier": persisted["tier"],
        })
    return results, rejections
