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
    "工部": "construction", "礼部": "personnel", "刑部": "security",
    "翰林院": "personnel", "都察院": "security", "内阁": "court",
    "督抚": "regional", "司礼监": "court",
    "内臣": "court", "锦衣卫": "security", "东厂": "security",
    "边镇": "military", "地方": "regional", "外臣": "regional",
    "未仕": "personnel", "后宫": "personnel", "宗藩": "regional",
    "内廷": "court", "生员": "personnel", "乡绅": "regional",
    "富商": "treasury", "布衣": "regional", "流寇": "military", "待铨": "personnel",
}

# Every supported office type gets a current-state rail in addition to the
# public layer.  These are the closest existing reports for social/roster
# roles whose dedicated rail is not yet modeled.
_OFFICE_VISIBLE_DOMAINS = {
    # Tuples make prompt field order stable; every entry deliberately contains
    # its _OFFICE_BUCKETS rail, so adding a role cannot silently produce a
    # public-only or unrelated current-state view.
    "户部": ("treasury", "role"), "兵部": ("military", "regional", "role"),
    "吏部": ("personnel", "role"), "工部": ("construction", "role"),
    "礼部": ("personnel", "role"), "刑部": ("security", "role"),
    "翰林院": ("personnel", "role"), "都察院": ("personnel", "security", "role"),
    "内阁": ("court", "treasury", "personnel", "role"), "督抚": ("regional", "role"),
    "司礼监": ("court", "treasury", "personnel", "role"), "内臣": ("court", "treasury", "personnel", "role"),
    "锦衣卫": ("security", "role"), "东厂": ("security", "role"),
    "边镇": ("military", "regional", "role"), "地方": ("regional", "role"),
    "外臣": ("regional", "role"), "内廷": ("court", "treasury", "personnel", "role"),
    "后宫": ("personnel", "role"), "宗藩": ("regional", "role"), "未仕": ("personnel", "role"),
    "生员": ("personnel", "role"), "乡绅": ("regional", "role"), "富商": ("treasury", "role"),
    "布衣": ("regional", "role"), "流寇": ("military", "regional", "role"), "待铨": ("personnel", "role"),
}

# A persisted character can temporarily carry a newly introduced or malformed
# office type while an old save is being upgraded.  Such a role still needs a
# useful current-state rail; falling back to ``public`` would recreate a
# one-world view for precisely the characters this projection is meant to
# differentiate.
_DEFAULT_VISIBLE_DOMAINS = ("personnel",)


def _visible_domains(office_type: str) -> tuple[str, ...]:
    """Return a deterministic role slice whose primary bucket is always present."""
    bucket = _OFFICE_BUCKETS.get(office_type, "personnel")
    configured = _OFFICE_VISIBLE_DOMAINS.get(office_type, _DEFAULT_VISIBLE_DOMAINS)
    if bucket in configured:
        return configured
    # Keep old saves with a newly introduced/malformed role useful even when
    # its mapping was not deployed alongside the bucket table.
    return (bucket, *configured)


def _qualitative(text: object) -> str:
    """Render an engine report for a minister without exposing machine values."""
    value = str(text or "")
    # Reports remain useful as labels and prose, but their exact balances, bars,
    # ids, and percentages belong to the judge-side tools, not a character prompt.
    return re.sub(r"[-+]?\d+(?:\.\d+)?%?", "若干", value)


def _role_roster(db: Any, office_type: str) -> str:
    """Return only the current roster for this office type.

    The role rail is intentionally queried from the current DB rather than
    copied from the character's event history.  It is therefore a real
    position-scoped fact set and updates automatically after appointments or
    restore, while the qualitative rendering keeps machine values out of the
    audience prompt.
    """
    if not hasattr(db, "conn"):
        return f"{office_type}本职在册：暂无。"
    rows = db.conn.execute(
        "SELECT name, office FROM characters WHERE office_type = ? ORDER BY name",
        (office_type,),
    ).fetchall()
    if not rows:
        return f"{office_type}本职在册：暂无。"
    roster = "、".join(
        f"{row['name']}（{row['office']}）" if row['office'] else str(row['name'])
        for row in rows
    )
    return f"{office_type}本职在册：{roster}。"


def _world(
    db: Any, state: Any, office_type: str,
) -> Dict[str, str]:
    reports = db.list_turn_reports() if hasattr(db, "list_turn_reports") else []
    def fact(text: object) -> str:
        return _qualitative(text)

    public = "\n".join(fact(r.get("report")) for r in reports)
    result: Dict[str, str] = {"public": public or "登基伊始，朝廷暂无前回合奏报。"}

    facts = {
        "treasury": db.treasury_report(state),
        "military": db.army_report(limit=10),
        "regional": db.region_report(limit=10),
        "personnel": db.faction_report(),
        "construction": db.buildings_report(),
        "security": db.power_report(exclude_self=True),
        "court": "\n".join((db.faction_report(), db.power_report(exclude_self=True))),
        "role": _role_roster(db, office_type),
    }
    visible_domains = _visible_domains(office_type)
    for domain in visible_domains:
        if domain == "public":
            # The public layer is already built from the turn reports above;
            # generic offices must not treat it as a deterministic report
            # source (there is no ``facts["public"]`` entry).
            continue
        # Keep the domain key stable for prompt consumers, while retaining the
        # office context in the slice.  Without it, offices that share a
        # domain (for example 礼部 and 翰林院) receive byte-for-byte identical
        # world views and lose the distinction required by the read model.
        result[domain] = fact(f"{office_type}本职所涉：{facts[domain]}")
    return result


def build_character_knowledge(db: Any, state: Any, character_name: str) -> Dict[str, object]:
    character = db.content.characters.get(character_name) if db.content else None
    office_type = str(getattr(character, "office_type", "") or "")
    office_name = str(getattr(character, "office", "") or "")
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
        targets = db.knowledge_exclusion_targets_for_source(source_id) if hasattr(db, "knowledge_exclusion_targets_for_source") else {"people": [], "offices": []}
        return (character_name in excluded_names
                or character_name in targets.get("people", [])
                or office_type in targets.get("offices", [])
                or office_name in targets.get("offices", []))

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
