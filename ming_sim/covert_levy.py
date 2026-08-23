"""#651 暗渠摊派事实投影。

不定义 extractor 包装、判决或第二状态机：判官复用案卷输入，实况复用 #622/#649，
揭破只进入 next_audience_todos 的唯一 dispatcher。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

ENTRY_KIND = "covert_levy_exposure"


def _issue_for_dossier(db: Any, dossier_id: int) -> int:
    row = db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? ORDER BY id LIMIT 1",
        (f"dossier:{int(dossier_id)}",),
    ).fetchone()
    return int(row["id"]) if row is not None else 0


def army_pay_fact_for_dossier(db: Any, dossier_id: int) -> Dict[str, object] | None:
    """把月结真值附在既有案卷判官输入，不另造 simulator payload。"""
    row = db.conn.execute(
        """SELECT d.target_id army_id,a.arrears,a.consecutive_pay_shortfall_months
           FROM decree_dossiers d JOIN armies a ON a.id=d.target_id
           WHERE d.id=? AND d.target_kind='army'""",
        (int(dossier_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "army_id": str(row["army_id"]),
        "arrears": float(row["arrears"] or 0),
        "consecutive_pay_shortfall_months": int(row["consecutive_pay_shortfall_months"] or 0),
    }


def build_covert_levy_candidates(db: Any) -> List[Dict[str, object]]:
    """兼容读端：候选只是案卷事实，不是生产协议。"""
    out: List[Dict[str, object]] = []
    rows = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE status='executing' ORDER BY id"
    ).fetchall()
    for row in rows:
        did = int(row["id"])
        fact = army_pay_fact_for_dossier(db, did)
        if fact is not None and _issue_for_dossier(db, did) > 0:
            out.append({"dossier_id": did, **fact})
    return out


def settle_exposure_from_canonical_actions(db: Any, state: Any, applied: Mapping[str, object]) -> int:
    """只凭 canonical applier 已成功落库的结果消费待办。"""
    consumed = 0
    for todo in db.list_next_audience_todos(status="pending"):
        if todo.get("entry_kind") != ENTRY_KIND:
            continue
        did = int((todo.get("payload_json") or {}).get("dossier_id") or 0)
        origin = f"dossier:{did}"
        dossier = db.get_decree_dossier(did) or {}
        actors = {str(dossier.get("executor_id") or "").strip()}
        for participant in dossier.get("participant_roster") or []:
            if isinstance(participant, Mapping) and participant.get("tier") in {"主办", "协办"}:
                actors.add(str(participant.get("character_id") or "").strip())
        actors.discard("")
        decision = ""
        # 禁摊派骑案卷执行格；默许骑 #622/#649 实况；查办骑人物处置。
        if any(isinstance(x, Mapping) and not x.get("rejected")
               and int(x.get("dossier_id") or 0) == did and x.get("outcome") == "failed"
               for x in applied.get("dossier_executions") or []):
            decision = "禁摊派"
        if any(isinstance(x, Mapping) and not x.get("rejected")
               and x.get("origin_ref") == origin
               for key in ("economy_moves", "fiscal_changes", "population_transfers")
               for x in applied.get(key) or []):
            decision = "默许"
        person_changes = list(applied.get("applied_person_changes") or [])
        person_changes += list((applied.get("issue_summary") or {}).get("applied_person_changes") or [])
        if any(isinstance(x, Mapping) and not x.get("rejected")
               and x.get("动作") in {"处置", "罢黜"} and str(x.get("name") or "") in actors
               for x in person_changes):
            decision = "查办"
        if decision:
            db.mark_next_audience_todo_status(
                int(todo["id"]), "consumed",
                payload_patch={"decision": decision, "decided_turn": int(state.turn)}, commit=False,
            )
            consumed += 1
    return consumed


def write_exposure_todos(
    db: Any, state: Any, applied: Mapping[str, object] | None = None,
) -> int:
    """由稽核、检举、已成功落库的 #649 民变实况三路写同一待办。"""
    transfers = [
        item for item in (applied or {}).get("population_transfers") or []
        if isinstance(item, Mapping) and not item.get("rejected")
    ]
    written = 0
    for row in db.conn.execute("SELECT id FROM decree_dossiers ORDER BY id").fetchall():
        did = int(row["id"])
        fork = db.read_dossier_fork_state(did)
        if not fork["fork"]:
            continue
        channels: List[str] = []
        if db.conn.execute(
            "SELECT 1 FROM decree_dossier_links WHERE target_dossier_id=? AND relation_type='稽核' LIMIT 1",
            (did,),
        ).fetchone() is not None:
            channels.append("稽核")
        if db.conn.execute(
            "SELECT 1 FROM faction_denunciations WHERE target_dossier_id=? LIMIT 1", (did,)
        ).fetchone() is not None:
            channels.append("检举")
        origin = f"dossier:{did}"
        if any(
            isinstance(item, Mapping)
            and item.get("origin_ref") == origin
            and item.get("reason") in {"摊派", "灾害", "兵灾"}
            for item in transfers
        ):
            channels.append("民变自长")
        if not channels:
            continue
        issue_id = _issue_for_dossier(db, did)
        if issue_id <= 0:
            continue
        created = db.insert_next_audience_todo(
            commitment_ref=issue_id, stage_idx=did, due_turn=int(state.turn),
            criterion_text="暗渠摊派揭破待裁", origin_context="案卷实况与奏报有异",
            entry_kind=ENTRY_KIND, created_turn=int(state.turn),
            payload_json={"dossier_id": did, "channels": channels, "fork": fork}, commit=False,
        )
        written += int(bool(created))
    return written
