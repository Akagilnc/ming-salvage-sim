"""Per-character knowledge projection (#489).

Personal records and independent public speech are read from their original
ledgers. Current office accounts are rebuilt from world state on every read.
"""

from __future__ import annotations

import json
import re

from typing import Any, Dict

from ming_sim.db import _load_durable_str_list
from ming_sim.participant_roster import participant_roster_names
from ming_sim.public_sayings import public_layer_events


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
    if "origin_kind" not in issue.keys():
        return None  # Non-event projections need not select event origin fields.
    origin_kind = str(issue["origin_kind"] or "")
    origin_ref = str(issue["origin_ref"] or "").strip()
    if origin_kind != "event_pool":
        return None  # Non-event projections need not select event origin fields.
    if not origin_ref:
        return set()

    raw: object = None
    saw_db_row = False
    row = db.conn.execute(
        'SELECT audiences FROM events WHERE id=?',
        (origin_ref,),
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
        # Content/event audience supplement: keep JSONDecodeError/TypeError surface
        # already locked by material-entry fail-loud cases (not an empty-facts wash).
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise TypeError(
            f"event {origin_ref!r} audiences must be a list[str], got {type(raw).__name__}"
        )
    names: set[str] = set()
    for idx, name in enumerate(raw):
        if not isinstance(name, str):
            raise TypeError(f"event {origin_ref!r} audiences[{idx}] must be str, got {type(name).__name__}")
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


def assert_origin_identity_exists(db: Any, origin: object) -> str:
    """Empty origin is public. Claimed durable identities must exist on the ledger.

    Covers ``secret_order:`` / ``dossier:`` / ``yamen:`` identity tokens only;
    free-form origins pass through. Unstorable ids → ``DeclarationDataError``;
    missing entities → ``DeclarationReferenceError`` (ADR 0015).
    """
    from ming_sim.exceptions import DeclarationDataError, DeclarationReferenceError
    from ming_sim.materials import (
        dossier_id_in_origin,
        origin_claims_secret_or_dossier,
        secret_order_id_in_origin,
    )
    from ming_sim.strict_types import strict_sqlite_id

    text = str(origin or "").strip()
    if not text:
        return ""
    yamen_match = re.match(r"yamen:(\d+)(?:[:/]|$)", text)
    if yamen_match is not None:
        try:
            yamen_id = strict_sqlite_id(yamen_match.group(1))
        except (TypeError, ValueError) as exc:
            raise DeclarationDataError("来源 yamen id 超出可存储范围或不可解析") from exc
        if db.yamens.get(yamen_id) is None:
            raise DeclarationReferenceError(f"yamen 不存在：{yamen_id}")
        return text
    if origin_claims_secret_or_dossier(text):
        secret_id = secret_order_id_in_origin(text)
        dossier_id = dossier_id_in_origin(text)
        if secret_id is None and dossier_id is None:
            raise DeclarationDataError("来源 id 超出可存储范围或不可解析")
        if secret_id is not None and db.character_knowledge.get_secret_order(secret_id) is None:
            raise DeclarationReferenceError(f"密令不存在：{secret_id}")
        if dossier_id is not None and db.dossiers.get(dossier_id) is None:
            raise DeclarationReferenceError(f"案卷不存在：{dossier_id}")
        return text
    return text


def origin_visible_to(
    db: Any, origin: object, character_name: str = "", *, linked_dossier_id: int = 0,
    _seen: frozenset[str] | None = None,
) -> bool:
    """Secret provenance grants only handlers; office/publicity never grants truth.

    Empty reader denotes the public feed, not the all-seeing world simulator.
    Affairs are associations, not access boundaries for their individual facts.
    ``yamen:<id>`` chases the office's own origin_ref (#1915 F1), same shape as
    dossier→secret_order; no separate permission model.

    Identity tokens reuse materials.secret_order_id_in_origin / dossier_id_in_origin
    (strict id). Unresolvable claimed secret/dossier/yamen identity fails closed
    (not public)—missing entity, cycle, or overflow never become public (#1915).
    """
    from ming_sim.materials import (
        dossier_id_in_origin,
        inquiry_source_order_id,
        origin_claims_secret_or_dossier,
        secret_order_id_in_origin,
    )
    from ming_sim.strict_types import strict_sqlite_id

    source = str(origin or "")
    seen = _seen or frozenset()
    if source and source in seen:
        return False
    yamen_match = re.match(r"yamen:(\d+)(?:[:/]|$)", source)
    if yamen_match is not None:
        try:
            yamen_id = strict_sqlite_id(yamen_match.group(1))
        except (TypeError, ValueError):
            return False
        yamen = db.yamens.get(yamen_id)
        if yamen is None:
            # Claimed yamen identity with no ledger row is not a public source.
            return False
        nested = str(getattr(yamen, "origin_ref", "") or "").strip()
        if nested and nested != source:
            return origin_visible_to(
                db, nested, character_name, linked_dossier_id=linked_dossier_id,
                _seen=seen | {source},
            )
    registered = db.conn.execute(
        'SELECT kind, participant_roster FROM character_knowledge_sources WHERE source_id=?',
        (source,),
    ).fetchone()
    if registered is not None and registered["kind"] != "public":
        participants = participant_roster_names(registered["participant_roster"])
        if participants and character_name not in participants:
            return False
    oral = re.match(r"chat_message:(\d+)$", source)
    if oral and int(oral.group(1)) in db._secret_origin_message_ids(character_name):
        return False
    order_id = secret_order_id_in_origin(source) or 0
    claimed_dossier_id = dossier_id_in_origin(source)
    if origin_claims_secret_or_dossier(source) and order_id == 0 and claimed_dossier_id is None:
        # 自称密令/案卷但 id 不可存储或不可解析：不得当公开。
        return False
    dossier_id = claimed_dossier_id or int(linked_dossier_id or 0)
    if dossier_id:
        row = db.conn.execute(
            'SELECT secret_order_id FROM decree_dossiers WHERE id=?',
            (dossier_id,),
        ).fetchone()
        if row is None:
            # Claimed or linked dossier missing from ledger: not public.
            return False
        try:
            linked = strict_sqlite_id(row["secret_order_id"] or 0)
        except (TypeError, ValueError):
            return False
        if linked:
            order_id = linked
    if not order_id:
        return True
    if not character_name:
        return False
    order = db.character_knowledge.get_secret_order(order_id)
    if order is None:
        return False
    if character_name == str(order["minister_name"]):
        return True
    dossier = db.dossiers.get_for_secret_order(order_id)
    if dossier is not None and character_name in participant_roster_names(dossier["participant_roster"]):
        return True
    # Inquiry assignments are actual delegated handling, not a position grant.
    return any(
        inquiry_source_order_id(event["source_id"]) == order_id
        for event in db._character_knowledge_events(character_name)
        if event["kind"] == "inquiry_assignment"
    )


def knowledge_row_visible_to(db: Any, row: Any, character_name: str) -> bool:
    """Public speech is universal; private sources retain their own roster."""
    item = dict(row)
    if item.get("kind") == "public":
        return True
    source_id = str(item.get("source_id") or "")
    return origin_visible_to(db, source_id, character_name)


def project_court_roster_rows(
    rows: list[Any], knowledge: Dict[str, object], office_type: str,
) -> list[Any]:
    """Project complete structured roster rows through one character's view.

    The complete roster remains an internal query result.  Full-court admission
    is the 吏部 appointment-register capability (office_type), not the mere
    presence of a personnel archive key — 近侍 also carries that key for 官缺
    without full-roster grant (#1914 / ADR 0034). Otherwise only the reader's
    current role roster crosses the output boundary. Free-prose name hits in
    event bodies are not an admission grant (ADR 0142 / #1834 F46).
    """
    current_office_type = str(knowledge.get("office_type") or office_type or "")
    if current_office_type == "吏部":
        return list(rows)
    return [
        row for row in rows
        if str(row["office_type"] or "") == current_office_type
    ]


def _appointment_register(db: Any, state: Any) -> str:
    """吏部任免簿：当前在朝职名，不是派系底账。"""
    rows = db.characters.current_court_rows(int(state.year), int(state.period))
    if not rows:
        return "任免簿：暂无。"
    return "任免簿：\n" + "\n".join(
        f"{row['name']}：{row['office'] or '无现任官职'}"
        for row in rows
    )


def _household_ledger(db: Any, state: Any, character_name: str) -> str:
    """户部太仓账：保留密支数额，按 typed 密令关联裁去案情语义。"""
    balance = db.conn.execute(
        "SELECT balance FROM economy_accounts WHERE account='国库'",
        (),
    ).fetchone()
    rows = db.conn.execute(
        """
        SELECT e.year,e.period,e.delta,e.balance_after,e.category,e.reason,
                              e.origin_ref,e.dossier_id
                       FROM economy_ledger e
                       WHERE e.account='国库' ORDER BY e.id DESC
        """,
        (),
    ).fetchall()
    lines = [f"太仓实存：{int(balance['balance'] if balance else state.metrics['国库'])}"]
    for row in reversed(rows):
        hide = not origin_visible_to(db, row["origin_ref"], character_name,
                                     linked_dossier_id=int(row["dossier_id"] or 0))
        detail = "密支" if hide else str(row["reason"] or row["category"] or "收支")
        lines.append(
            f"{int(row['year'])}年{int(row['period'])}月：{int(row['delta']):+d}，"
            f"余额{int(row['balance_after'])}（{detail}）"
        )
    return "\n".join(lines)


def _army_register(db: Any) -> str:
    rows = db.conn.execute("SELECT name,manpower FROM armies WHERE owner_power='ming' ORDER BY name", ()).fetchall()
    return "兵籍在册：\n" + "\n".join(
        f"{row['name']}：{int(row['manpower'])}人" for row in rows
    )


def _office_vacancy_register(db: Any) -> str:
    """官缺底账：office_vacancies 视图（静态职缺 + 现任）。"""
    rows = db.conn.execute(
        """
        SELECT office_title, jurisdiction, holder_name
        FROM office_vacancies
        ORDER BY sort_order, office_title
        """,
        (),
    ).fetchall()
    if not rows:
        return "官缺：暂无。"
    lines: list[str] = []
    for row in rows:
        # office_slots.office_title 是 PRIMARY KEY，视图侧不会空。
        title = str(row["office_title"])
        jur = str(row["jurisdiction"] or "").strip()
        holder = str(row["holder_name"] or "").strip()
        place = f"（{jur}）" if jur else ""
        if holder:
            lines.append(f"{title}{place}：现任{holder}")
        else:
            lines.append(f"{title}{place}：空缺")
    return "官缺：\n" + "\n".join(lines)


def _province_overview(db: Any) -> str:
    """各省概况：两京／布政司定性警讯（输入侧收窄既有 PROVINCE_KINDS）。"""
    from ming_sim.execution_pressure import PROVINCE_KINDS

    # region_report 无行时固定返回「地区尚未建档。」，不另写空串兜底。
    body = _prose(db.region_report(limit=None, kinds=PROVINCE_KINDS))
    return f"各省概况：\n{body}"


def _world(
    db: Any, state: Any, character_name: str, office_name: str, office_type: str,
) -> tuple[Dict[str, str], Dict[str, tuple[str, ...]]]:
    """Project current truth only through exact durable person relationships."""
    result: Dict[str, str] = {}
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

    # #1914 / ADR 0034 局部例外：御前近侍可读官缺与各省概况（非全体人物全知）。
    # 放在辖域投影之后直接覆盖 regional，省掉「键是否已有」条件。
    from ming_sim.audience_night import is_inner_court_attendant

    if is_inner_court_attendant({"office": office_name}):
        result["personnel"] = _office_vacancy_register(db)
        result["regional"] = _province_overview(db)

    armies = db.conn.execute(
        'SELECT id,name FROM armies WHERE commander=? OR controller=? ORDER BY name',
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
        'SELECT office, office_type FROM characters WHERE name = ?',
        (name,),
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
    active_issues = db.issues.active_rows()
    for issue in active_issues:
        source_id = f"issue:{int(issue['id'])}"
        if source_id in known:
            continue
        stage = _prose(issue["stage_text"])
        if not origin_visible_to(db, issue["origin_ref"], character_name):
            continue
        if not str(stage).strip() or not _reader_in_issue_audience(db, issue, character_name):
            continue
        if not knowledge_row_visible_to(
            db,
            {"source_id": source_id},
            character_name,
        ):
            continue
        origin_turn = int(issue["origin_turn"] or state.turn)
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
    db: Any, state: Any, character_name: str,
) -> Dict[str, object]:
    """Current office accounts, personal handling, and independently public speech."""
    character = db.content.characters.get(character_name) if db.content else None
    # The content object is the seed/in-memory roster and can lag behind a
    # restored save.  The characters table is the durable current-world source.
    office_name, office_type = current_character_office(db, character, character_name)
    world, scope = _world(db, state, character_name, office_name, office_type)
    events = db._character_knowledge_events(character_name) if character_name else []
    public_events = db._character_knowledge_events("")
    # Issued directives are public; read their original records.
    for directive in db.issues.list_issued_directives():
        public_events.append({
            "turn": int(directive["turn"]), "year": int(directive["year"]),
            "period": int(directive["period"]), "kind": "public",
            "title": directive.get("event_title") or "明发旨意",
            "body": _prose(directive.get("text") or ""),
            "source_id": f"directive:{directive['id']}",
        })
    visible_events = [dict(row) for row in events
                      if knowledge_row_visible_to(db, row, character_name)]
    # Public versions and personal sources have separate carriers.
    visible_public = [dict(row) for row in public_events
                      if knowledge_row_visible_to(db, row, character_name)]
    # Public versions have their own durable records; registered sources are
    # read directly, without an archival mirror or payload precedence rule.
    public_saying_events = [
        {
            key: (_prose(value) if key == "body" else value)
            for key, value in row.items()
        }
        for row in public_layer_events(db)
        if knowledge_row_visible_to(
            db,
            {**row, "office_type": office_type, "office": office_name},
            character_name,
        )
    ]
    visible_public.extend(public_saying_events)
    visible_issues = []
    for issue in db.issues.active_rows():
        if not origin_visible_to(db, issue["origin_ref"], character_name):
            continue
        source_id = f"issue:{issue['id']}"
        participants = participant_roster_names(issue["participant_roster"])
        if participants and character_name not in participants:
            continue
        if not knowledge_row_visible_to(
            db,
            {"source_id": source_id, "office_type": office_type, "office": office_name},
            character_name,
        ):
            continue
        if issue["origin_kind"] != "impeachment_surge":
            target_roster = []
        else:
            target_roster = _load_durable_str_list(
                issue["target_roster"], surface="issues.target_roster",
            )
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
