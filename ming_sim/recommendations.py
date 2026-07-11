"""大臣荐人读取与审计写入（#493）。"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List


def _known_names(db: Any, recommender: str) -> set[str]:
    """Return people named in the recommender's durable participation/knowledge rows."""
    names: set[str] = set()
    conn = getattr(db, "conn", None)
    if conn is None:
        return names
    rows = conn.execute(
        "SELECT source_id FROM character_knowledge_events WHERE character_name=?",
        (recommender,),
    ).fetchall()
    for row in rows:
        source = conn.execute(
            "SELECT participant_roster FROM character_knowledge_sources WHERE source_id=?",
            (row["source_id"],),
        ).fetchone()
        if source is None:
            continue
        try:
            roster = json.loads(source["participant_roster"] or "[]")
        except (TypeError, ValueError):
            roster = []
        if isinstance(roster, list):
            for item in roster:
                if isinstance(item, dict):
                    name = item.get("character_id") or item.get("name")
                    if name:
                        names.add(str(name))
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
        "AND status IN ('active','offstage','retired','dismissed') ORDER BY name",
        (recommender,),
    ).fetchall()
    result: List[Dict[str, object]] = []
    for row in rows:
        if str(row["faction"] or "") != faction and str(row["name"]) not in known:
            continue
        status = str(row["status"] or "")
        kind = "荐在职" if status == "active" else "荐起复"
        basis = "本派系网络" if str(row["faction"] or "") == faction else "见闻中有其人"
        result.append({
            "name": row["name"], "office": row["office"] or "",
            "office_type": row["office_type"] or "", "faction": row["faction"] or "",
            "status": status, "reason_code": row["reason_code"] or "",
            "status_reason": row["status_reason"] or "", "candidate_kind": kind,
            "basis": basis,
        })
    return result


def record_recommendation(db: Any, state: Any, recommender: str,
                          candidate: Dict[str, object], target_office: str,
                          reason: str = "") -> int:
    """Persist one adopted recommendation and its provenance."""
    cur = db.conn.execute(
        """INSERT INTO recommendation_events
           (turn,year,period,recommender,candidate,candidate_kind,target_office,basis,reason,status)
           VALUES (?,?,?,?,?,?,?,?,?,'adopted')""",
        (int(state.turn), int(state.year), int(state.period), recommender,
         str(candidate.get("name") or ""), str(candidate.get("candidate_kind") or ""),
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
