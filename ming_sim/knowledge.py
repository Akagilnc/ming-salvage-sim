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


def _world(
    db: Any, state: Any, office_type: str, office_name: str,
    excluded_people: set[str] | None = None, excluded_offices: set[str] | None = None,
) -> Dict[str, str]:
    bucket = _OFFICE_BUCKETS.get(office_type, "public")
    reports = db.list_turn_reports() if hasattr(db, "list_turn_reports") else []
    def fact(text: object) -> str:
        value = _qualitative(text)
        for person in excluded_people or set():
            value = value.replace(person, "某人")
        return value

    public = "\n".join(fact(r.get("report")) for r in reports)
    if office_type in (excluded_offices or set()) or office_name in (excluded_offices or set()):
        # A direct office-level blackout removes the reader's public view too;
        # cross-domain readers still retain their unrelated public layer.
        public = ""
    result: Dict[str, str] = {"public": public or "登基伊始，朝廷暂无前回合奏报。"}

    # Keep each world fact tied to its domain.  A blacklist for 户部 therefore
    # removes the treasury fact even when it is being read by 内阁, without
    # accidentally deleting 内阁's personnel fact as well.  The current office
    # and title are checked at read time, so appointment changes cannot revive a
    # fact that was blacklisted for that office.
    domain_offices = {
        "treasury": {"户部"}, "military": {"兵部", "边镇"},
        "regional": {"督抚", "地方", "外臣"}, "personnel": {"吏部"},
        "construction": {"工部"}, "security": {"锦衣卫", "东厂"},
        "court": {"内阁", "司礼监", "内臣", "内廷"},
    }

    def blocked(domain: str) -> bool:
        # Office exclusions are provenance-aware: an exclusion for 户部 may
        # hide the treasury fact, but must not erase unrelated personnel or
        # court facts.  Do not compare against the reader's office here; the
        # source office of the fact is the secrecy boundary.
        fact_sources = domain_offices.get(domain, set())
        targets = excluded_offices or set()
        if fact_sources & targets:
            return True
        # A persisted exclusion may use a concrete office title (for example
        # ``南京户部尚书``) rather than the normalized office_type.  Resolve
        # that title to its source type without turning the exclusion into a
        # global "clear every bucket" switch.
        characters = getattr(getattr(db, "content", None), "characters", {}) or {}
        return office_name in targets and any(
            str(getattr(character, "office", "") or "") == office_name
            and str(getattr(character, "office_type", "") or "") in fact_sources
            for character in characters.values()
        )

    facts = {
        "treasury": db.treasury_report(state),
        "military": db.army_report(limit=10),
        "regional": db.region_report(limit=10),
        "personnel": db.faction_report(),
        "construction": db.buildings_report(),
        "security": db.power_report(exclude_self=True),
    }
    visible_domains = {
        "户部": {"treasury"}, "兵部": {"military", "regional"},
        "吏部": {"personnel"}, "工部": {"construction"},
        "督抚": {"regional"}, "边镇": {"military", "regional"},
        "地方": {"regional"}, "外臣": {"regional"},
        "锦衣卫": {"security"}, "东厂": {"security"},
        "内阁": {"treasury", "personnel"}, "司礼监": {"treasury", "personnel"},
        "内臣": {"treasury", "personnel"}, "内廷": {"treasury", "personnel"},
    }.get(office_type, {bucket})
    for domain in visible_domains:
        if domain == "public":
            # The public layer is already built from the turn reports above;
            # generic offices must not treat it as a deterministic report
            # source (there is no ``facts["public"]`` entry).
            continue
        if blocked(domain):
            # Keep the domain addressable while making the secrecy boundary
            # explicit.  A missing key is indistinguishable from an unmapped
            # office/domain and lets callers accidentally fall back to it.
            if office_type in {"内阁", "司礼监", "内臣", "内廷"}:
                result[domain] = ""
            continue
        else:
            result[domain] = fact(facts[domain])
    return result


def build_character_knowledge(db: Any, state: Any, character_name: str) -> Dict[str, object]:
    character = db.content.characters.get(character_name) if db.content else None
    office_type = str(getattr(character, "office_type", "") or "")
    exclusion_targets = {"people": set(), "offices": set()}
    for order in db.list_secret_orders():
        targets = json.loads(order.get("excluded_targets") or "{}") if isinstance(order.get("excluded_targets"), str) else order.get("excluded_targets") or {}
        exclusion_targets["people"].update(str(x) for x in targets.get("people", []))
        exclusion_targets["offices"].update(str(x) for x in targets.get("offices", []))
    office_name = str(getattr(character, "office", "") or "")
    world = _world(
        db, state, office_type, office_name,
        {character_name} if character_name in exclusion_targets["people"] else set(),
        exclusion_targets["offices"],
    )
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
