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

from ming_sim.participant_roster import participant_roster_names


def _issue_audience_names(db: Any, issue: Any) -> set[str]:
    """Resolve seed-event audiences for an issue (read-model only).

    Opening/seed situations list knowers on the originating event's ``audiences``
    field.  Issues themselves do not duplicate that column; look up via
    ``origin_kind=event_pool`` → events table, then content fallback.
    """
    try:
        origin_kind = str(issue["origin_kind"] or "")
        origin_ref = str(issue["origin_ref"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return set()
    if origin_kind != "event_pool" or not origin_ref:
        return set()
    raw: object = None
    if hasattr(db, "conn"):
        try:
            row = db.conn.execute(
                "SELECT audiences FROM events WHERE id=?", (origin_ref,),
            ).fetchone()
        except Exception:
            row = None
        if row is not None:
            raw = row["audiences"]
    if raw is None:
        content = getattr(db, "content", None)
        event_by_id = getattr(content, "event_by_id", None) or {}
        ev = event_by_id.get(origin_ref)
        if ev is not None:
            raw = getattr(ev, "audiences", None) or []
    if raw is None:
        return set()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return set()
    if not isinstance(raw, (list, tuple)):
        return set()
    return {str(name).strip() for name in raw if str(name).strip()}


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
    reader = None
    try:
        reader = db.conn.execute(
            "SELECT name, office, office_type FROM characters WHERE name=?", (character_name,)
        ).fetchone()
    except (AttributeError, TypeError):
        reader = None
    target = target or reader or row
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
    excluded = {str(name) for name in excluded_names}
    if character_name in excluded or target_name in excluded:
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
    def excluded_subject(subject: Any, fallback_name: str) -> bool:
        if subject is None:
            return fallback_name in people
        try:
            name = str(subject["name"] or fallback_name)
            office_type = str(subject["office_type"] or "")
            office = str(subject["office"] or "")
        except (KeyError, IndexError, TypeError):
            name, office_type, office = fallback_name, "", ""
        return name in people or office_type in offices or office in offices
    if excluded_subject(reader, character_name) or excluded_subject(target, target_name):
        return False
    # A private source's roster is a positive capability, not a deny-list
    # snapshot.  Enforce it at read time so characters created after archival
    # cannot inherit old participant-private material.
    try:
        source = db.conn.execute(
            "SELECT kind, participant_roster FROM character_knowledge_sources WHERE source_id=?",
            (str(row["source_id"] or ""),),
        ).fetchone()
    except (AttributeError, KeyError, IndexError, TypeError):
        source = None
    # A public event is a new disclosure capability even when it deliberately
    # retains the private source id for provenance.  It keeps its own explicit
    # people/office exclusions above, but must not inherit the source roster.
    try:
        event_is_public = str(row["kind"] or "") == "public"
    except (KeyError, IndexError, TypeError):
        event_is_public = False
    if not event_is_public and source is not None and str(source["kind"] or "") != "public":
        participants = participant_roster_names(source["participant_roster"])
        if participants and character_name not in participants:
            return False
    return True


def _prose(text: object) -> str:
    """Carry durable report prose without mechanically interpreting it."""
    return str(text or "")


def _issue_audience_case_events(
    db: Any,
    state: Any,
    character_name: str,
    *,
    known_source_ids: set[str] | None = None,
) -> list[Dict[str, object]]:
    """#1281 prompt-only synthesis: seed-event audience sees issue stage_text.

    Read-time only.  Must never be folded into ``build_character_knowledge`` /
    ``get_character_knowledge`` events — those APIs return durable rows only
    (#492 near_minister tail contract).
    """
    known = set(known_source_ids or ())
    synthesized: list[Dict[str, object]] = []
    active_issues = (
        db.list_active_issues() if hasattr(db, "list_active_issues") else []
    )
    for issue in active_issues:
        try:
            source_id = f"issue:{int(issue['id'])}"
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if source_id in known:
            continue
        try:
            stage = _prose(issue["stage_text"]).strip()
        except (KeyError, IndexError, TypeError):
            stage = ""
        if not stage or character_name not in _issue_audience_names(db, issue):
            continue
        if not knowledge_row_visible_to(
            db,
            {"source_id": source_id, "excluded_names": "[]",
             "office_type": "", "office": ""},
            character_name,
        ):
            continue
        try:
            origin_turn = int(issue["origin_turn"] or state.turn)
        except (KeyError, IndexError, TypeError, ValueError):
            origin_turn = int(state.turn)
        synthesized.append({
            "turn": origin_turn,
            "year": int(state.year) if origin_turn == int(state.turn) else 0,
            "period": int(state.period) if origin_turn == int(state.turn) else 0,
            "kind": "issue_case",
            "title": issue["title"],
            "body": stage,
            "source_id": source_id,
        })
        known.add(source_id)
    return synthesized


def render_character_knowledge(
    knowledge: Dict[str, object],
    character_name: str,
    *,
    db: Any = None,
    state: Any = None,
) -> str:
    """Render one character's projected knowledge for an audience prompt.

    This is the single presentation seam for both live session prompts and
    minister-agent prompts.  The projection has already enforced access
    control; this function only de-duplicates sources, orders them, and caps
    the prompt material.  #1281 issue stage_text for seed-event audiences is
    synthesized here (read-time) when ``db``/``state`` are supplied — never
    written into the durable knowledge projection.
    """
    lines = [f"【{character_name}此刻所知的天下（仅此人物见闻）】"]
    for key, value in (knowledge.get("world") or {}).items():
        if value:
            lines.append(f"{key}：{value}")
    event_items = [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]
    if db is not None and state is not None:
        known_source_ids = {
            str(item.get("source_id") or "")
            for item in event_items
            if item.get("source_id")
        }
        event_items = [
            *event_items,
            *_issue_audience_case_events(
                db, state, character_name, known_source_ids=known_source_ids,
            ),
        ]
    by_source = {}
    for item in event_items:
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
        title = str(item.get("title") or "旧闻")
        body = str(item.get("body") or "")
        if body:
            lines.append(f"- {title}：{body}")
    return "\n".join(lines) if len(lines) > 1 else ""


def project_court_roster_rows(
    rows: list[Any], knowledge: Dict[str, object], office_type: str,
) -> list[Any]:
    """Project complete structured roster rows through one character's view.

    The complete roster remains an internal query result.  A personnel-domain
    capability may expose it; otherwise only the reader's current role roster
    and people named in already-authorized events cross the output boundary.
    """
    world = knowledge.get("world") or {}
    if "personnel" in world:
        return list(rows)
    current_office_type = str(knowledge.get("office_type") or office_type or "")
    visible_event_text = "\n".join(
        "：".join(str(value) for value in (item.get("title"), item.get("body")) if value)
        for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]
    )
    return [
        row for row in rows
        if str(row["office_type"] or "") == current_office_type
        or str(row["name"] or "") in visible_event_text
    ]


def _role_roster(db: Any, office_type: str, state: Any) -> str:
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
        """SELECT name, office FROM characters
           WHERE office_type = ? AND status = 'active' AND power_id = 'ming'
             AND (debut_year = 0 OR debut_year < ?
                  OR (debut_year = ? AND debut_month <= ?))
           ORDER BY name""",
        (office_type, int(state.year), int(state.year), int(state.period)),
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
        source_id = str(row["source_id"] or "")
        # Plain turn-report/chapter rows are rendered aggregate read models,
        # not independently authorizable sources.  Their explicit ``:public``
        # counterparts remain source-scoped and are projected below.
        if ((source_id.startswith("turn_report:") and not source_id.endswith(":public"))
                or (source_id.startswith("chapter:") and not source_id.startswith("chapter_source:"))
                or re.fullmatch(r"settlement:narrative:\d+", source_id)):
            continue
        participants = participant_roster_names(row["participant_roster"])
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
    from ming_sim.population_pressure import regional_displaced_pressure_brief

    # Build only the current-state rails that this office is entitled to read.
    # Besides keeping the returned projection scoped, this prevents a future
    # report implementation from leaking a sensitive cross-domain payload via
    # an intermediate all-world snapshot.
    report_builders = {
        "treasury": lambda: db.treasury_report(state),
        "military": lambda: db.army_report(limit=30),
        "regional": lambda: "\n".join((
            db.region_report(limit=10),
            f"省级流民态势：{regional_displaced_pressure_brief(db)}",
        )),
        "personnel": lambda: db.faction_report(audience=True),
        "construction": lambda: db.buildings_report(qualitative=True),
        "security": lambda: db.power_report(exclude_self=True, audience=True),
        "court": lambda: "\n".join((
            db.faction_report(audience=True),
            db.power_report(exclude_self=True, audience=True),
        )),
    }
    facts = {
        domain: _prose(report_builders[domain]())
        for domain in visible_domains
        if domain in report_builders
    }
    result["role"] = _role_roster(db, office_type, state)
    for domain in visible_domains:
        if domain in facts:
            # The domain map is the semantic boundary.  Do not prepend an
            # office label to manufacture a difference between otherwise
            # identical reports; the value must remain an actual current-state
            # fact selected by the content-owned domain mapping.
            result[domain] = facts[domain]
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
            "body": _prose(directive.get("text") or ""),
            "source_id": f"directive:{directive['id']}",
        })
    def source_projection(turn: int, fallback: object, *, public_counterpart: str = "") -> str:
        """Project aggregate narrative from source rows, never from redaction.

        Reports and chapter memories are rendered aggregates.  When their turn
        has source-scoped knowledge rows, those rows are the only material used
        for this character.  Without an independent source, it grants nothing.
        """
        # Only durable source rows are inputs here.  The synthetic
        # ``turn_report:*``/``chapter:*`` rows below are read-model outputs;
        # feeding one archive back into the next archive would duplicate
        # material and make an already-rendered aggregate look like an
        # unrestricted source.
        rows = []
        for row in public_events:
            source_id = str(row.get("source_id") or "")
            # ``turn_report:*:public`` and ``chapter_source:*`` are explicit,
            # source-scoped public counterparts written by the archive API.
            # Unlike aggregate read-model rows, each has its own durable source
            # boundary and remains visible beside a same-turn secret.
            aggregate_row = (
                source_id.startswith("opening:")
                or source_id.startswith("directive:")
                or (source_id.startswith("turn_report:") and not source_id.endswith(":public"))
                or source_id.startswith("chapter:")
                or source_id == f"settlement:narrative:{turn}"
            )
            if int(row.get("turn") or 0) == turn and not aggregate_row:
                rows.append(row)
        # Direct archive callers persist an explicit public counterpart.  It
        # is the authoritative public fragment for that aggregate; mixing it
        # with unrelated same-turn sources would turn one gazette item into a
        # synthetic bundle and lose its independently addressable history.
        counterpart_rows = [row for row in rows if str(row.get("source_id") or "") == public_counterpart]
        # Independently public source rows are already the canonical audience
        # material.  Do not add a report/chapter rendering of the same turn on
        # top of them: that is how ordinary monthly prose was repeated.
        if any(
            not row.get("excluded_names")
            and not str(row.get("source_id") or "").startswith(("turn_report:", "chapter_source:"))
            for row in rows
        ):
            return ""
        if counterpart_rows:
            # A chapter's public counterpart is derived from the same
            # independently public source set as that turn's gazette.  Keep
            # the gazette projection as the one monthly rendering instead of
            # replaying identical prose through the chapter archive.
            if public_counterpart.startswith("chapter_source:"):
                report_counterpart = f"turn_report:{turn}:public"
                report_rows = [
                    row for row in rows
                    if str(row.get("source_id") or "") == report_counterpart
                ]
                if report_rows:
                    return ""
            rows = counterpart_rows
        visible = [
            row for row in rows
            if knowledge_row_visible_to(
                db, {**row, "office_type": office_type, "office": office_name}, character_name,
            )
        ]

        # An aggregate has no independent source boundary.  It is never a
        # knowledge grant: source rows are the sole public projection seam.
        # #883 deliberately has no old-save compatibility fallback.
        if rows:
            return "\n".join(
                _prose(row.get("body") or row.get("title") or "")
                for row in visible
                if row.get("body") or row.get("title")
            )
        return ""

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
            report_turn = int(report["turn"])
            body = source_projection(
                report_turn, report.get("report"),
                public_counterpart=f"turn_report:{report_turn}:public",
            )
            if body:
                public_events.append({
                    "turn": int(report["turn"]), "year": int(report["year"]),
                    "period": int(report["period"]), "kind": "public",
                    "title": "邸报", "body": body,
                    "source_id": f"projection:turn_report:{report['turn']}",
                    "excluded_names": "[]",
                })
    if hasattr(db, "list_chapter_memories"):
        for chapter in db.list_chapter_memories(upto_turn=state.turn):
            chapter_turn = int(chapter["turn"])
            body = source_projection(
                chapter_turn, chapter.get("body"),
                public_counterpart=f"chapter_source:{chapter_turn}",
            )
            if body:
                public_events.append({
                    "turn": int(chapter["turn"]), "year": int(chapter["year"]),
                    "period": int(chapter["period"]), "kind": "chapter_summary",
                    "title": chapter.get("title") or "朝局旧闻", "body": body,
                    "source_id": f"projection:chapter:{chapter['turn']}",
                    "excluded_names": "[]",
                })

    visible_events = [
        {
            key: (_prose(value) if key == "body" else value)
            for key, value in row.items() if key != "excluded_names"
        }
        for row in events
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    projected_turns = set()
    for row in public_events:
        source_id = str(row.get("source_id") or "")
        if source_id.startswith("turn_report:") and source_id.endswith(":public"):
            turn = source_id.removeprefix("turn_report:").removesuffix(":public")
        elif source_id.startswith("chapter_source:"):
            turn = source_id.removeprefix("chapter_source:")
        elif source_id.startswith("projection:turn_report:"):
            turn = source_id.removeprefix("projection:turn_report:")
        elif source_id.startswith("projection:chapter:"):
            turn = source_id.removeprefix("projection:chapter:")
        else:
            continue
        if turn.isdigit():
            projected_turns.add(int(turn))
    visible_public = [
        {
            key: (_prose(value) if key == "body" else value)
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
        and not re.fullmatch(r"settlement:narrative:\d+", str(row.get("source_id") or ""))
        # When a source-preserving archive projection exists for this turn,
        # expose it once through that archive rather than beside its source
        # row.  This keeps normal monthly prose from being tripled by source,
        # gazette, and chapter read models.
        and (
            int(row.get("turn") or 0) not in projected_turns
            or bool(row.get("excluded_names"))
            or str(row.get("source_id") or "").startswith("projection:")
            or str(row.get("source_id") or "").startswith("opening:")
            or str(row.get("source_id") or "").startswith("directive:")
        )
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    report_projection_turns = {
        int(row.get("turn") or 0) for row in visible_public
        if str(row.get("source_id") or "").startswith("projection:turn_report:")
    }
    visible_public = [
        row for row in visible_public
        if not (
            str(row.get("source_id") or "").startswith("projection:chapter:")
            and int(row.get("turn") or 0) in report_projection_turns
        )
    ]
    projection_bodies_by_turn: dict[int, list[str]] = {}
    for row in visible_public:
        if str(row.get("source_id") or "").startswith("projection:"):
            projection_bodies_by_turn.setdefault(int(row.get("turn") or 0), []).append(
                str(row.get("body") or "")
            )
    visible_public = [
        row for row in visible_public
        if str(row.get("source_id") or "").startswith("projection:")
        or not any(
            str(row.get("body") or "")
            and str(row.get("body") or "") in aggregate
            for aggregate in projection_bodies_by_turn.get(int(row.get("turn") or 0), [])
        )
    ]
    # Collapse only exact same-turn archive/source duplicates.  Never compare
    # substrings and never deduplicate across turns: those are independent
    # historical facts even when their prose happens to overlap.
    archive_bodies = {
        (int(row.get("turn") or 0), str(row.get("body") or ""))
        for row in visible_public
        if str(row.get("source_id") or "").startswith("projection:")
    }
    visible_public = [
        row for row in visible_public
        if str(row.get("source_id") or "").startswith("projection:")
        or (int(row.get("turn") or 0), str(row.get("body") or "")) not in archive_bodies
    ]
    deduped_public = []
    seen_exact: set[tuple[int, str]] = set()
    for row in visible_public:
        identity = (int(row.get("turn") or 0), str(row.get("body") or ""))
        if identity[1] and identity in seen_exact:
            continue
        seen_exact.add(identity)
        deduped_public.append(row)
    visible_public = deduped_public
    public_bodies = [
        _prose(item.get("body") or item.get("title") or "")
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
            participants = participant_roster_names(issue["participant_roster"])
        except (KeyError, IndexError, TypeError):
            participants = set()
        # Unassigned issues are public; assigned issues are visible only when
        # this character entered the durable source projection.
        if participants:
            if character_name not in participants or source_id not in known_source_ids:
                continue
        if not knowledge_row_visible_to(
            db,
            {"source_id": source_id, "excluded_names": "[]", "office_type": office_type, "office": office_name},
            character_name,
        ):
            continue
        try:
            target_roster = json.loads(str(issue["target_roster"] or "[]"))
        except (KeyError, TypeError, ValueError):
            target_roster = []
        if issue["origin_kind"] != "impeachment_surge" or not isinstance(target_roster, list):
            target_roster = []
        target_roster = [str(target).strip() for target in target_roster if str(target).strip()]
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
            "origin_turn": issue["origin_turn"],
            "end_turn": issue["end_turn"],
            "commitment_kind": issue["commitment_kind"],
            "target_roster": target_roster,
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
        lines.append(_prose(line))
    return "\n".join(lines)
