"""暗渠旧案财政效果一次性撤销：由 issues.py 清算迁入（ADR 0150 决定 8）。"""

from __future__ import annotations


from typing import Any


_COVERT_NEUTRALIZATION_REASON = "禁摊派：一次性撤销旧案暗渠财政效果"


def neutralize_covert_fiscal_effects(
    db: Any,
    state: Any,
    *,
    exposed_dossier_id: int,
    prohibition_dossier_id: int,
) -> int:
    """Undo one old case's beyond-intent fiscal contribution, once per live incarnation."""
    old_origin = f"dossier:{int(exposed_dossier_id)}"
    receipt_origin = f"dossier:{int(prohibition_dossier_id)}"
    rows = db.fiscal_config.effects_for_dossier(int(exposed_dossier_id))
    raw_keys = {
        str(row.get("key") or "").strip() for row in rows if row.get("beyond_intent")
    }
    keys: set[str] = set()
    for raw_key in raw_keys:
        stem = db._stem_of(raw_key)
        if not stem:
            continue
        if raw_key.endswith(("_base", "_rate")):
            keys.add(raw_key)
        else:
            keys.add(f"{stem}_base")

    written = 0
    for key in sorted(keys):
        stem = db._stem_of(key)
        base_key, rate_key = f"{stem}_base", f"{stem}_rate"
        receipt = db.fiscal_config.read_neutralize_covert_fiscal_effects(
            (receipt_origin, key, _COVERT_NEUTRALIZATION_REASON)
        )
        if receipt is None:
            receipt = db.fiscal_config.read_neutralize_covert_fiscal_effects_fiscal_config_tombstones_2(
                (receipt_origin, base_key, rate_key, _COVERT_NEUTRALIZATION_REASON)
            )
        if receipt is not None:
            continue

        current = db.fiscal_config.values().get(key)
        if current is None:
            continue
        latest_remove = db.fiscal_config.read_neutralize_covert_fiscal_effects_fiscal_config_tombstones((key,))
        latest_create = db.fiscal_config.read_neutralize_covert_fiscal_effects_fiscal_config_creations((key,))
        remove_mark = (
            (int(latest_remove["turn"]), 0, int(latest_remove["id"]))
            if latest_remove
            else (-1, -1, -1)
        )
        create_mark = (
            (int(latest_create["turn"]), 1, int(latest_create["id"]))
            if latest_create
            else (-1, -1, -1)
        )
        start = max(remove_mark, create_mark)

        if (
            latest_create is not None
            and create_mark > remove_mark
            and str(latest_create["origin_ref"]) == old_origin
            and bool(db.coerce_beyond_intent_flag(latest_create["beyond_intent"]))
        ):
            if key != base_key:
                continue
            if (
                db.remove_fiscal_item(
                    key,
                    commit=False,
                    origin_ref=receipt_origin,
                    reason=_COVERT_NEUTRALIZATION_REASON,
                    turn=int(state.turn),
                )
                is not None
            ):
                written += 1
            continue

        contribution = 0
        for row in db.fiscal_config.changes_for(key, old_origin):
            mark = (int(row["turn"]), 2, int(row["id"]))
            if mark > start and bool(
                db.coerce_beyond_intent_flag(row["beyond_intent"])
            ):
                contribution += int(row["delta"])
        floor = db.fiscal_config_minimum_value(key) or 0
        new_value = max(int(floor), int(current) - max(0, contribution))
        from ming_sim.entities.fiscal.config_writer import _write_fiscal_config_change

        _write_fiscal_config_change(
            db,
            turn=int(state.turn),
            key=key,
            old_value=int(current),
            new_value=new_value,
            origin_ref=receipt_origin,
            reason=_COVERT_NEUTRALIZATION_REASON,
        )
        written += 1
    return written
