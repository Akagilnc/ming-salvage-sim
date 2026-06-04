"""Steam event payload helpers for the web/Electron bridge."""

from __future__ import annotations

from typing import Any, Dict, List


STAT_RUNS_STARTED = "STAT_RUNS_STARTED"
STAT_TURNS_PLAYED = "STAT_TURNS_PLAYED"
STAT_DECREES_ISSUED = "STAT_DECREES_ISSUED"
STAT_SAVES_CREATED = "STAT_SAVES_CREATED"
STAT_ENDINGS_REACHED = "STAT_ENDINGS_REACHED"
STAT_MAX_TURN_REACHED = "STAT_MAX_TURN_REACHED"


def add_stat(name: str, delta: int = 1) -> Dict[str, Any]:
    return {"type": "add_stat_int", "name": name, "delta": int(delta)}


def set_stat(name: str, value: int) -> Dict[str, Any]:
    return {"type": "set_stat_int", "name": name, "value": int(value)}


def with_events(payload: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    if events:
        payload["steam_events"] = events
    return payload
