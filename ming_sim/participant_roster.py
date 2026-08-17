"""Canonical read projection for persisted participant rosters."""

from __future__ import annotations

import json
from typing import Dict, List


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


def project_execution_liability_parties(
    roster: object,
) -> List[Dict[str, object]]:
    """#565 连坐责任投影：主办→primary；主办/协办行 delegator_id 一级→secondary。

    同构 breach_decree_dossier 双处收集：协办本人零机械只作戏源，
    但其委派人仍次责（ADR 0053：大臣遣学生为协办办砸→全权者背锅）。
    先定档后去重：同一人 primary 胜 secondary；知情永不入。
    写路与 list_execution_liability_parties 共用本函数，禁止第二份 roster 遍历。
    """
    if not isinstance(roster, list):
        return []

    primary_ids: List[str] = []
    seen_primary: set[str] = set()
    for item in roster:
        if not isinstance(item, dict) or item.get("tier") != "主办":
            continue
        lead = str(item.get("character_id") or "").strip()
        if lead and lead not in seen_primary:
            seen_primary.add(lead)
            primary_ids.append(lead)

    secondary_ids: List[str] = []
    seen_secondary: set[str] = set()
    for item in roster:
        if not isinstance(item, dict) or item.get("tier") not in {"主办", "协办"}:
            continue
        delegator = str(item.get("delegator_id") or "").strip()
        if (
            delegator
            and delegator not in seen_primary
            and delegator not in seen_secondary
        ):
            seen_secondary.add(delegator)
            secondary_ids.append(delegator)

    parties: List[Dict[str, object]] = [
        {
            "character_id": lead,
            "responsibility": "primary",
            "tier": "主办",
        }
        for lead in primary_ids
    ]
    parties.extend(
        {
            "character_id": delegator,
            "responsibility": "secondary",
            "tier": "delegator",
        }
        for delegator in secondary_ids
    )
    return parties
