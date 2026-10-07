"""Normalize ADR 0009 person deltas into the single 人物变更 stream."""

from __future__ import annotations

from typing import Mapping


PERSON_CHANGE_KEY = "人物变更"
ACTION_KEY = "动作"


def _copy_with_action_key(item: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(item)
    if "action" in normalized and ACTION_KEY not in normalized:
        normalized[ACTION_KEY] = normalized.pop("action")
    return normalized


def normalize_person_changes(extracted: Mapping[str, object]) -> list[dict[str, object]]:
    """Return ADR 0009 person changes from the canonical 人物变更 key only."""
    raw_items = extracted.get(PERSON_CHANGE_KEY)
    if not isinstance(raw_items, list):
        return []
    return [
        _copy_with_action_key(item)
        for item in raw_items
        if isinstance(item, Mapping)
    ]
