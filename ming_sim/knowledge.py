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
from ming_sim.public_sayings import (
    public_layer_events,
    public_layer_prose,
)


def _prose(text: object) -> str:
    """Carry durable report prose without mechanically interpreting it."""
    return str(text or "")


def _issue_audience_names(db: Any, issue: Any) -> set[str] | None:
    """Audience-name supplement for an event-origin issue, or ``None`` if N/A.

    ``events.audiences`` names a positive grant onto originating issues; it is
    not an ACL/veto over ``knowledge["issues"]``.  A legitimate empty list is an
    empty supplement.  DB execution errors and JSON/typed-shape malformations
    propagate unchanged.  Content fallback applies only when the events query
    succeeds with no row.
    """
    try:
        origin_kind = str(issue["origin_kind"] or "")
        origin_ref = str(issue["origin_ref"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return None
    if origin_kind != "event_pool":
        return None
    if not origin_ref:
        return set()

    raw: object = None
    saw_db_row = False
    row = db.conn.execute(
        "SELECT audiences FROM events WHERE id=?", (origin_ref,),
    ).fetchone()
    if row is not None:
        saw_db_row = True
        raw = row["audiences"]
    if not saw_db_row:
        content = db.content
        event_by_id = getattr(content, "event_by_id", None) or {}
        ev = event_by_id.get(origin_ref)
        if ev is None:
            return set()
        raw = getattr(ev, "audiences", None)

    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise TypeError(
            f"event {origin_ref!r} audiences must be a list[str], got {type(raw).__name__}"
        )
    names: set[str] = set()
    for idx, name in enumerate(raw):
        if not isinstance(name, str):
            raise TypeError(
                f"event {origin_ref!r} audiences[{idx}] must be str, "
                f"got {type(name).__name__}"
            )
        stripped = name.strip()
        if stripped:
            names.add(stripped)
    return names


def _reader_in_issue_audience(db: Any, issue: Any, character_name: str) -> bool:
    """Whether the optional audience supplement names this reader.

    ``None`` means the supplement does not apply. That is not a grant.
    An empty supplement does not name anyone. Malformed audience payloads
    still raise from ``_issue_audience_names``.
    """
    audiences = _issue_audience_names(db, issue)
    return bool(audiences) and character_name in audiences


def _exclusion_lists_from_row(row: Any) -> tuple[set[str], set[str], set[str]]:
    """Parse excluded_names and excluded_targets.people/offices from one row."""
    try:
        excluded_names = {
            str(name) for name in json.loads(row["excluded_names"] or "[]")
        }
    except (TypeError, ValueError, KeyError, IndexError):
        excluded_names = set()
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
    if not isinstance(targets, dict):
        targets = {}
    people = {str(name) for name in (targets.get("people") or [])}
    offices = {str(name) for name in (targets.get("offices") or [])}
    return excluded_names, people, offices


def _subject_matches_exclusion(
    subject: Any,
    fallback_name: str,
    *,
    excluded_names: set[str],
    people: set[str],
    offices: set[str],
) -> bool:
    """True when person name or current office/office_type hits exclusion lists."""
    if subject is None:
        name, office_type, office = fallback_name, "", ""
    else:
        try:
            name = str(subject["name"] or fallback_name)
            office_type = str(subject["office_type"] or "")
            office = str(subject["office"] or "")
        except (KeyError, IndexError, TypeError):
            name, office_type, office = fallback_name, "", ""
    if name in excluded_names or name in people:
        return True
    return bool(office_type and office_type in offices) or bool(
        office and office in offices
    )


def knowledge_row_visible_to(
    db: Any, row: Any, character_name: str, *, target: Any = None,
) -> bool:
    """Apply one source's person and current-position secrecy boundary.

    ``target`` is the person whose visibility is being tested.  When omitted,
    the subject is the reader, which is the projection's normal use case.
    Recommendation reads pass each roster candidate explicitly so an excluded
    office cannot be reintroduced by a name-only roster projection.
    """
    # #1853 J8-R2：成功持有 GameDB 后 conn 为必备能力；禁 AttributeError 洗成无读者。
    reader = db.conn.execute(
        "SELECT name, office, office_type FROM characters WHERE name=?", (character_name,)
    ).fetchone()
    target = target or reader or row
    def target_value(key: str) -> object:
        try:
            return target[key]
        except (KeyError, IndexError, TypeError):
            return None

    target_name = str(target_value("name") or target_value("character_id") or character_name)
    excluded_names, people, offices = _exclusion_lists_from_row(row)
    source_id = str(row["source_id"] or "")
    # 合成读模型行未必自带 excluded_names；source 上的持久黑名单仍是同一真源。
    excluded_names |= {
        str(name)
        for name in (db.knowledge_exclusions_for_source(source_id) or [])
    }
    if not people and not offices:
        fallback = db.knowledge_exclusion_targets_for_source(source_id)
        if isinstance(fallback, dict):
            people = {str(name) for name in (fallback.get("people") or [])}
            offices = {str(name) for name in (fallback.get("offices") or [])}
    if _subject_matches_exclusion(
        reader, character_name,
        excluded_names=excluded_names, people=people, offices=offices,
    ) or _subject_matches_exclusion(
        target, target_name,
        excluded_names=excluded_names, people=people, offices=offices,
    ):
        return False
    # A private source's roster is a positive capability, not a deny-list
    # snapshot.  Enforce it at read time so characters created after archival
    # cannot inherit old participant-private material.
    # #1853 J8-R2：conn 直调；行字段缺失由上层 Mapping 契约承担，不在此吞 AttributeError。
    source = db.conn.execute(
        "SELECT kind, participant_roster FROM character_knowledge_sources WHERE source_id=?",
        (str(row["source_id"] or ""),),
    ).fetchone()
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


def project_issue_materials(
    db: Any, character_name: str, knowledge: Dict[str, object],
) -> list[Dict[str, object]]:
    """Canonical materials projection: knowledge issues ∪ audience-named grant.

    Base visibility is exactly ``knowledge["issues"]``.  ``events.audiences``
    only adds originating issues that name this reader; it never removes a
    knowledge-visible issue.  A legitimate empty audience list is an empty
    supplement.
    """
    projected: dict[int, Dict[str, object]] = {}

    for issue in knowledge.get("issues") or []:
        issue_id = int(issue["id"])
        audiences = _issue_audience_names(db, issue)
        row = dict(issue)
        row["source_id"] = str(row.get("source_id") or f"issue:{issue_id}")
        row["audience_names"] = tuple(sorted(audiences or ()))
        projected[issue_id] = row

    active_issues = db.list_active_issues()
    for issue in active_issues:
        issue_id = int(issue["id"])
        if issue_id in projected:
            continue
        audiences = _issue_audience_names(db, issue)
        if not audiences or character_name not in audiences:
            continue
        row = {
            "id": issue_id,
            "kind": issue["kind"],
            "origin_kind": issue["origin_kind"],
            "origin_ref": issue["origin_ref"],
            "title": issue["title"],
            "stage_text": issue["stage_text"],
            "resolve_condition": issue["resolve_condition"],
            "fail_condition": issue["fail_condition"],
            "affair_id": int(issue["affair_id"] or 0),
            "participant_roster": issue["participant_roster"],
            "source_id": f"issue:{issue_id}",
            "audience_names": tuple(sorted(audiences)),
        }
        projected[issue_id] = row

    return list(projected.values())


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


def _appointment_register(db: Any, state: Any) -> str:
    """吏部任免簿：当前在朝职名，不是派系底账。"""
    rows = db.current_court_roster_rows(state)
    if not rows:
        return "任免簿：暂无。"
    return "任免簿：\n" + "\n".join(
        f"{row['name']}：{row['office'] or '无现任官职'}"
        for row in rows
    )


def _role_roster(db: Any, office_type: str, state: Any) -> str:
    """Return only the current roster for this office type.

    The role rail is intentionally queried from the current DB rather than
    copied from the character's event history.  It is therefore a real
    position-scoped fact set and updates automatically after appointments or
    restore, while the qualitative rendering keeps machine values out of the
    audience prompt.
    """
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
    rows = db.conn.execute(
        "SELECT turn, year, period, kind, title, body, source_id, "
        "participant_roster, excluded_names FROM character_knowledge_sources "
        "WHERE turn <= ? ORDER BY turn, id",
        (int(upto_turn),),
    ).fetchall()
    projected: list[Dict[str, object]] = []
    for row in rows:
        source_id = str(row["source_id"] or "")
        # Plain turn-report rows are rendered aggregate read models,
        # not independently authorizable sources.  Their explicit ``:public``
        # counterparts remain source-scoped and are projected below.
        if ((source_id.startswith("turn_report:") and not source_id.endswith(":public"))
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


def _household_secret_case_hidden(
    row: Any, character_name: str, reader: Any,
) -> bool:
    """户部流水密令案情是否对读者隐藏：复用 typed 密令 excluded_names / excluded_targets。"""
    excluded_names, people, offices = _exclusion_lists_from_row(row)
    return _subject_matches_exclusion(
        reader, character_name,
        excluded_names=excluded_names, people=people, offices=offices,
    )


def _household_ledger(db: Any, state: Any, character_name: str) -> str:
    """户部太仓账：保留密支数额，按 typed 密令关联裁去案情语义。"""
    balance = db.conn.execute(
        "SELECT balance FROM economy_accounts WHERE account='国库'"
    ).fetchone()
    rows = db.conn.execute(
        """SELECT e.year,e.period,e.delta,e.balance_after,e.category,e.reason,
                  s.excluded_names, s.excluded_targets
           FROM economy_ledger e
           LEFT JOIN decree_dossiers d ON d.id = CASE
             WHEN e.origin_ref LIKE 'dossier:%' THEN CAST(substr(e.origin_ref,9) AS INTEGER)
             ELSE e.dossier_id END
           LEFT JOIN secret_orders s ON s.id=d.secret_order_id
           WHERE e.account='国库' ORDER BY e.id DESC"""
    ).fetchall()
    # #1853 J8-R2：与上方 balance/rows 同为必备 conn 直调，禁缺能力软兼容。
    reader = db.conn.execute(
        "SELECT name, office, office_type FROM characters WHERE name=?",
        (character_name,),
    ).fetchone()
    lines = [f"太仓实存：{int(balance['balance'] if balance else state.metrics['国库'])}"]
    for row in reversed(rows):
        hide = _household_secret_case_hidden(row, character_name, reader)
        detail = "密支" if hide else str(row["reason"] or row["category"] or "收支")
        lines.append(
            f"{int(row['year'])}年{int(row['period'])}月：{int(row['delta']):+d}，"
            f"余额{int(row['balance_after'])}（{detail}）"
        )
    return "\n".join(lines)


def _army_register(db: Any) -> str:
    rows = db.conn.execute(
        "SELECT name,manpower FROM armies WHERE owner_power='ming' ORDER BY name"
    ).fetchall()
    return "兵籍在册：\n" + "\n".join(
        f"{row['name']}：{int(row['manpower'])}人" for row in rows
    )


def _world(
    db: Any, state: Any, character_name: str, office_name: str, office_type: str,
) -> tuple[Dict[str, str], Dict[str, tuple[str, ...]]]:
    """Project current truth only through exact durable person relationships."""
    result: Dict[str, str] = {
        "public": "登基伊始，朝廷暂无前回合奏报。",
        "role": _role_roster(db, office_type, state),
    }
    scope: Dict[str, tuple[str, ...]] = {"region_ids": (), "army_ids": ()}

    if office_type == "户部":
        result["treasury"] = _household_ledger(db, state, character_name)
    elif office_type == "兵部":
        result["military"] = _army_register(db)
    elif office_type == "吏部":
        result["personnel"] = _appointment_register(db, state)

    # Authoritative office→辖域 projection (shared with dossier archive keys).
    # Region from the holder's appointment (character_offices.region_id) — never location.
    projected = db.project_office_identity(
        office_name, office_type, character_name=character_name,
    ) or {}
    region_ids = tuple(
        str(rid) for rid in (projected.get("region_ids") or ()) if str(rid or "").strip()
    )
    if region_ids:
        scope["region_ids"] = region_ids
        # Materials/region detail use the primary jurisdiction when several.
        primary = region_ids[0]
        result["regional"] = _prose(db.region_detail(primary, qualitative=True))
        result["construction"] = _prose(
            db.buildings_report(region_id=primary, qualitative=True)
        )

    armies = db.conn.execute(
        "SELECT id,name FROM armies WHERE commander=? OR controller=? ORDER BY name",
        (character_name, character_name),
    ).fetchall()
    if armies:
        ids = tuple(str(row["id"]) for row in armies)
        scope["army_ids"] = ids
        details = db.army_roster(filter_names=list(ids), qualitative_equipment=True)
        result["command"] = _prose(details)
    return result, scope


def current_character_office(
    db: Any, character: Any, character_name: str = "",
) -> tuple[str, str]:
    """Current durable (office, office_type); missing DB row falls back to seed character fields."""
    name = str(character_name or getattr(character, "name", "") or "")
    current = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name = ?", (name,),
    ).fetchone()
    return (
        str((current["office"] if current is not None else getattr(character, "office", "")) or ""),
        str((current["office_type"] if current is not None else getattr(character, "office_type", "")) or ""),
    )


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
    (durable knowledge events remain distinct from prompt-only synthesis).
    """
    known = set(known_source_ids or ())
    synthesized: list[Dict[str, object]] = []
    active_issues = db.list_active_issues()
    for issue in active_issues:
        try:
            source_id = f"issue:{int(issue['id'])}"
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if source_id in known:
            continue
        try:
            stage = _prose(issue["stage_text"])
        except (KeyError, IndexError, TypeError):
            stage = ""
        if not str(stage).strip() or not _reader_in_issue_audience(db, issue, character_name):
            continue
        if not knowledge_row_visible_to(
            db,
            {"source_id": source_id},
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


def build_character_knowledge(
    db: Any, state: Any, character_name: str, *, public_feed: bool = False,
) -> Dict[str, object]:
    """个人知识投影；`public_feed=True` 时按公共供料边界投影公开说法。

    公开说法的排除边界按调用职责区分（#1829 F1）：人物读者走
    `knowledge_row_visible_to` 的按人排除；全量推演者（空姓名世界层）按
    ADR 0155 三层全看；只有公共供料方（公共邸报作者）没有可被排除的具体
    读者，须显式传 `public_feed=True` 落「受排除说法不进公共供料」边界。
    """
    character = db.content.characters.get(character_name) if db.content else None
    # The content object is the seed/in-memory roster and can lag behind a
    # restored save.  The characters table is the durable current-world source.
    office_name, office_type = current_character_office(db, character, character_name)
    world, scope = _world(db, state, character_name, office_name, office_type)
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

        Turn reports are rendered aggregates.  When their turn has source-scoped
        knowledge rows, those rows are the only material used for this character.
        Without an independent source, it grants nothing.
        """
        # Only durable source rows are inputs here.  The synthetic
        # ``turn_report:*`` rows below are read-model outputs; feeding one
        # archive back into the next would duplicate material.
        rows = []
        for row in public_events:
            source_id = str(row.get("source_id") or "")
            # ``turn_report:*:public`` is an explicit, source-scoped public
            # counterpart written by the archive API.
            aggregate_row = (
                source_id.startswith("opening:")
                or source_id.startswith("directive:")
                or (source_id.startswith("turn_report:") and not source_id.endswith(":public"))
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
        # material.  Do not add a report rendering of the same turn on top of them.
        if any(
            not row.get("excluded_names")
            and not str(row.get("source_id") or "").startswith("turn_report:")
            for row in rows
        ):
            return ""
        if counterpart_rows:
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
        elif source_id.startswith("projection:turn_report:"):
            turn = source_id.removeprefix("projection:turn_report:")
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
        # character-specific turn_report projection above is the only archive
        # representation allowed into the audience view.
        if not str(row.get("source_id") or "").startswith("turn_report:")
        and not re.fullmatch(r"settlement:narrative:\d+", str(row.get("source_id") or ""))
        # When a source-preserving archive projection exists for this turn,
        # expose it once through that archive rather than beside its source row.
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
    # Identity is the durable source_id.  Same prose, overlapping prose, or the
    # same turn does not make two sources one record.  An empty source_id has
    # no identity to collapse.  A repeated non-empty source_id is one record.
    # An explicit public event is the authoritative payload for that source
    # (the same priority knowledge_items_for_turn already uses on the write
    # side): it replaces an earlier projection, and a later non-public row
    # must not replace it.
    deduped_public = []
    index_by_source: dict[str, int] = {}
    for row in visible_public:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            deduped_public.append(row)
            continue
        slot = index_by_source.get(source_id)
        if slot is None:
            index_by_source[source_id] = len(deduped_public)
            deduped_public.append(row)
            continue
        if str(row.get("kind") or "") == "public":
            deduped_public[slot] = row
    # Independently persisted public sayings never enter the archive
    # aggregation/dedup rules above.  Append the authoritative public-layer
    # projection after those rules, then join its layer prose.
    public_saying_events = [
        {
            key: (_prose(value) if key == "body" else value)
            for key, value in row.items() if key != "excluded_names"
        }
        for row in public_layer_events(db, for_public_feed=public_feed)
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    visible_public = [*deduped_public, *public_saying_events]
    public_bodies = [
        _prose(item.get("body") or item.get("title") or "")
        for item in deduped_public
        if (item.get("body") or item.get("title"))
        and not str(item.get("source_id") or "").startswith("opening:")
    ]
    public_bodies.extend(public_layer_prose(item) for item in public_saying_events)
    world["public"] = "\n".join(public_bodies) or world["public"]
    known_source_ids = {
        str(row.get("source_id") or "")
        for row in [*events, *public_events]
        if row.get("source_id")
    }
    visible_issues = []
    for issue in db.list_active_issues():
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
            "origin_kind": issue["origin_kind"], "origin_ref": issue["origin_ref"],
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
            "affair_id": int(issue["affair_id"] or 0),
            "participant_roster": issue["participant_roster"],
        })
    return {
        "character_name": character_name,
        "office_type": office_type,
        "turn": int(state.turn),
        "world": world,
        "scope": scope,
        "events": visible_events,
        "public_events": visible_public,
        "issues": visible_issues,
    }
