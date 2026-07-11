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
    # ``turn_reports`` is a rendered aggregate.  It has no item/source
    # boundary, so reading it here would make a secret-bearing report a public
    # event.  ``public`` is filled from the source-scoped event projection in
    # build_character_knowledge after exclusions have been applied.
    result: Dict[str, str] = {"public": "登基伊始，朝廷暂无已公开的前回合见闻。"}

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

    def is_excluded(row: Dict[str, object]) -> bool:
        try:
            excluded_names = json.loads(str(row.get("excluded_names") or "[]"))
        except (TypeError, ValueError):
            excluded_names = []
        if character_name in excluded_names:
            return True
        source_id = str(row.get("source_id") or "")
        targets = row.get("excluded_targets") or (
            db.knowledge_exclusion_targets_for_source(source_id)
            if hasattr(db, "knowledge_exclusion_targets_for_source")
            else {"people": [], "offices": []}
        )
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
    public_bodies = [
        _qualitative(item.get("body") or item.get("title") or "")
        for item in visible_public
        if item.get("body") or item.get("title")
    ]
    world["public"] = "\n".join(public_bodies) or world["public"]
    known_source_ids = {
        str(row.get("source_id") or "")
        for row in [*events, *public_events]
        if row.get("source_id")
    }
    visible_issues = []
    for issue in db.list_active_issues() if hasattr(db, "list_active_issues") else []:
        source_id = f"issue:{issue['id']}"
        try:
            roster = json.loads(issue["participant_roster"] or "[]")
        except (TypeError, ValueError, KeyError):
            roster = []
        # Unassigned issues are public; assigned issues are visible only when
        # this character entered the durable source projection.
        if roster and source_id not in known_source_ids:
            continue
        if is_excluded({"source_id": source_id, "excluded_names": "[]"}):
            continue
        visible_issues.append({
            "id": int(issue["id"]), "kind": issue["kind"],
            "title": issue["title"], "bar_value": issue["bar_value"],
            "bar_good_meaning": issue["bar_good_meaning"],
            "bar_bad_meaning": issue["bar_bad_meaning"],
            "stage_text": issue["stage_text"], "faction_hint": issue["faction_hint"],
            "severity": issue["severity"], "source_id": source_id,
            "resolve_condition": issue["resolve_condition"],
            "fail_condition": issue["fail_condition"],
            "stop_condition": issue["stop_condition"],
            "end_turn": issue["end_turn"],
            "commitment_kind": issue["commitment_kind"],
        })
    return {
        "character_name": character_name,
        "office_type": office_type,
        "turn": int(state.turn),
        "world": world,
        "events": visible_events,
        "public_events": visible_public,
        "issues": visible_issues,
    }


def build_character_treasury_ledger(
    db: Any, state: Any, character_name: str, account: str, turns: int,
) -> str:
    """Render ledger history through the character's treasury projection.

    This is intentionally part of the knowledge read model: callers must not
    query ``economy_ledger`` before the office-domain gate has been applied.
    Amounts and balances are qualitative in audience-facing text.
    """
    knowledge = build_character_knowledge(db, state, character_name)
    if "treasury" not in (knowledge.get("world") or {}):
        return ""
    try:
        window = max(1, min(24, int(turns)))
    except (TypeError, ValueError):
        window = 6
    if not hasattr(db, "conn"):
        return ""
    start_turn = max(0, int(state.turn) - window + 1)
    rows = db.conn.execute(
        "SELECT year, period, delta, balance_after, category, reason "
        "FROM economy_ledger WHERE account=? AND turn>=? AND turn<=? "
        "ORDER BY turn DESC, id DESC",
        (account, start_turn, int(state.turn)),
    ).fetchall()
    if not rows:
        return f"见闻中未载{account}近{window}回合流水。"
    lines = [f"【{account}近{window}回合流水】"]
    for row in rows:
        line = (
            f"{row['year']}年{row['period']}月：{row['delta']:+d}（{row['reason'] or row['category']}；"
            f"余额{row['balance_after']}）"
        )
        lines.append(_qualitative(line))
    return "\n".join(lines)
