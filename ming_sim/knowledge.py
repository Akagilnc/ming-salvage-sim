"""Per-character knowledge projection (#489).

The projection is deliberately a read model: durable participation/public-event
rows are the source of memory, while the office bucket is rebuilt from current
world state on every read.  That makes a fresh turn useful and keeps restore
free of a second copy of the world state.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable


_OFFICE_BUCKETS = {
    "户部": "treasury", "兵部": "military", "吏部": "personnel",
    "工部": "construction", "礼部": "public", "翰林院": "public",
    "都察院": "public", "内阁": "court", "司礼监": "court",
    "内臣": "court", "锦衣卫": "security", "东厂": "security",
    "边镇": "military", "地方": "regional", "外臣": "regional",
    "未仕": "public", "后宫": "public", "宗藩": "public",
}


def _world(db: Any, state: Any, office_type: str) -> Dict[str, str]:
    bucket = _OFFICE_BUCKETS.get(office_type, "public")
    public = db.get_turn_report(state.turn - 1) if hasattr(db, "get_turn_report") else ""
    values: Dict[str, str] = {"public": public or "登基伊始，朝廷暂无前回合奏报。"}
    if bucket in {"treasury", "court"}:
        values["treasury"] = db.treasury_report(state)
    if bucket in {"military", "regional", "security"}:
        values["military"] = db.army_report(limit=10)
        values["regional"] = db.region_report(limit=10)
    if bucket in {"personnel", "court"}:
        values["personnel"] = db.faction_report()
    if bucket == "construction":
        values["construction"] = db.buildings_report()
    if bucket == "security":
        values["security"] = db.power_report(exclude_self=True)
    # Every office type has a deterministic bucket; generic offices get the
    # public layer plus their own domain rather than an empty/undefined view.
    return {"public": values["public"], bucket: values.get(bucket, values["public"])}


def build_character_knowledge(db: Any, state: Any, character_name: str) -> Dict[str, object]:
    character = db.content.characters.get(character_name) if db.content else None
    office_type = str(getattr(character, "office_type", "") or "")
    world = _world(db, state, office_type)
    events = db._character_knowledge_events(character_name)
    public_events = db._character_knowledge_events("")
    # Issued directives are public by their nature.  Read them here so old
    # saves and the normal decree path need no second write hook.
    for directive in db.list_directives_by_turn(state.turn):
        public_events.append({
            "turn": int(directive["turn"]), "year": int(directive["year"]),
            "period": int(directive["period"]), "kind": "public",
            "title": directive.get("event_title") or "明发旨意",
            "body": directive.get("text") or "",
            "source_id": f"directive:{directive['id']}",
        })
    excluded = set()
    for row in db._character_knowledge_events(character_name, include_exclusions=True):
        excluded.update(json.loads(row.get("excluded_names") or "[]"))
    visible_events = [row for row in events if row["source_id"] not in excluded]
    visible_public = [row for row in public_events if character_name not in json.loads(row.get("excluded_names") or "[]")]
    return {
        "character_name": character_name,
        "office_type": office_type,
        "turn": int(state.turn),
        "world": world,
        "events": visible_events,
        "public_events": visible_public,
    }
