"""#651 暗渠摊派事实投影。

不定义 extractor 包装、判决或第二状态机：判官复用案卷输入，实况复用 #622/#649，
揭破只进入 next_audience_todos 的唯一 dispatcher。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

ENTRY_KIND = "covert_levy_exposure"
PROHIBITION_ACTION = "prohibit_covert_levy"


def active_prohibition_dossier(db: Any, exposed_dossier_id: int) -> Dict[str, object] | None:
    """Return the first canonical dossier which authorizes this prohibition."""
    rows = db.conn.execute(
        """SELECT * FROM decree_dossiers
           WHERE action_type=? AND target_kind='dossier' AND target_id=?
             AND status IN ('promulgated','closed')
           ORDER BY id""",
        (PROHIBITION_ACTION, str(int(exposed_dossier_id))),
    ).fetchall()
    for row in rows:
        item = dict(row)
        if db.dossier_authorizes_effects(int(item["id"])):
            return item
    return None


def canonical_fiscal_result(
    db: Any, source: Mapping[str, object], *, applied: bool,
    effective_origin_ref: object | None = None, **result: object,
) -> Dict[str, object]:
    """Build the shared receipt identity for every canonical fiscal applier."""
    from ming_sim.simulation import read_beyond_intent_raw

    origin = source.get("origin_ref") if effective_origin_ref is None else effective_origin_ref
    result["origin_ref"] = str(origin or "").strip()
    result["beyond_intent"] = bool(
        db.coerce_beyond_intent_flag(read_beyond_intent_raw(source))
    )
    result["applied"] = bool(applied)
    return result


def stopped_covert_effect(
    db: Any, *, origin_ref: object, beyond_intent: object = False,
) -> bool:
    """True only for a post-prohibition covert leg owned by the targeted old dossier."""
    origin = str(origin_ref or "").strip()
    if not origin.startswith("dossier:"):
        return False
    raw_id = origin.removeprefix("dossier:")
    if not raw_id.isdigit():
        return False
    from ming_sim.simulation import read_beyond_intent_raw
    beyond = db.coerce_beyond_intent_flag(read_beyond_intent_raw({"beyond_intent": beyond_intent}))
    if not beyond:
        return False
    return active_prohibition_dossier(db, int(raw_id)) is not None


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


def settle_exposure_from_canonical_actions(db: Any, state: Any, applied: Mapping[str, object]) -> int:
    """只凭 canonical applier 已成功落库的结果消费待办。"""
    consumed = 0
    for todo in db.list_next_audience_todos(status="pending"):
        if todo.get("entry_kind") != ENTRY_KIND:
            continue
        payload = todo.get("payload_json") or {}
        did = int(payload.get("dossier_id") or 0)
        # The same row remains the durable reminder only while the real gap exists.
        if payload.get("decision") == "禁摊派":
            pay_fact = army_pay_fact_for_dossier(db, did) or {}
            if float(pay_fact.get("arrears") or 0) <= 0:
                db.mark_next_audience_todo_status(int(todo["id"]), "consumed", commit=False)
                consumed += 1
            continue
        if payload.get("decision"):
            continue
        origin = f"dossier:{did}"
        dossier = db.get_decree_dossier(did) or {}
        actors = {str(dossier.get("executor_id") or "").strip()}
        for participant in dossier.get("participant_roster") or []:
            if isinstance(participant, Mapping) and participant.get("tier") in {"主办", "协办"}:
                actors.add(str(participant.get("character_id") or "").strip())
        actors.discard("")
        successful = lambda x: isinstance(x, Mapping) and not x.get("rejected")
        # Identity is the successfully promulgated case-bound dossier, never an
        # unrelated fiscal receipt with a convenient shape.
        pay_fact = army_pay_fact_for_dossier(db, did) or {}
        prohibition = active_prohibition_dossier(db, did)
        stopped = prohibition is not None
        if prohibition is not None:
            # The canonical prohibition owns the durable, idempotent rollback receipt.
            from ming_sim.issues import neutralize_covert_fiscal_effects
            neutralize_covert_fiscal_effects(
                db, state, exposed_dossier_id=did,
                prohibition_dossier_id=int(prohibition["id"]),
            )
        levy_transfer = any(
            successful(x) and x.get("origin_ref") == origin and x.get("reason") == "摊派"
            for x in applied.get("population_transfers") or []
        )
        covert_effect = any(
            successful(x) and x.get("applied") is True
            and x.get("origin_ref") == origin and x.get("beyond_intent") is True
            for key in ("economy_moves", "fiscal_changes", "fiscal_creates", "fiscal_removes")
            for x in applied.get(key) or []
        )
        person_changes = list(applied.get("applied_person_changes") or [])
        person_changes += list((applied.get("issue_summary") or {}).get("applied_person_changes") or [])
        punished = any(
            successful(x) and x.get("动作") in {"处置", "罢黜"}
            and str(x.get("name") or "") in actors for x in person_changes
        )
        paid_cost = any(
            successful(x)
            and str(x.get("origin") or "").startswith(f"{origin}:relation:")
            and ({str(x.get("source") or ""), str(x.get("target") or "")} & actors)
            for x in applied.get("relation_edge_event_resolutions") or []
        )
        decisions = [
            name for name, matched in (
                ("禁摊派", stopped), ("默许", levy_transfer and covert_effect),
                ("查办", punished and paid_cost),
            ) if matched
        ]
        if len(decisions) != 1:
            continue
        decision = decisions[0]
        # 禁令的真实后果是欠饷缺口继续顶在御前，故保留同一 pending 行而非造第二 dispatcher。
        reopened = (
            decision == "禁摊派" and float(pay_fact.get("arrears") or 0) > 0
        )
        status = "pending" if reopened else "consumed"
        db.mark_next_audience_todo_status(
            int(todo["id"]), status,
            payload_patch={"decision": decision, "decided_turn": int(state.turn),
                           "shortfall_reopened": reopened}, commit=False,
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
        # #651's covert channel is narrower than the shared #622/#627 fork:
        # report, transformed execution, and a canonical beyond-intent effect
        # must all exist.  Keep this conjunction at the consumer seam.
        if not (
            fork["fork"]
            and str(fork.get("execution_outcome") or "") == "transformed"
            and bool(fork.get("beyond_intent"))
            and int(fork.get("actual_effect_count") or 0) > 0
        ):
            continue
        channels: List[str] = []
        if db.conn.execute(
            "SELECT 1 FROM decree_dossier_links WHERE target_dossier_id=? AND relation_type='稽核' LIMIT 1",
            (did,),
        ).fetchone() is not None:
            channels.append("稽核")
        from ming_sim.supervision import ORIGIN_MARK_DENUNCIATION_TRUE, origin_has_mark
        denunciations = db.conn.execute(
            "SELECT origin FROM faction_denunciations WHERE target_dossier_id=?", (did,)
        ).fetchall()
        if any(origin_has_mark(row["origin"], ORIGIN_MARK_DENUNCIATION_TRUE) for row in denunciations):
            channels.append("检举")
        origin = f"dossier:{did}"
        if any(
            isinstance(item, Mapping)
            and item.get("origin_ref") == origin
            and item.get("reason") == "摊派"
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
