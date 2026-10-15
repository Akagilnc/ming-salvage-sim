"""军队落库段：``new_armies``（建军）与 ``army_delta``（既有军字段变动）。

两条按登记表分列登记，因为顺序约束不同且各自可被战略事件归属门闩整组压制：
建军必须先于 ``army_delta``，否则同回合引用新军的变动会被跳过（查无此军）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState, Event

from ming_sim.applier import SectionResult
from ming_sim.constants import ARMY_FIELD_ALIASES
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.db import latched_army_field_effect_permitted
from ming_sim.settlement.preflight import _effect_event_ids


def apply_new_armies(run, items: List[object] | None = None):
    """建军。归属战略事件的项不在此落——由局势段在事件触发时物化。"""
    if items is None:
        items = list(run.current_extracted.get("new_armies") or [])
    rows = []
    rejections = []
    from ming_sim.constants import ARMY_FIELD_ALIASES
    from ming_sim.simulation import normalize_item_keys

    for raw in items:
        if not isinstance(raw, dict):
            continue
        # id(raw) 是战略事件归属真源；身份槽走 ITEM，领域键走 ARMY（势力→owner_power）。
        if run.declared_new_army_event_by_item.get(id(raw), "") in run.strategic_event_referenced_ids:
            continue
        item = normalize_item_keys(raw, domain_aliases=ARMY_FIELD_ALIASES)
        origin_ref = str(item.get("origin_ref") or "").strip()
        landed, refused = run.db.create_armies_from_extraction(
            run.state, [item], actor="档房", commit=False,
            origin_ref=origin_ref, require_origin=True,
        source=run.ctx.source,)
        rows.extend(landed)
        rejections.extend(refused)
    return SectionResult(applied=rows, rejected=rejections)


def apply_deltas(run):
    """既有军字段变动。随军炮转移是双边写，故走同模块的
    :func:`apply_army_delta_with_cannon_transfer`。"""
    rows = []
    rejections = []
    for index, (army_id, raw_changes) in enumerate(
        run.current_ordered.get("army_delta") or []
    ):
        if _effect_event_ids(
            "army_delta", index, run.strategic_event_referenced_ids,
            run.current_event_ids,
        ):
            continue
        landed, refused = apply_army_delta_with_cannon_transfer(
            run.db, run.state, run.pseudo_event, army_id, raw_changes,
        source=run.ctx.source,)
        rows.extend(landed)
        rejections.extend(refused)
    return SectionResult(applied=rows, rejected=rejections)

def apply_army_delta_with_cannon_transfer(
    db: GameDB, state: GameState, pseudo_event: Event, army_id: str,
    raw_changes: Dict[str, object],
    source: Provenance = Provenance.system_simulation,
    *,
    origin_ref: str | None = None,
    actor: str = "档房",
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """Apply one extracted army item, including an explicit paired cannon transfer."""
    army_changes: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    from ming_sim.simulation import lift_identity_field_aliases

    changes = lift_identity_field_aliases(raw_changes) if isinstance(raw_changes, dict) else {}
    if origin_ref is None:
        origin_ref = str(changes.get("origin_ref") or "").strip()
    payload = {k: v for k, v in changes.items() if k != "origin_ref"}
    if "cannon_transfer_to" in payload:
        target_id = payload.pop("cannon_transfer_to")
        cannon_keys = [k for k in payload if ARMY_FIELD_ALIASES.get(k, k) == "cannon_equipment"]
        try:
            requested = _strict_int(payload[cannon_keys[0]]) if len(cannon_keys) == 1 else 0
        except ValueError as exc:
            rejections.append(RejectedItem(
                item={"army_id": army_id, "changes": raw_changes},
                reason=str(exc), category="invalid_enum", source=source,
            ))
            return army_changes, rejections
        source_row = db.armies.row(army_id, fields="cannon_equipment, is_mutinied")
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejections.append(RejectedItem(item={"army_id": army_id, "changes": raw_changes}, reason=origin_error["reason"], category=origin_error["category"], source=source))
            return army_changes, rejections
        target = (
            db.armies.row(target_id, fields="cannon_equipment, is_mutinied")
            if isinstance(target_id, str) and target_id
            else None
        )
        if (len(cannon_keys) != 1 or requested >= 0 or source_row is None
                or target is None or target_id == army_id):
            rejections.append(RejectedItem(item={"army_id": army_id, "changes": raw_changes}, reason="随军炮转移须指定在册来源、去向及负数拟转量", category="missing_ref" if source_row is None or target is None else "invalid_enum", source=source))
            return army_changes, rejections
        for key in cannon_keys:
            payload.pop(key)
        writable = all(
            not bool(row["is_mutinied"]) or latched_army_field_effect_permitted(
                "cannon_equipment", delta,
            )
            for row, delta in ((source_row, requested), (target, -requested))
        )
        actual = (min(-requested, int(source_row["cannon_equipment"]),
                      12 - int(target["cannon_equipment"])) if writable else 0)
        if actual > 0:
            transfer_changes: List[Dict[str, object]] = []
            for leg_id, leg_delta in ((army_id, -actual), (target_id, actual)):
                leg_changes, leg_rejections = db.apply_army_deltas(
                    state, pseudo_event, None, actor,
                    {leg_id: {"随军大炮": leg_delta, "reason": raw_changes.get("reason")}},
                    commit=False, origin_ref=origin_ref, require_origin=True,
                source=source,)
                rejections.extend(leg_rejections)
                if len(leg_changes) != 1 or leg_changes[0].get("delta") != leg_delta:
                    raise RuntimeError("随军炮转移双边实数不等")
                transfer_changes.extend(leg_changes)
            army_changes.extend(transfer_changes)
        else:
            for leg_id in (army_id, target_id):
                army_changes.append({
                    "army_id": leg_id, "field": "cannon_equipment",
                    "delta": 0, "applied": False, "reason": raw_changes.get("reason"),
                })
    landed, refused = db.apply_army_deltas(
        state, pseudo_event, None, actor, {army_id: payload}, commit=False, origin_ref=origin_ref, require_origin=True,
    source=source,)
    army_changes.extend(landed)
    rejections.extend(refused)

    return army_changes, rejections
