"""财政配置变更的唯一写核。调用方拥有事务。"""
from __future__ import annotations

from typing import Any

def _write_fiscal_config_change(
    db: Any, *, turn: int, key: str, old_value: int, new_value: int,
    origin_ref: str, reason: str, beyond_intent: object = 0,
) -> None:
    """Canonical fiscal change writer shared by extraction and prohibition rollback."""
    db.validate_fiscal_config_value(key, new_value)
    db.set_fiscal_config(key, new_value, commit=False)
    db.fiscal_config.set_origin(key, origin_ref)
    db.fiscal_config.record_change(
        turn=turn, key=key, old_value=old_value, new_value=new_value,
        origin_ref=origin_ref, reason=reason, beyond_intent=beyond_intent,
    )
    stem = db._stem_of(key)
    if stem in db._SIDE_CHANNEL_REGION_FIELD:
        ratio = (new_value / old_value) if old_value > 0 else (1.0 if new_value == 0 else 0.0)
        db.apply_dynamic_fiscal_scale(stem, ratio, commit=False)
