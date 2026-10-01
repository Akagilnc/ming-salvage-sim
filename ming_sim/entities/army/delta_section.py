"""军队落库段：``new_armies``（建军）与 ``army_delta``（既有军字段变动）。

两条按登记表分列登记，因为顺序约束不同且各自可被战略事件归属门闩整组压制：
建军必须先于 ``army_delta``，否则同回合引用新军的变动会被跳过（查无此军）。
"""

from __future__ import annotations

from typing import List

from ming_sim.applier import section_from_rows
from ming_sim.issues import (
    ARMY_FIELD_ALIASES,
    _effect_event_ids,
    _strict_int,
    latched_army_field_effect_permitted,
)


def apply_new_armies(run, items: List[object] | None = None):
    """建军。归属战略事件的项不在此落——由局势段在事件触发时物化。"""
    if items is None:
        items = list(run.current_extracted.get("new_armies") or [])
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if run.declared_new_army_event_by_item.get(id(item), "") in run.strategic_event_referenced_ids:
            continue
        origin_ref = str(item.get("origin_ref") or "").strip()
        rows.extend(run.db.create_armies_from_extraction(
            run.state, [item], actor="档房", commit=False,
            origin_ref=origin_ref, require_origin=True,
        ))
    return section_from_rows(rows, run.ctx.source, category="army_changes")


def apply_deltas(run):
    """既有军字段变动。随军炮转移是双边写，故走同模块的
    :func:`apply_army_delta_with_cannon_transfer`。"""
    rows = []
    for index, (army_id, raw_changes) in enumerate(
        run.current_ordered.get("army_delta") or []
    ):
        if _effect_event_ids(
            "army_delta", index, run.strategic_event_referenced_ids,
            run.current_event_ids,
        ):
            continue
        rows.extend(apply_army_delta_with_cannon_transfer(
            run.db, run.state, run.pseudo_event, army_id, raw_changes,
        ))
    return section_from_rows(rows, run.ctx.source, category="army_changes")

def apply_army_delta_with_cannon_transfer(
    db: GameDB, state: GameState, pseudo_event: Event, army_id: str,
    raw_changes: Dict[str, object],
) -> List[Dict[str, object]]:
    """Apply one extracted army item, including an explicit paired cannon transfer."""
    army_changes: List[Dict[str, object]] = []
    origin_ref = str(raw_changes.get("origin_ref") or "").strip()
    payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
    if "cannon_transfer_to" in payload:
        target_id = payload.pop("cannon_transfer_to")
        cannon_keys = [k for k in payload if ARMY_FIELD_ALIASES.get(k, k) == "cannon_equipment"]
        try:
            requested = _strict_int(payload[cannon_keys[0]]) if len(cannon_keys) == 1 else 0
        except (TypeError, ValueError):
            requested = 0
        source = db.conn.execute(
            "SELECT cannon_equipment, is_mutinied FROM armies WHERE id=?", (army_id,)
        ).fetchone()
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            army_changes.append({"army_id": army_id, **origin_error,
                                 "item": {"army_id": army_id, "changes": raw_changes}})
            return army_changes
        target = (db.conn.execute(
            "SELECT cannon_equipment, is_mutinied FROM armies WHERE id=?", (target_id,)
        ).fetchone() if isinstance(target_id, str) and target_id else None)
        if (len(cannon_keys) != 1 or requested >= 0 or source is None
                or target is None or target_id == army_id):
            army_changes.append({
                "army_id": army_id, "rejected": True,
                "category": "missing_ref" if source is None or target is None else "invalid_enum",
                "reason": "随军炮转移须指定在册来源、去向及负数拟转量",
                "item": {"army_id": army_id, "changes": raw_changes},
            })
            return army_changes
        for key in cannon_keys:
            payload.pop(key)
        writable = all(
            not bool(row["is_mutinied"]) or latched_army_field_effect_permitted(
                "cannon_equipment", delta,
            )
            for row, delta in ((source, requested), (target, -requested))
        )
        actual = (min(-requested, int(source["cannon_equipment"]),
                      12 - int(target["cannon_equipment"])) if writable else 0)
        if actual > 0:
            db.conn.execute("SAVEPOINT cannon_transfer")
            try:
                transfer_changes: List[Dict[str, object]] = []
                for leg_id, leg_delta in ((army_id, -actual), (target_id, actual)):
                    leg_changes = db.apply_army_deltas(
                        state, pseudo_event, None, "档房",
                        {leg_id: {"随军大炮": leg_delta, "reason": raw_changes.get("reason")}},
                        commit=False, origin_ref=origin_ref, require_origin=True,
                    )
                    if len(leg_changes) != 1 or leg_changes[0].get("delta") != leg_delta:
                        raise RuntimeError("随军炮转移双边实数不等")
                    transfer_changes.extend(leg_changes)
                db.conn.execute("RELEASE SAVEPOINT cannon_transfer")
            except Exception:
                db.conn.execute("ROLLBACK TO SAVEPOINT cannon_transfer")
                db.conn.execute("RELEASE SAVEPOINT cannon_transfer")
                raise
            army_changes.extend(transfer_changes)
        else:
            for leg_id in (army_id, target_id):
                army_changes.append({
                    "army_id": leg_id, "field": "cannon_equipment",
                    "delta": 0, "applied": False, "reason": raw_changes.get("reason"),
                })
    army_changes.extend(db.apply_army_deltas(
        state, pseudo_event, None, "档房", {army_id: payload}, commit=False, origin_ref=origin_ref, require_origin=True,
    ))

    return army_changes
