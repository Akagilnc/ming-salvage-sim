"""大臣荐人读取与审计写入（#493；#1931 删预筛切片与派系／见闻资格闸）。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .relations import EMPEROR_NODE


def _fact_candidate_row(row: Any) -> Dict[str, object]:
    status = str(row["status"] or "")
    # ADR 0009 决定 10 的 active 人才池分支锚定「听用候铨」及
    # reason_code=被顶替；office 单独命中会把其它身名分误标为起复。
    is_displaced_holder = (
        status == "active"
        and row["office"] == "听用候铨"
        and row["reason_code"] == "被顶替"
    )
    kind = "荐起复" if status != "active" or is_displaced_holder else "荐在职"
    return {
        "name": row["name"],
        "office": row["office"] or "",
        "office_type": row["office_type"] or "",
        "faction": row["faction"] or "",
        "status": status,
        "reason_code": row["reason_code"] or "",
        "status_reason": row["status_reason"] or "",
        "candidate_kind": kind,
        # #1931：不再按派系／见闻标注依据；空串满足 NOT NULL 列。
        "basis": "",
    }


_FACT_CANDIDATE_WHERE = (
    # #1931 J2：归明以 power_id='ming' 为准；faction 可仍为「流寇」（招抚保留标签），
    # 不得再以派系标签否决可荐事实。
    "power_id='ming' AND "
    "office_type NOT IN ('后宫','宗藩','未仕') AND "
    "status IN ('active','offstage','retired','dismissed') AND "
    "NOT (debut_year > 0 AND (debut_year > ? OR (debut_year = ? AND debut_month > ?)))"
)


def recommender_on_ledger(db: Any, recommender: str) -> bool:
    """荐者须在人物账上；不查派系／见闻／在场资格（#1931 F1）。"""
    name = str(recommender or "").strip()
    if not name:
        return False
    return (
        db.conn.execute(
            "SELECT 1 FROM characters WHERE name=?", (name,),
        ).fetchone()
        is not None
    )


def lookup_recommendation_candidate(
    db: Any, state: Any, name: str, *, recommender: str = "",
) -> Optional[Dict[str, object]]:
    """按账上事实取一名可荐对象；不按派系／见闻过滤（#1931）。

    荐者在册由 ``recommender_on_ledger`` / ``validate_recommendation_snapshot``
    与受理闸共用判断；本函数只取被荐者事实行（并排除自荐）。
    """
    target = str(name or "").strip()
    if not target:
        return None
    if recommender and target == str(recommender).strip():
        return None
    row = db.conn.execute(
        "SELECT name, office, office_type, faction, status, reason_code, "
        f"status_reason FROM characters WHERE name = ? AND {_FACT_CANDIDATE_WHERE}",
        (target, int(state.year), int(state.year), int(state.period)),
    ).fetchone()
    if row is None:
        return None
    return _fact_candidate_row(row)


def validate_recommendation_snapshot(
    db: Any, state: Any, recommender: str, snapshot: Dict[str, object],
) -> bool:
    """Check a staged recommendation before appointment mutates its candidate."""
    if not recommender_on_ledger(db, recommender):
        return False
    name = str(snapshot.get("name") or "").strip()
    if not name:
        return False
    current = lookup_recommendation_candidate(
        db, state, name, recommender=recommender,
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
        """
        INSERT INTO recommendation_events
                   (turn,year,period,recommender,candidate,candidate_kind,target_office,basis,reason,status)
                   VALUES (?,?,?,?,?,?,?,?,?,'adopted')
        """,
        (
            int(state.turn),
            int(state.year),
            int(state.period),
            recommender,
            str(candidate.get('name') or ''),
            event_kind,
            target_office,
            str(candidate.get('basis') or ''),
            reason,
        ),
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
        row = db.person_logs.relation_by_origin(
            leg_source, leg_target, leg_kind, base, f"{base}|%"
        )
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
