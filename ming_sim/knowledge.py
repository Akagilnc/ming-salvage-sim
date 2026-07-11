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

from ming_sim.qualitative import qualitative_band


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
    """Keep report prose while preserving player-facing countable facts.

    The report builders already translate abstract game axes (for example morale
    and satisfaction) into qualitative language.  Amounts, troop totals, dates,
    artillery pieces, and arrears months are diegetic facts, not hidden axes;
    replacing every number here made the audience unable to reason about the
    state it is entitled to see.
    """
    rendered = str(text or "")
    labels = {
        "火器": ("匮乏", "短缺", "尚可", "精良", "充足"),
        "民心": ("堪忧", "堪忧", "尚可", "稳固", "拥戴"),
        "动乱": ("低", "渐起", "中等", "高", "已炽"),
        "士绅阻力": ("低", "偏低", "中等", "偏高", "很高"),
        "军事压力": ("低", "偏低", "中等", "偏高", "很高"),
        "进度": ("未见起色", "初有进展", "稳步推进", "近于收束", "已平"),
        "风险": ("低", "中", "偏高", "极高", "极高"),
        "完好": ("残损", "失修", "尚可", "完好", "坚固"),
        "等级": ("初设", "成形", "完备", "宏整", "巨构"),
    }
    pattern = re.compile(r"(" + "|".join(labels) + r")\s*[:：]?\s*(-?\d+)(?:\s*/\s*100|%)?")
    def replace(match: re.Match[str]) -> str:
        label, raw = match.groups()
        return label + "：" + qualitative_band(raw, labels[label])
    rendered = pattern.sub(replace, rendered)
    return rendered


def render_character_knowledge(knowledge: Dict[str, object], character_name: str) -> str:
    """Render one character's projected knowledge for an audience prompt.

    This is the single presentation seam for both live session prompts and
    minister-agent prompts.  The projection has already enforced access
    control; this function only de-duplicates sources, orders them, and caps
    the prompt material.
    """
    lines = [f"【{character_name}此刻所知的天下（仅此人物见闻）】"]
    for key, value in (knowledge.get("world") or {}).items():
        if value:
            lines.append(f"{key}：{value}")
    by_source = {}
    for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]:
        source_id = str(item.get("source_id") or "")
        key = (source_id, item.get("title") or "", item.get("body") or "") if source_id else (
            int(item.get("turn") or 0), item.get("title") or "", item.get("body") or ""
        )
        by_source[key] = item
    recent_items = sorted(
        by_source.values(),
        key=lambda item: (int(item.get("turn") or 0), str(item.get("source_id") or "")),
    )[-20:]
    for item in recent_items:
        title = item.get("title") or "旧闻"
        body = item.get("body") or ""
        if body:
            lines.append(f"- {title}：{body}")
    return "\n".join(lines) if len(lines) > 1 else ""


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
    # The roster is a membership fact, not a second free-text office report.
    # Including office strings here can name people outside this role (for
    # example a kinship note in an office title), defeating the role boundary.
    roster = "、".join(str(row["name"]) for row in rows)
    return f"{office_type}本职在册：{roster}。"


def _source_archive_rows(db: Any, character_name: str, upto_turn: int) -> list[Dict[str, object]]:
    """Project durable source rows into this character's archive boundary.

    ``character_knowledge_sources`` is the write-side source of truth for
    restricted matters.  It must participate in archive projection even when
    no public-event mirror exists; otherwise a mixed aggregate has no exact
    source fragment to redact.
    """
    if not hasattr(db, "conn"):
        return []
    rows = db.conn.execute(
        "SELECT turn, year, period, kind, title, body, source_id, "
        "participant_roster, excluded_names FROM character_knowledge_sources "
        "WHERE turn <= ? ORDER BY turn, id",
        (int(upto_turn),),
    ).fetchall()
    projected: list[Dict[str, object]] = []
    for row in rows:
        try:
            roster = json.loads(row["participant_roster"] or "[]")
        except (TypeError, ValueError):
            roster = []
        participants = {
            str(item.get("character_id") or item.get("name"))
            for item in roster
            if isinstance(item, dict) and (item.get("character_id") or item.get("name"))
        }
        try:
            excluded = json.loads(row["excluded_names"] or "[]")
        except (TypeError, ValueError):
            excluded = []
        if not isinstance(excluded, list):
            excluded = []
        # A participant-rostered source is private to its participants unless
        # an explicit exclusion says otherwise.  Empty rosters are not added
        # here: public events already have their own projection path.
        if not participants:
            continue
        if character_name not in participants:
            excluded.append(character_name)
        projected.append({
            "turn": int(row["turn"]), "year": int(row["year"]),
            "period": int(row["period"]), "kind": row["kind"],
            "title": row["title"], "body": row["body"],
            "source_id": row["source_id"],
            "excluded_names": json.dumps(list(dict.fromkeys(excluded)), ensure_ascii=False),
        })
    return projected


def _world(
    db: Any, state: Any, office_type: str,
) -> Dict[str, str]:
    # ``turn_reports`` is a rendered aggregate.  It has no item/source
    # boundary, so reading it here would make a secret-bearing report a public
    # event.  ``public`` is filled from the source-scoped event projection in
    # build_character_knowledge after exclusions have been applied.
    result: Dict[str, str] = {"public": "登基伊始，朝廷暂无前回合奏报。"}

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
            result[domain] = _qualitative(facts[domain])
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
    public_events.extend(_source_archive_rows(db, character_name, int(state.turn)))
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
    def source_projection(turn: int, fallback: object) -> str:
        """Project aggregate narrative from source rows, never from redaction.

        Reports and chapter memories are rendered aggregates.  When their turn
        has source-scoped knowledge rows, those rows are the only material used
        for this character.  The aggregate is a compatibility fallback for old
        saves that predate the source projection and have no rows at all.
        """
        # Only durable source rows are inputs here.  The synthetic
        # ``turn_report:*``/``chapter:*`` rows below are read-model outputs;
        # feeding one archive back into the next archive would duplicate
        # material and make an already-rendered aggregate look like an
        # unrestricted source.
        rows = [
            row for row in public_events
            if int(row.get("turn") or 0) == turn
            and not str(row.get("source_id") or "").startswith(
                ("opening:", "directive:", "turn_report:", "chapter:", "chapter_source:",
                )
            )
            and str(row.get("source_id") or "") != f"settlement:narrative:{turn}"
        ]
        visible = [
            row for row in rows
            if knowledge_row_visible_to(
                db, {**row, "office_type": office_type, "office": office_name}, character_name,
            )
        ]

        # Once any source boundary exists, the aggregate is no longer an
        # authorization boundary: chapter-memory/LLM rewriting can paraphrase
        # a secret so that it is no longer an exact substring of the source.
        # Project only independently persisted visible items.  The aggregate
        # remains a compatibility fallback solely for old saves with no source
        # rows at all; new settlement producers must persist public and
        # restricted items through ``knowledge_items``.
        if rows:
            return "\n".join(
                _qualitative(row.get("body") or row.get("title") or "")
                for row in visible
                if row.get("body") or row.get("title")
            )
        return _qualitative(fallback)

    # Keep the durable source rows, and add a character-specific projection of
    # each aggregate archive.  Source rows redact restricted fragments from
    # the aggregate, while independently persisted public fragments remain
    # available to the character.
    if hasattr(db, "list_turn_reports"):
        for report in db.list_turn_reports():
            # The opening gazette is seed material, not a prior played turn.
            # Its separately persisted opening facts remain visible without
            # turning the turn-zero aggregate into every role's public rail.
            if int(report["turn"]) <= 0:
                continue
            body = source_projection(int(report["turn"]), report.get("report"))
            if body:
                public_events.append({
                    "turn": int(report["turn"]), "year": int(report["year"]),
                    "period": int(report["period"]), "kind": "public",
                    "title": "邸报", "body": body,
                    "source_id": f"turn_report:{report['turn']}",
                    "excluded_names": "[]",
                })
    if hasattr(db, "list_chapter_memories"):
        for chapter in db.list_chapter_memories(upto_turn=state.turn):
            body = source_projection(int(chapter["turn"]), chapter.get("body"))
            if body:
                public_events.append({
                    "turn": int(chapter["turn"]), "year": int(chapter["year"]),
                    "period": int(chapter["period"]), "kind": "chapter_summary",
                    "title": chapter.get("title") or "朝局旧闻", "body": body,
                    "source_id": f"chapter:{chapter['turn']}",
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
        # Aggregate archive writers leave compatibility source rows behind.
        # They are not authorization boundaries: when the turn contains a
        # restricted source their prose may be a rewrite of that source.  The
        # character-specific turn_report/chapter projection above is the only
        # archive representation allowed into the audience view.
        if not str(row.get("source_id") or "").startswith(
            ("turn_report:", "chapter_source:")
        )
        and not re.fullmatch(r"settlement:narrative:\\d+", str(row.get("source_id") or ""))
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    public_bodies = [
        _qualitative(item.get("body") or item.get("title") or "")
        for item in visible_public
        if (item.get("body") or item.get("title"))
        and not str(item.get("source_id") or "").startswith("opening:")
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
        if roster:
            participants = {
                str(item.get("character_id") or item.get("name"))
                for item in roster
                if isinstance(item, dict) and (item.get("character_id") or item.get("name"))
            }
            if character_name not in participants or source_id not in known_source_ids:
                continue
        if not knowledge_row_visible_to(
            db,
            {"source_id": source_id, "excluded_names": "[]", "office_type": office_type, "office": office_name},
            character_name,
        ):
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
