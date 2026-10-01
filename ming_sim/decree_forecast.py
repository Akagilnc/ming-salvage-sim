"""Nightly, per-decree forecast staging (#1861).

The work stays inside the existing session ticket queue and C0 staged-declaration
store. Forecasts never write a dossier, ledger entry, or player-facing material.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, Optional

from ming_sim import agents, audience_translation, decree
from ming_sim.audience_translate import build_translation_target_grounding
from ming_sim.db import payload_declares_escort
from ming_sim.declaration_dispatch import (
    held_dossier_decree_ref,
    pending_action_decree_ref,
    stage_declaration,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_transport import audience_transport_policy
from ming_sim.materials import (
    prepare_world_materials,
    release_material_tree,
    world_materials_root,
)
from ming_sim.month_translate import (
    _effect_ref_grounding,
    _visible_effect_refs,
    translate_month_segment,
)
from ming_sim.session_write_queue import get_session_write_queue

logger = logging.getLogger(__name__)
_owners_guard = threading.Lock()
_owners: Dict[int, "weakref.ReferenceType[Any]"] = {}


def bind_forecast_owner(owner: Any) -> None:
    """召对会话登记自己，使应允落账后能找回写队列与模型配置。"""
    db = getattr(owner, "db", None)
    if db is None:
        return
    with _owners_guard:
        _owners[id(db)] = weakref.ref(owner)


def _owner_for(db: Any) -> Any:
    with _owners_guard:
        ref = _owners.get(id(db))
    return None if ref is None else ref()


def _call_exhausted(exc: BaseException) -> bool:
    """夜里预算用尽：typed 不可用，或提供方 HTTP 429。不读错误散文。"""
    if isinstance(exc, LLMUnavailable):
        return True
    status = getattr(exc, "status_code", None)
    try:
        return int(status) == 429
    except (TypeError, ValueError):
        return False


def _payload_dict(candidate: Dict[str, Any]) -> Dict[str, Any]:
    payload = candidate.get("payload")
    if isinstance(payload, dict):
        return payload
    raw = candidate.get("payload_json")
    if raw in (None, ""):
        return {}
    loaded = json.loads(str(raw))
    return loaded if isinstance(loaded, dict) else {}


def _this_decree_fact(
    candidate: Dict[str, Any], *, decree_text: str, db: Any = None,
) -> Dict[str, object]:
    """本旨事实：随调用消息携带，不进材料目录（ADR 0155）。

    字段形状沿 continuing_dossier_facts，另附完整载荷与 mode；status 固定按已颁看待。
    已有案卷的 paid 从账本实付投影（materials.dossier_paid_amount）；
    夜里尚未成案的拟旨 id 无动账，投影为 0。
    """
    from ming_sim.materials import dossier_paid_amount

    payload = _payload_dict(candidate)
    paid = dossier_paid_amount(db, candidate.get("id")) if db is not None else 0
    return {
        "id": candidate.get("id"),
        "status": "promulgated",
        "decree_text": decree_text,
        "action_type": str(candidate.get("action_type") or ""),
        "target_kind": str(candidate.get("target_kind") or ""),
        "target_id": str(candidate.get("target_id") or ""),
        "grant_action": str(payload.get("grant_action") or ""),
        "payload": payload,
        "mode": str(candidate.get("mode") or payload.get("mode") or "ordinary"),
        "paid": paid,
    }


def release_forecast_materials(snapshot: Optional[Dict[str, Any]]) -> None:
    """释放快照持有的材料目录；可重复调用。"""
    if not snapshot:
        return
    prepared = snapshot.pop("prepared", None)
    if prepared is None:
        return
    release_material_tree(getattr(prepared, "root", None))


def forecast_snapshot(
    session: Any,
    candidate: Dict[str, Any],
    *,
    decree_ref: str,
    decree_text: Optional[str] = None,
) -> Dict[str, Any]:
    """预推唯一快照：引用、判官上下文、材料目录、本旨事实与可见效果引用。

    夜里预推、留中回流、过月补跑、批红续推四处只构造候选后调用本函数。
    「按已颁看待」只有这一种写法。每次预推独立材料目录，调用方负责释放。
    """
    db, state = session.db, session.state
    body = copy.deepcopy(candidate)
    payload = _payload_dict(body)
    # 同夜暗护：密令已成案、这道拨银还是暂存。预推副本带上指向本暂存的护行，
    # 不把拨银提前成案，也不写回暂存载荷。
    pending_action_id = body.get("pending_action_id")
    covert_sources: list = []
    if pending_action_id and hasattr(db, "list_covert_escorts_aimed_at_pending"):
        covert_sources = db.list_covert_escorts_aimed_at_pending(int(pending_action_id))
        if covert_sources:
            payload = dict(payload)
            payload["escort_sources"] = list(covert_sources)
    body["payload"] = payload
    text = (
        str(decree_text)
        if decree_text is not None
        else str(body.get("decree_text") or "")
    )
    body["decree_text"] = text
    body["decree_ref"] = decree_ref
    turn = int(state.turn)
    # 判官上下文用原始候选；推演侧本旨事实按已颁看待。
    context = decree.build_promulgation_judge_context(db, state, [body])
    # 与世界段同一读法；独立 dest_root，避免并行预推互踩固定「世界推演」根。
    dest_parent = Path(world_materials_root(db, state)).parent / "decree-forecast"
    prepared = prepare_world_materials(db, state, dest_root=dest_parent)
    try:
        grounding, refs = _frozen_effect_refs(db, turn, payload)
        # 夜里拨银还没有案卷。目录与本旨身份用这道暂存自己的 decree_ref，
        # 不用 MAX(id)+1 猜号——两道同夜预推会猜到同一个未来号，落账时串路。
        # 猜号只留在判官候选的整数 id 上（批红契约要正整数），不进护送目录。
        catalog_token = _uncased_grant_catalog_token(db, body, decree_ref)
        if catalog_token and (covert_sources or payload_declares_escort(payload)):
            grounding = _append_this_decree_escort_grounding(
                grounding, body, covert_sources, catalog_token,
            )
        this_decree = _this_decree_fact(body, decree_text=text, db=db)
        if catalog_token:
            this_decree = dict(this_decree)
            this_decree["id"] = catalog_token
    except BaseException:
        release_material_tree(prepared.root)
        raise
    return {
        "candidate": body,
        "context": context,
        "prepared": prepared,
        "this_decree": this_decree,
        "target_grounding": grounding,
        "visible_refs": refs,
        "decree_ref": decree_ref,
        "turn": turn,
    }


def _pending_snapshot(session: Any, pending_action_id: int, night_id: int) -> Optional[Dict[str, Any]]:
    db, state = session.db, session.state
    row = db.conn.execute(
        "SELECT * FROM pending_actions WHERE id=?", (int(pending_action_id),),
    ).fetchone()
    if row is None:
        return None
    pending = dict(row)
    if (
        pending.get("kind") != "directive"
        or pending.get("action") != "拟旨"
        or pending.get("status") != "pending"
        or int(pending.get("night_approved") or 0) != 1
        or int(pending.get("night_id") or 0) != int(night_id)
    ):
        return None
    version = int(pending.get("version") or 0)
    decree_ref = pending_action_decree_ref(int(pending_action_id), version)
    prepared_directive = db._prepare_pending_directive(
        state, pending, content=getattr(session, "content", None),
    )
    if prepared_directive.get("classification") != "valid":
        return None
    payload = dict(prepared_directive["payload"])
    action_type = db._directive_dossier_action_type(payload)
    executor_kind, executor_id = db._directive_executor(action_type, payload)
    next_id = int(db.conn.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM decree_dossiers"
    ).fetchone()[0])
    candidate: Dict[str, object] = {
        "id": next_id,
        "pending_action_id": int(pending_action_id),
        "action_type": action_type,
        "decree_text": str(prepared_directive["text"]),
        "target_kind": str(payload.get("target_kind") or ""),
        "target_id": payload.get("target_id", pending.get("target_id")),
        "executor_kind": str(executor_kind or ""),
        "executor_id": str(executor_id or ""),
        "mode": str(payload.get("mode") or "ordinary"),
        "payload": payload,
        "status": "proposed",
        "settlement_verdict": "",
        "promulgation_decision": "",
        "rescript_pending": False,
        "due_turn": int(payload.get("due_turn") or state.turn),
        "created_turn": int(pending.get("turn") or state.turn),
        "promulgated_turn": 0,
        "held_turn": 0,
        "stigma": [],
        "participant_roster": list(payload.get("participant_roster") or []),
        "links": [],
        "execution_signal": payload.get("execution_signal"),
        "execution_note": "",
        "execution_outcome": "",
    }
    snapshot = forecast_snapshot(
        session, candidate, decree_ref=decree_ref,
        decree_text=str(prepared_directive["text"]),
    )
    snapshot["pending_action_id"] = int(pending_action_id)
    snapshot["version"] = version
    snapshot["night_id"] = int(night_id)
    return snapshot


def _held_snapshot(session: Any, dossier_id: int) -> Optional[Dict[str, Any]]:
    db, state = session.db, session.state
    row = db.get_decree_dossier(int(dossier_id))
    if row is None or not _is_held_for_rejudgment(row, int(state.turn)):
        return None
    candidate = copy.deepcopy(row)
    snapshot = forecast_snapshot(
        session, candidate,
        decree_ref=decree_ref_for_dossier(db, candidate),
    )
    snapshot["dossier_id"] = int(dossier_id)
    return snapshot


def _uncased_grant_catalog_token(
    db: Any, candidate: Dict[str, Any], decree_ref: str,
) -> Optional[str]:
    """尚未成案的拨银用自己的暂存标识当目录行；已经有案卷则不再补行。"""
    if str(candidate.get("action_type") or "") != "grant_allocation":
        return None
    token = str(decree_ref or "")
    if not token:
        return None
    try:
        pending_id = int(candidate.get("pending_action_id"))
    except (TypeError, ValueError):
        return None
    if pending_id <= 0 or not hasattr(db, "conn"):
        return None
    existing = db.conn.execute(
        "SELECT id FROM decree_dossiers "
        "WHERE action_type='grant_allocation' AND pending_action_id=? LIMIT 1",
        (pending_id,),
    ).fetchone()
    if existing is not None:
        return None
    return token


def _append_this_decree_escort_grounding(
    grounding: str, candidate: Dict[str, Any], sources: list, token: str,
) -> str:
    """本旨尚未成案，全局目录没有它的行。目录身份是暂存 decree_ref，不是猜号。"""
    kind = str(candidate.get("target_kind") or "")
    target_id = str(candidate.get("target_id") or "")
    payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
    declared = payload_declares_escort(payload)
    lines = [
        f"dossier\t{token}\t{kind}:{target_id}\t本旨"
        + ("\t自带押解" if declared else ""),
    ]
    for source in sources:
        lines.append(
            f"escort_link\t{int(source['secret_order_dossier_id'])}\t{token}"
            f"\t{source['relation_type']}"
        )
    body = grounding.rstrip("\n")
    extra = "\n".join(lines)
    if not body:
        return extra + "\n"
    return body + "\n" + extra + "\n"


def _frozen_effect_refs(
    db: Any, turn: int, payload: Dict[str, Any],
) -> tuple[str, dict]:
    """#1840：转译输入与暂存落账共用这一份可见引用，不另建账。"""
    refs = _visible_effect_refs(db, turn, payload)
    return build_translation_target_grounding(db) + _effect_ref_grounding(refs), refs


def _is_held_for_rejudgment(row: Dict[str, Any], turn: int) -> bool:
    return (
        str(row.get("status") or "") == "proposed"
        and str(row.get("promulgation_decision") or "") == "rejected"
        and not bool(row.get("rescript_pending"))
        and int(row.get("held_turn") or 0) > 0
        and int(turn) > int(row.get("held_turn") or 0)
    )


def decree_ref_for_dossier(db: Any, dossier: Dict[str, Any]) -> str:
    """过月与夜里预推共用身份；留中案卷以案卷身份持久绑定，与原旨暂存隔离。"""
    if int(dossier.get("held_turn") or 0) > 0:
        return held_dossier_decree_ref(int(dossier["id"]))
    pending_id = int(dossier.get("pending_action_id") or 0)
    if pending_id > 0:
        row = db.conn.execute(
            "SELECT version FROM pending_actions WHERE id=?",
            (pending_id,),
        ).fetchone()
        version = int(row["version"] or 1) if row is not None else 1
        return pending_action_decree_ref(pending_id, version)
    return held_dossier_decree_ref(int(dossier["id"]))


def snapshot_for_existing_dossier(session: Any, dossier: Dict[str, Any]) -> Dict[str, Any]:
    """过月补跑用当前案卷与当前盘面组一份预推快照，不另建判官或推演入口。"""
    return forecast_snapshot(
        session, dict(dossier),
        decree_ref=decree_ref_for_dossier(session.db, dossier),
    )


def produce_forecast_product(session: Any, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """判官、逐旨推演、过月段转译三步。只产出暂存物，不落账。"""
    try:
        candidate = snapshot["candidate"]
        payload = _payload_dict(candidate)
        if decree.dossier_action_policy(
            candidate.get("action_type"), payload,
        )["external_review"]:
            raw = decree.llm_promulgation_verdicts(
                [candidate], session.state, db=session.db,
                agno_db=getattr(session, "agno_db", None),
                llm_config=session.llm_config,
                prepared_context=snapshot["context"],
                transport_policy=audience_transport_policy(),
            )
        else:
            raw = decree.stub_promulgation_verdicts([candidate], session.state)
        verdicts = decree.validate_promulgation_verdicts(
            raw, [candidate], session.db, prepared_context=snapshot["context"],
        )
        verdict = dict(verdicts[0])
        declaration: Dict[str, object] = {}
        questions = None
        forecast_text = None
        if str(verdict.get("decision") or "") == "promulgated":
            agent = agents.create_decree_forecast_agent(
                session.llm_config, snapshot["prepared"],
            )
            narrative = agents.run_agent_text(
                agent,
                json.dumps({
                    "instruction": "推演这一道旨在当前盘面上的可能后果。",
                    "this_decree": snapshot["this_decree"],
                }, ensure_ascii=False),
                tag="decree-forecast",
                transport_policy=audience_transport_policy(),
            )
            from ming_sim.month_chain import _split_at_question

            # 与世界段同一解析：问前段文只转译一次，同段合法请旨全部暂存。
            prefix, questions = _split_at_question(str(narrative or ""))
            forecast_text = prefix
            if prefix.strip():
                declaration = translate_month_segment(
                    segment=prefix,
                    target_grounding=str(snapshot["target_grounding"]),
                    decree_payload=payload,
                    llm_config=session.llm_config,
                )
        return {
            "verdict": verdict,
            "declaration": declaration,
            "questions": questions,
            "forecast_text": forecast_text,
        }
    finally:
        release_forecast_materials(snapshot)


def _forecast(
    session: Any, snapshot: Dict[str, Any], *, write_lock: Optional[threading.Lock] = None,
) -> None:
    # 同一 decree_ref（记录号+版本，或留中案卷 id）已有暂存则不再跑模型链。
    try:
        if session.db.staged_declarations.staged_for(str(snapshot["decree_ref"])):
            return
        product = produce_forecast_product(session, snapshot)
        verdict = product["verdict"]
        declaration = product["declaration"]
        questions = product["questions"]
        forecast_text = product["forecast_text"]

        def stage_if_current() -> None:
            if "pending_action_id" in snapshot:
                row = session.db.conn.execute(
                    "SELECT status,kind,action,night_approved,night_id,version "
                    "FROM pending_actions WHERE id=?",
                    (snapshot["pending_action_id"],),
                ).fetchone()
                if row is None or (
                    row["status"] != "pending"
                    or row["kind"] != "directive"
                    or row["action"] != "拟旨"
                    or int(row["night_approved"] or 0) != 1
                    or int(row["night_id"] or 0) != snapshot["night_id"]
                    or int(row["version"] or 0) != snapshot["version"]
                ):
                    return
            else:
                current = session.db.get_decree_dossier(snapshot["dossier_id"])
                if current is None or not _is_held_for_rejudgment(current, int(session.state.turn)):
                    return
            if session.db.staged_declarations.staged_for(str(snapshot["decree_ref"])):
                return
            stage_declaration(
                session.db,
                decree_ref=str(snapshot["decree_ref"]),
                declaration=declaration,
                turn=int(snapshot["turn"]),
                verdict=verdict,
                questions=questions,
                forecast_text=forecast_text,
                visible_refs=snapshot.get("visible_refs"),
            )

        def stage() -> None:
            get_session_write_queue(session).run(snapshot["ticket"], stage_if_current)

        if write_lock is None:
            stage()
        else:
            # One night-start ticket orders the month barrier. Parallel legs must
            # not enter that ticket's write turn together.
            with write_lock:
                stage()
    finally:
        # produce 已释放则 no-op；早退未 produce 时在此释放。
        release_forecast_materials(snapshot)


def _submit_snapshot_job(
    session: Any,
    *,
    snapshot_fn: Any,
    ticket: Any,
    write_lock: Optional[threading.Lock] = None,
) -> bool:
    """Run one already-claimed forecast ticket on the audience executor."""
    queue = get_session_write_queue(session)

    def run() -> None:
        snapshot: Optional[Dict[str, Any]] = None
        try:
            if write_lock is None:
                snapshot = queue.run(ticket, snapshot_fn)
            else:
                with write_lock:
                    snapshot = queue.run(ticket, snapshot_fn)
            if snapshot is None:
                return
            snapshot["ticket"] = ticket
            try:
                _forecast(session, snapshot, write_lock=write_lock)
            except Exception as exc:
                if _call_exhausted(exc):
                    return
                raise
        finally:
            release_forecast_materials(snapshot)
            queue.complete(ticket)

    try:
        future = audience_translation._executor.submit(run)
    except BaseException:
        queue.complete(ticket)
        raise
    future.add_done_callback(
        lambda done: audience_translation._observe_finished_future(
            done, where="decree forecast", key=getattr(ticket, "key", None),
        )
    )
    return True


def _forecast_configured(session: Any) -> bool:
    cfg = getattr(session, "llm_config", None)
    return cfg is not None and hasattr(cfg, "advanced_model") and hasattr(cfg, "model")


def schedule_pending_decree_forecast(
    session: Any, pending_action_id: int, *, night_id: int,
) -> bool:
    if not _forecast_configured(session):
        return False
    action_id = int(pending_action_id)
    nid = int(night_id)
    row = session.db.conn.execute(
        "SELECT version, status, kind, action, night_approved, night_id "
        "FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    if row is None or (
        row["status"] != "pending"
        or row["kind"] != "directive"
        or row["action"] != "拟旨"
        or int(row["night_approved"] or 0) != 1
        or int(row["night_id"] or 0) != nid
    ):
        return False
    version = int(row["version"] or 1)
    if session.db.staged_declarations.staged_for(
        pending_action_decree_ref(action_id, version),
    ):
        return False
    queue = get_session_write_queue(session)
    ticket = queue.claim_if_absent(
        [("decree_forecast", action_id, version, nid)],
    )[0]
    if ticket is None:
        return False
    return _submit_snapshot_job(
        session,
        snapshot_fn=lambda: _pending_snapshot(session, action_id, nid),
        ticket=ticket,
    )


def schedule_restored_decree_forecasts(owner_or_db: Any, pending_action_ids: list[int]) -> None:
    """Requeue forecasts for approved directives restored by chat rollback."""
    if not pending_action_ids:
        return
    session = owner_or_db if hasattr(owner_or_db, "db") else _owner_for(owner_or_db)
    if session is None:
        return
    db = session.db
    bind_forecast_owner(session)
    for action_id in pending_action_ids:
        row = db.conn.execute(
            "SELECT night_id FROM pending_actions WHERE id=?", (int(action_id),),
        ).fetchone()
        if row is not None and int(row["night_id"] or 0) > 0:
            schedule_pending_decree_forecast(
                session, int(action_id), night_id=int(row["night_id"]),
            )


def schedule_approved_from_dispatch(db: Any, result: Any, night_id: int) -> None:
    """应允落账后为拟旨起预推。无登记会话则不动（测试直调分派不烧模型）。"""
    owner = _owner_for(db)
    if owner is None:
        return
    promises = getattr(result, "promises", None)
    applied = getattr(promises, "applied", None) or []
    for item in applied:
        if not isinstance(item, dict):
            continue
        if str(item.get("decision") or "") != "应允":
            continue
        if str(item.get("kind") or "") != "directive":
            continue
        if str(item.get("action") or "") != "拟旨":
            continue
        try:
            action_id = int(item.get("action_id") or 0)
        except (TypeError, ValueError):
            continue
        if action_id > 0:
            schedule_pending_decree_forecast(owner, action_id, night_id=int(night_id))


def schedule_held_decree_forecasts(session: Any) -> bool:
    """At a newly opened night, rejudge and forecast held historical proposals.

    The scan ticket is claimed before return so a later month barrier waits for
    every retained leg. Each dossier then uses the existing per-decree submit;
    model calls overlap, write turns on the shared ticket do not.
    """
    from ming_sim.audience_night import get_open_night

    if not _forecast_configured(session):
        return False
    night = get_open_night(session.db)
    if night is None:
        return False
    night_id = int(night["id"])
    queue = get_session_write_queue(session)
    ticket = queue.claim_if_absent([("held_decree_forecast_scan", night_id)])[0]
    if ticket is None:
        return False

    def scan_and_fanout() -> None:
        # Caller may still hold the session write gate (night-open prologue).
        # Snapshot on this worker, after that turn ends — never on the caller.
        try:
            turn = int(session.state.turn)

            def snapshot_held_ids() -> list[int]:
                rows = session.db.list_decree_dossiers_for_simulation(turn)
                return [
                    int(row["id"]) for row in rows
                    if _is_held_for_rejudgment(row, turn)
                ]

            ids = queue.run(ticket, snapshot_held_ids)
            if not ids:
                return
            write_lock = threading.Lock()
            for dossier_id in ids:
                retained = queue.retain(
                    ticket, ("held_decree_forecast", night_id, int(dossier_id)),
                )
                _submit_snapshot_job(
                    session,
                    snapshot_fn=lambda dossier_id=dossier_id: _held_snapshot(
                        session, dossier_id,
                    ),
                    ticket=retained,
                    write_lock=write_lock,
                )
        finally:
            queue.complete(ticket)

    try:
        future = audience_translation._executor.submit(scan_and_fanout)
    except BaseException:
        queue.complete(ticket)
        raise
    future.add_done_callback(
        lambda done: audience_translation._observe_finished_future(
            done, where="held decree forecast scan", night_id=night_id,
        )
    )
    return True
