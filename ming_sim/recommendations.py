"""大臣荐人读取与审计写入（#493）。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .knowledge import knowledge_row_visible_to
from .participant_roster import participant_roster_names
from .relations import EMPEROR_NODE


def _known_names(db: Any, recommender: str) -> set[str]:
    """Return names in the recommender's visible private/public event rosters."""
    names: set[str] = set()
    conn = getattr(db, "conn", None)
    if conn is None:
        return names
    def add_visible_roster(source: Any, event: Any = None) -> None:
        if source is None:
            return
        if event is not None and not knowledge_row_visible_to(db, event, recommender):
            return
        if not knowledge_row_visible_to(db, source, recommender):
            return
        for name in participant_roster_names(source["participant_roster"]):
            target = conn.execute(
                "SELECT name, office, office_type FROM characters WHERE name=?", (name,)
            ).fetchone()
            if target is not None and knowledge_row_visible_to(
                db, source, recommender, target=target,
            ):
                if event is None or knowledge_row_visible_to(db, event, recommender, target=target):
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
        if recommender in participant_roster_names(source["participant_roster"]):
            yield source, None

    # Public sources are visible without a direct participation row.  Their
    # structured roster is the public-event side of the #459 read projection.
    for source in conn.execute(
        "SELECT source_id, participant_roster, excluded_names, excluded_targets "
        "FROM character_knowledge_sources WHERE kind='public'"
    ).fetchall():
        yield source, None


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
        same_faction = str(row["faction"] or "") == faction
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


def record_recommendation_edges(db: Any, state: Any, recommender: str,
                                candidate: str, event_id: int, reason: str) -> tuple[int, int]:
    """荐人口双边写口（#635，ADR 0081/0082；庭裁 r2/r3）。

    获准荐任恰写两条边，随调用方 applier.atomic 事务同生共死——
    边1：荐主→被荐人 kind=`恩义`；边2：君(EMPEROR_NODE)→荐主 kind=`知遇`。
    context=荐词原句逐字透传，非空必填（空则响亮拒绝，零模板宪法）。
    幂等锚=origin `recommendation:{event_id}:{恩义|知遇}`，写口自动追加
    `|round:{turn}` 后缀；重放同一事件 id 不重写。荐人专属的稳定 origin
    判重归本语义拥有者（与 credit_events::_existing_edge_id 同构），通用写口
    record_relation_edge_event 保持精确事件身份，不为单一消费者扩权。
    """
    # 荐词原句逐字透传，只以 strip 判空，不裁剪持久化文本。
    text = str(reason or "")
    if not text.strip():
        raise ValueError("荐人双边缺非空荐词语境：reason 必填、逐字透传")
    source = str(recommender or "").strip()
    target = str(candidate or "").strip()
    if not source or not target:
        raise ValueError("荐人双边荐主/被荐人不能为空")
    turn, year, period = int(state.turn), int(state.year), int(state.period)

    def _existing_leg_id(leg_kind: str, leg_source: str, leg_target: str) -> int | None:
        """荐人专属幂等：稳定 origin（|round 后缀前）+端点+腿别，跨回合、
        忽略可变 context；命中即返回原 id，不重写。"""
        base = f"recommendation:{int(event_id)}:{leg_kind}"
        row = db.conn.execute(
            """
            SELECT id FROM relation_edge_events
            WHERE source = ? AND target = ? AND event_kind = ?
              AND (origin = ? OR origin LIKE ?)
            ORDER BY id LIMIT 1
            """,
            (leg_source, leg_target, leg_kind, base, f"{base}|%"),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    grace = _existing_leg_id("恩义", source, target)
    if grace is None:
        grace = db.record_relation_edge_event(
            source=source, target=target, event_kind="恩义", context=text,
            origin=f"recommendation:{int(event_id)}:恩义",
            turn=turn, year=year, period=period,
        )
    zhiyu = _existing_leg_id("知遇", EMPEROR_NODE, source)
    if zhiyu is None:
        zhiyu = db.record_relation_edge_event(
            source=EMPEROR_NODE, target=source, event_kind="知遇", context=text,
            origin=f"recommendation:{int(event_id)}:知遇",
            turn=turn, year=year, period=period,
        )
    return grace, zhiyu


def list_recommendation_events(db: Any, state: Any, recommender: str | None = None) -> List[Dict[str, object]]:
    sql = "SELECT * FROM recommendation_events WHERE turn <= ?"
    params: list[object] = [int(state.turn)]
    if recommender:
        sql += " AND recommender=?"
        params.append(recommender)
    sql += " ORDER BY turn, id"
    return [dict(row) for row in db.conn.execute(sql, params).fetchall()]
