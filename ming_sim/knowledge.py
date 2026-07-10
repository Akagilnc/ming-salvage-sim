"""Per-character knowledge projection (#489).

The projection is deliberately a read model: durable participation/public-event
rows are the source of memory, while the office bucket is rebuilt from current
world state on every read.  That makes a fresh turn useful and keeps restore
free of a second copy of the world state.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


_OFFICE_BUCKETS = {
    "户部": "treasury", "兵部": "military", "吏部": "personnel",
    "工部": "construction", "礼部": "public", "刑部": "public",
    "翰林院": "public", "都察院": "public", "内阁": "court",
    "督抚": "regional", "司礼监": "court",
    "内臣": "court", "锦衣卫": "security", "东厂": "security",
    "边镇": "military", "地方": "regional", "外臣": "regional",
    "未仕": "public", "后宫": "public", "宗藩": "public",
    "内廷": "court", "生员": "public", "乡绅": "public",
    "富商": "public", "布衣": "public", "流寇": "public", "待铨": "public",
}


def _qualitative(text: object) -> str:
    """Render an engine report for a minister without exposing machine values."""
    value = str(text or "")
    # Reports remain useful as labels and prose, but their exact balances, bars,
    # ids, and percentages belong to the judge-side tools, not a character prompt.
    return re.sub(r"[-+]?\d+(?:\.\d+)?%?", "若干", value)


def _world(db: Any, state: Any, office_type: str) -> Dict[str, str]:
    bucket = _OFFICE_BUCKETS.get(office_type, "public")
    reports = db.list_turn_reports() if hasattr(db, "list_turn_reports") else []
    public = "\n".join(_qualitative(r.get("report")) for r in reports)
    values: Dict[str, str] = {"public": public or "登基伊始，朝廷暂无前回合奏报。"}
    if bucket in {"treasury", "court"}:
        values["treasury"] = _qualitative(db.treasury_report(state))
    if bucket in {"military", "regional", "security"}:
        values["military"] = _qualitative(db.army_report(limit=10))
        values["regional"] = _qualitative(db.region_report(limit=10))
    if bucket in {"personnel", "court"}:
        values["personnel"] = _qualitative(db.faction_report())
    if bucket == "construction":
        values["construction"] = _qualitative(db.buildings_report())
    if bucket == "security":
        values["security"] = _qualitative(db.power_report(exclude_self=True))
    # Every office type has a deterministic bucket; generic offices get the
    # public layer plus their own domain rather than an empty/undefined view.
    return {"public": values["public"], bucket: values.get(bucket, values["public"])}


def build_character_knowledge(db: Any, state: Any, character_name: str) -> Dict[str, object]:
    character = db.content.characters.get(character_name) if db.content else None
    office_type = str(getattr(character, "office_type", "") or "")
    world = _world(db, state, office_type)
    events = db._character_knowledge_events(character_name, include_exclusions=True)
    public_events = db._character_knowledge_events("", include_exclusions=True)
    # Issued directives are public by their nature.  Read them here so old
    # saves and the normal decree path need no second write hook.
    for directive in db.list_issued_directives():
        public_events.append({
            "turn": int(directive["turn"]), "year": int(directive["year"]),
            "period": int(directive["period"]), "kind": "public",
            "title": directive.get("event_title") or "明发旨意",
            "body": _qualitative(directive.get("text") or ""),
            "source_id": f"directive:{directive['id']}",
        })
    for report in db.list_turn_reports():
        public_events.append({
            "turn": int(report["turn"]), "year": int(report["year"]),
            "period": int(report["period"]), "kind": "public",
            "title": "邸报", "body": _qualitative(report.get("report")),
            "source_id": f"turn_report:{report['turn']}",
            "excluded_names": "[]",
        })
    def is_excluded(row: Dict[str, object]) -> bool:
        try:
            excluded_names = json.loads(str(row.get("excluded_names") or "[]"))
        except (TypeError, ValueError):
            excluded_names = []
        if character_name in excluded_names:
            return True
        source_id = str(row.get("source_id") or "")
        return character_name in db.knowledge_exclusions_for_source(source_id)

    visible_events = [
        {
            key: (_qualitative(value) if key == "body" else value)
            for key, value in row.items() if key != "excluded_names"
        }
        for row in events if not is_excluded(row)
    ]
    visible_public = [
        {
            key: (_qualitative(value) if key == "body" else value)
            for key, value in row.items() if key != "excluded_names"
        }
        for row in public_events if not is_excluded(row)
    ]
    return {
        "character_name": character_name,
        "office_type": office_type,
        "turn": int(state.turn),
        "world": world,
        "events": visible_events,
        "public_events": visible_public,
    }
