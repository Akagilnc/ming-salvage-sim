"""人物行程领域规则：语气枚举、启程准入、距离与速度。

人物实体拥有此单一实现；编排层与召对消费者从此取用，不反向依赖 settlement。
"""

from __future__ import annotations

import math
from typing import Dict, Optional

from ming_sim.db import GameDB
from ming_sim.distance import DistanceMatrix
from ming_sim.exceptions import DeclarationDataError
from ming_sim.paths import bundled_path


TRAVEL_SPEED_BY_TONE = {"常行": 1.0, "加急": 1.5, "星夜兼程": 2.0}


def load_valid_regions(db: GameDB) -> set[str]:
    return {
        str(row["id"])
        for row in db.regions.read_load_pending_gate_valid_regions(())
    }


def normalize_travel_tone(value: object) -> str:
    """Validate the canonical typed travel tone; never infer or downgrade it."""
    tone = "常行" if value is None else str(value).strip()
    if tone not in TRAVEL_SPEED_BY_TONE:
        raise DeclarationDataError("行程语气不在闭合枚举")
    return tone


def admit_transit_departure(
    item: Dict[str, object],
    row: Dict[str, object],
    valid_regions: set[str],
) -> tuple[Optional[Dict[str, object]], Optional[tuple[str, str]]]:
    """Return the canonical, write-free departure projection or its item rejection."""
    if "location" in item:
        return None, ("行止只接受 transit_to 启程", "invalid_transition")
    transit_to = str(item.get("transit_to") or "").strip()
    if not transit_to:
        return None, ("transit_to 缺失", "missing_field")
    if str(row.get("status") or "active") != "active":
        return None, ("行止 仅适用于 active 人物", "invalid_transition")
    if transit_to not in valid_regions:
        return None, ("transit_to 地区不存在", "missing_ref")
    try:
        tone = normalize_travel_tone(item.get("行程语气"))
    except DeclarationDataError as exc:
        return None, (str(exc), "invalid_enum")
    previous_destination = str(row.get("transit_to") or "")
    if previous_destination and previous_destination != transit_to:
        return None, ("在途人物不可改道", "invalid_transition")
    location = str(row.get("location") or "")
    if location not in valid_regions:
        return None, None
    matrix = DistanceMatrix.from_file(bundled_path("content", "distance_matrix.json"))
    distance = matrix.travel_time(location, transit_to)
    if not math.isfinite(distance) or distance < 0 or (location != transit_to and distance <= 0):
        raise ValueError(f"invalid baked travel time: {location!r} -> {transit_to!r}")
    terminal_location = transit_to if distance == 0 else location
    terminal_transit_to = "" if distance == 0 else transit_to
    return {
        "location": terminal_location,
        "transit_to": terminal_transit_to,
        "distance": distance,
        "tone": tone,
        "speed": None if distance == 0 else TRAVEL_SPEED_BY_TONE[tone],
        "material": (
            terminal_location != location
            or terminal_transit_to != previous_destination
        ),
    }, None
