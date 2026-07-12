"""大臣荐人读取与审计写入（#493）。"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from .knowledge import knowledge_row_visible_to
from .qualitative import qualitative_bucket


def _identity_bucket(value: object) -> int:
    """Use the same low/middle/high identity cuts as minister context."""
    return qualitative_bucket(value, (40, 80), default=50)

def _source_visible_to(row: Any, recommender: str, *, target: Any = None, db: Any) -> bool:
    """Apply the #459 exclusion boundary before using a source's roster."""
    return knowledge_row_visible_to(db, row, recommender, target=target)


def _roster_names(raw: object) -> set[str]:
    try:
        roster = json.loads(raw or "[]")
    except (TypeError, ValueError):
        roster = []
    if not isinstance(roster, list):
        return set()
    return {
        str(item.get("character_id") or item.get("name"))
        for item in roster
        if isinstance(item, dict) and (item.get("character_id") or item.get("name"))
    }


def _known_names(db: Any, recommender: str) -> set[str]:
    """Return names in the recommender's visible private/public event rosters."""
    names: set[str] = set()
    conn = getattr(db, "conn", None)
    if conn is None:
        return names
    def add_visible_roster(source: Any, event: Any = None) -> None:
        if source is None:
            return
        if event is not None and not _source_visible_to(event, recommender, db=db):
            return
        if not _source_visible_to(source, recommender, db=db):
            return
        for name in _roster_names(source["participant_roster"]):
            target = conn.execute(
                "SELECT name, office, office_type FROM characters WHERE name=?", (name,)
            ).fetchone()
            if target is not None and _source_visible_to(source, recommender, target=target, db=db):
                if event is None or _source_visible_to(event, recommender, target=target, db=db):
                    names.add(name)

    for source, event in _visible_sources(db, recommender):
        add_visible_roster(source, event)
    return names


def _visible_sources(db: Any, recommender: str) -> Iterable[tuple[Any, Any]]:
    """Yield sources the recommender may read, with their participation event."""
    conn = db.conn
    rows = conn.execute(
        "SELECT source_id, excluded_names FROM character_knowledge_events WHERE character_name=?",
        (recommender,),
    ).fetchall()
    for row in rows:
        source = conn.execute(
            "SELECT source_id, participant_roster, excluded_names, excluded_targets "
            "FROM character_knowledge_sources WHERE source_id=?",
            (row["source_id"],),
        ).fetchone()
        yield source, row

    # A durable source is sufficient evidence of direct participation.  The
    # audience event mirror may not have been materialized yet (for example,
    # immediately after a source is written), and recommendations must not
    # lose an otherwise reachable candidate in that interval.
    for source in conn.execute(
        "SELECT source_id, participant_roster, excluded_names, excluded_targets "
        "FROM character_knowledge_sources"
    ).fetchall():
        if recommender in _roster_names(source["participant_roster"]):
            yield source, None

    # Public sources are visible without a direct participation row.  Their
    # structured roster is the public-event side of the #459 read projection.
    for source in conn.execute(
        "SELECT source_id, participant_roster, excluded_names, excluded_targets "
        "FROM character_knowledge_sources WHERE kind='public'"
    ).fetchall():
        yield source, None


def _excluded_from_visible_source(db: Any, recommender: str, target: Any) -> bool:
    """Return whether a source about *this* target excludes it.

    An exclusion is a boundary on one source's participant roster, not a
    global office-wide veto over candidates independently known elsewhere.
    """
    for source, event in _visible_sources(db, recommender):
        if source is None or not _source_visible_to(source, recommender, db=db):
            continue
        if event is not None and not _source_visible_to(event, recommender, db=db):
            continue
        if str(target["name"]) not in _roster_names(source["participant_roster"]):
            continue
        if not _source_visible_to(source, recommender, target=target, db=db):
            return True
        if event is not None and not _source_visible_to(event, recommender, target=target, db=db):
            return True
    return False


def list_recommendation_candidates(db: Any, state: Any, recommender: str) -> List[Dict[str, object]]:
    """Build the two recommendation slices visible to one minister.

    Same-faction people form the probe's network rail; durable participation rows
    form the minister-specific knowledge rail.  No global roster fallback is
    allowed, so an unrelated person remains invisible.
    """
    conn = getattr(db, "conn", None)
    if conn is None:
        return []
    source = conn.execute(
        "SELECT faction, identity, name, office, office_type FROM characters WHERE name=?", (recommender,)
    ).fetchone()
    if source is None:
        return []
    faction = str(source["faction"] or "")
    recommender_identity_bucket = _identity_bucket(source["identity"])
    known = _known_names(db, recommender)
    rows = conn.execute(
        "SELECT name, office, office_type, faction, identity, status, reason_code, status_reason "
        "FROM characters WHERE name != ? AND power_id='ming' "
        "AND faction != '流寇' AND office_type NOT IN ('后宫','宗藩','未仕') "
        "AND status IN ('active','offstage','retired','dismissed') "
        "AND NOT (debut_year > 0 AND "
        "(debut_year > ? OR (debut_year = ? AND debut_month > ?))) "
        "ORDER BY name",
        (recommender, int(state.year), int(state.year), int(state.period)),
    ).fetchall()
    result: List[Dict[str, object]] = []
    for row in rows:
        if _excluded_from_visible_source(db, recommender, row):
            continue
        same_faction = str(row["faction"] or "") == faction
        if (
            same_faction
            and str(row["name"]) not in known
            and _identity_bucket(row["identity"]) > recommender_identity_bucket
        ):
            continue
        if not same_faction and str(row["name"]) not in known:
            continue
        status = str(row["status"] or "")
        # ADR 0009 决定 10 的 active 人才池分支锚定「听用候铨」及
        # reason_code=被顶替；office 单独命中会把其它身名分误标为起复。
        is_displaced_holder = (
            status == "active"
            and row["office"] == "听用候铨"
            and row["reason_code"] == "被顶替"
        )
        kind = "荐起复" if status != "active" or is_displaced_holder else "荐在职"
        basis = "本派系网络" if str(row["faction"] or "") == faction else "见闻中有其人"
        result.append({
            "name": row["name"], "office": row["office"] or "",
            "office_type": row["office_type"] or "", "faction": row["faction"] or "",
            "status": status, "reason_code": row["reason_code"] or "",
            "status_reason": row["status_reason"] or "", "candidate_kind": kind,
            "basis": basis,
        })
    return result


def build_recommendation_brief(db: Any, state: Any, recommender: str) -> str:
    """Render the minister's already-filtered recommendation slice for context."""
    rows = list_recommendation_candidates(db, state, recommender)
    if not rows:
        return "【可荐人切片】本大臣眼下没有可据以具名荐人的人选。"
    lines = ["【可荐人切片】（已按本大臣派系网络与见闻过滤）"]
    for row in rows:
        status = row["status_reason"] or row["reason_code"] or row["status"]
        if row["candidate_kind"] == "荐起复":
            lines.append(
                f"{row['name']}：荐起复；原职/身份={row['office'] or '居家'}；"
                f"来历={status}；依据={row['basis']}。"
            )
        else:
            lines.append(
                f"{row['name']}：荐在职作破格差遣；现职={row['office'] or '在朝'}；"
                f"依据={row['basis']}。"
            )
    return "\n".join(lines)


def validate_recommendation_snapshot(
    db: Any, state: Any, recommender: str, snapshot: Dict[str, object],
) -> bool:
    """Check a staged recommendation before appointment mutates its candidate."""
    name = str(snapshot.get("name") or "").strip()
    if not name:
        return False
    current = next(
        (row for row in list_recommendation_candidates(db, state, recommender)
         if row["name"] == name),
        None,
    )
    if current is None:
        return False
    return all(
        current.get(key) == snapshot.get(key)
        for key in ("candidate_kind", "basis", "status", "office", "faction")
    )


def record_recommendation(db: Any, state: Any, recommender: str,
                          candidate: Dict[str, object], target_office: str,
                          reason: str = "") -> int:
    """Persist one adopted recommendation and its provenance."""
    # Event consumers use the stable semantic kind; the UI/tool slice keeps the
    # action-oriented labels 荐起复/荐在职.
    event_kind = {"荐起复": "起复", "荐在职": "在职"}.get(
        str(candidate.get("candidate_kind") or ""), str(candidate.get("candidate_kind") or "")
    )
    cur = db.conn.execute(
        """INSERT INTO recommendation_events
           (turn,year,period,recommender,candidate,candidate_kind,target_office,basis,reason,status)
           VALUES (?,?,?,?,?,?,?,?,?,'adopted')""",
        (int(state.turn), int(state.year), int(state.period), recommender,
         str(candidate.get("name") or ""), event_kind,
         target_office, str(candidate.get("basis") or ""), reason),
    )
    return int(cur.lastrowid)


def list_recommendation_events(db: Any, state: Any, recommender: str | None = None) -> List[Dict[str, object]]:
    sql = "SELECT * FROM recommendation_events WHERE turn <= ?"
    params: list[object] = [int(state.turn)]
    if recommender:
        sql += " AND recommender=?"
        params.append(recommender)
    sql += " ORDER BY turn, id"
    return [dict(row) for row in db.conn.execute(sql, params).fetchall()]
