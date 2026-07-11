"""大臣荐人读取与审计写入（#493）。"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List


def _source_visible_to(row: Any, recommender: str) -> bool:
    """Apply the #459 exclusion boundary before using a source's roster."""
    try:
        excluded = json.loads(row["excluded_names"] or "[]")
    except (TypeError, ValueError, KeyError, IndexError):
        excluded = []
    if recommender in {str(name) for name in excluded}:
        return False
    try:
        targets = json.loads(row["excluded_targets"] or "{}")
    except (TypeError, ValueError, KeyError, IndexError):
        targets = {}
    people = targets.get("people", []) if isinstance(targets, dict) else []
    return recommender not in {str(name) for name in people}


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
    rows = conn.execute(
        "SELECT source_id, excluded_names FROM character_knowledge_events WHERE character_name=?",
        (recommender,),
    ).fetchall()
    for row in rows:
        if not _source_visible_to(row, recommender):
            continue
        source = conn.execute(
            "SELECT participant_roster, excluded_names, excluded_targets "
            "FROM character_knowledge_sources WHERE source_id=?",
            (row["source_id"],),
        ).fetchone()
        if source is not None and _source_visible_to(source, recommender):
            names.update(_roster_names(source["participant_roster"]))

    # Public sources are visible without a direct participation row.  Their
    # structured roster is the public-event side of the #459 read projection.
    for source in conn.execute(
        "SELECT participant_roster, excluded_names, excluded_targets "
        "FROM character_knowledge_sources WHERE kind='public'"
    ).fetchall():
        if _source_visible_to(source, recommender):
            names.update(_roster_names(source["participant_roster"]))
    return names


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
        "SELECT faction FROM characters WHERE name=?", (recommender,)
    ).fetchone()
    if source is None:
        return []
    faction = str(source["faction"] or "")
    known = _known_names(db, recommender)
    rows = conn.execute(
        "SELECT name, office, office_type, faction, status, reason_code, status_reason "
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
        if str(row["faction"] or "") != faction and str(row["name"]) not in known:
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
