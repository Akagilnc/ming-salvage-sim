"""Canonical read projection for persisted participant rosters."""

from __future__ import annotations

import json


def participant_roster_names(raw: object) -> set[str]:
    """Project persisted dict roster entries to their character names."""
    try:
        roster = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(roster, list):
        return set()
    return {
        str(item.get("character_id") or item.get("name"))
        for item in roster
        if isinstance(item, dict) and (item.get("character_id") or item.get("name"))
    }
