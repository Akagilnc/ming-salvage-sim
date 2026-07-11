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


def _visible_domains(db: Any, office_type: str) -> tuple[str, ...]:
    """Return the validated content setting for this office's current-state rail."""
    configured = getattr(getattr(db, "content", None), "office_knowledge_domains", {}).get(office_type, ())
    # Unknown/malformed runtime roles get no private current-state rail.  The
    # content loader validates every shipped office type, so silently assigning
    # a hard-coded domain here would turn a missing setting into a data leak.
    return tuple(configured)


def knowledge_row_visible_to(
    db: Any, row: Any, character_name: str, *, target: Any = None,
) -> bool:
    """Apply one source's person and current-position secrecy boundary.

    ``target`` is the person whose visibility is being tested.  When omitted,
    the subject is the reader, which is the projection's normal use case.
    Recommendation reads pass each roster candidate explicitly so an excluded
    office cannot be reintroduced by a name-only roster projection.
    """
    target = target or row
    def target_value(key: str) -> object:
        try:
            return target[key]
        except (KeyError, IndexError, TypeError):
            return None

    target_name = str(target_value("name") or target_value("character_id") or character_name)
    target_office_type = str(target_value("office_type") or "")
    target_office = str(target_value("office") or "")
    try:
        excluded_names = json.loads(row["excluded_names"] or "[]")
    except (TypeError, ValueError, KeyError, IndexError):
        excluded_names = []
    if target_name in {str(name) for name in excluded_names}:
        return False
    targets: object = {}
    try:
        raw_targets = row["excluded_targets"]
    except (KeyError, IndexError, TypeError):
        raw_targets = None
    if raw_targets:
        try:
            targets = json.loads(raw_targets or "{}")
        except (TypeError, ValueError):
            targets = {}
    if not isinstance(targets, dict) or not targets:
        source_id = str(row["source_id"] or "")
        if hasattr(db, "knowledge_exclusion_targets_for_source"):
            targets = db.knowledge_exclusion_targets_for_source(source_id)
    people = {str(name) for name in (targets.get("people", []) if isinstance(targets, dict) else [])}
    offices = {str(name) for name in (targets.get("offices", []) if isinstance(targets, dict) else [])}
    return target_name not in people and target_office_type not in offices and target_office not in offices


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
            # The domain map is the semantic boundary.  Do not prepend an
            # office label to manufacture a difference between otherwise
            # identical reports; the value must remain an actual current-state
            # fact selected by the content-owned domain mapping.
            result[domain] = fact(facts[domain])
    return result


def build_character_knowledge(db: Any, state: Any, character_name: str) -> Dict[str, object]:
    character = db.content.characters.get(character_name) if db.content else None
    # The content object is the seed/in-memory roster and can lag behind a
    # restored save.  The characters table is the durable current-world source
    # for the position rail, so always prefer it when this is a real GameDB.
    current = None
    if hasattr(db, "conn"):
        current = db.conn.execute(
            "SELECT office, office_type FROM characters WHERE name = ?",
            (character_name,),
        ).fetchone()
    office_type = str(
        (current["office_type"] if current is not None else getattr(character, "office_type", ""))
        or ""
    )
    office_name = str(
        (current["office"] if current is not None else getattr(character, "office", ""))
        or ""
    )
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
    visible_events = [
        {
            key: (_qualitative(value) if key == "body" else value)
            for key, value in row.items() if key != "excluded_names"
        }
        for row in events
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    visible_public = [
        {
            key: (_qualitative(value) if key == "body" else value)
            for key, value in row.items() if key != "excluded_names"
        }
        for row in public_events
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    return {
        "character_name": character_name,
        "office_type": office_type,
        "turn": int(state.turn),
        "world": world,
        "events": visible_events,
        "public_events": visible_public,
    }
