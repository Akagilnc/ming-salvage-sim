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


_DEFAULT_VISIBLE_DOMAINS = ("personnel",)


def _visible_domains(db: Any, office_type: str) -> tuple[str, ...]:
    """Return the validated content setting for this office's current-state rail."""
    configured = getattr(getattr(db, "content", None), "office_knowledge_domains", {}).get(
        office_type, _DEFAULT_VISIBLE_DOMAINS
    )
    return tuple(configured) or _DEFAULT_VISIBLE_DOMAINS


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

    visible_domains = _visible_domains(db, office_type)
    # Build only the current-state rails that this office is entitled to read.
    # Besides keeping the returned projection scoped, this prevents a future
    # report implementation from leaking a sensitive cross-domain payload via
    # an intermediate all-world snapshot.
    report_builders = {
        "treasury": lambda: db.treasury_report(state),
        "military": lambda: db.army_report(limit=10),
        "regional": lambda: db.region_report(limit=10),
        "personnel": db.faction_report,
        "construction": db.buildings_report,
        "security": lambda: db.power_report(exclude_self=True),
        "court": lambda: "\n".join((db.faction_report(), db.power_report(exclude_self=True))),
    }
    facts = {
        domain: _qualitative(report_builders[domain]())
        for domain in visible_domains
        if domain in report_builders
    }
    result["role"] = _role_roster(db, office_type)
    for domain in visible_domains:
        if domain in facts:
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
