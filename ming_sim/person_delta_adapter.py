"""Normalize ADR 0009 person deltas into the single 人物变更 stream."""

from __future__ import annotations

from typing import Mapping


PERSON_CHANGE_KEY = "人物变更"
# Effect payload carriers, shared by the engine readers and material projection.
PERSON_EFFECT_KEYS = (PERSON_CHANGE_KEY, "person_changes", "character")
ACTION_KEY = "动作"
LEGACY_SPILLOVER = "appointments（朝臣 spillover）"


def _copy_with_action_key(item: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(item)
    if "action" in normalized and ACTION_KEY not in normalized:
        normalized[ACTION_KEY] = normalized.pop("action")
    return normalized


def _dict_items(raw: object) -> list[Mapping[str, object]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _copy_present(item: Mapping[str, object], *keys: str) -> dict[str, object]:
    return {key: item[key] for key in keys if key in item}


def _appointment_to_person_change(
    item: Mapping[str, object],
) -> dict[str, object]:
    return {
        "name": item.get("name", ""),
        ACTION_KEY: "任命",
        "office": item.get("office", ""),
        **_copy_present(
            item, "office_type", "faction", "reason", "origin_ref",
            "region_id", "任所", "辖区",
        ),
        "legacy_spillover": LEGACY_SPILLOVER,
    }


def _status_to_person_change(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": item.get("name", ""),
        ACTION_KEY: "处置",
        **_copy_present(item, "status", "reason_code", "reason", "origin_ref"),
        "legacy_gate": True,
    }


def _power_to_person_change(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": item.get("name", ""),
        ACTION_KEY: "易主",
        "new_power": item.get("new_power", ""),
        "方式": "不明",
        "反噬": {},
        **_copy_present(item, "reason", "origin_ref"),
        "legacy_partial": True,
    }


def _office_to_person_change(item: Mapping[str, object]) -> dict[str, object]:
    translated = {
        "name": item.get("name", ""),
        ACTION_KEY: "任命",
        "office": item.get("new_office", ""),
        **_copy_present(
            item, "faction", "reason", "origin_ref",
            "region_id", "任所", "辖区",
        ),
    }
    if "new_office_type" in item:
        translated["office_type"] = item["new_office_type"]
    return translated


def normalize_person_changes(extracted: Mapping[str, object]) -> list[dict[str, object]]:
    """Return ADR 0009 person changes from new or legacy person delta keys."""
    raw_items = extracted.get(PERSON_CHANGE_KEY)
    if isinstance(raw_items, list) and raw_items:
        return [
            _copy_with_action_key(item)
            for item in raw_items
            if isinstance(item, Mapping)
        ]

    changes: list[dict[str, object]] = []
    appointment_spillover: list[dict[str, object]] = []
    for item in _dict_items(extracted.get("appointments")):
        if str(item.get("office_type") or "").strip() != "后宫":
            appointment_spillover.append(_appointment_to_person_change(item))

    changes.extend(
        _status_to_person_change(item)
        for item in _dict_items(extracted.get("character_status_changes"))
    )
    changes.extend(
        _power_to_person_change(item)
        for item in _dict_items(extracted.get("character_power_changes"))
    )
    changes.extend(
        _office_to_person_change(item)
        for item in _dict_items(extracted.get("office_changes"))
    )
    changes.extend(appointment_spillover)
    return changes
