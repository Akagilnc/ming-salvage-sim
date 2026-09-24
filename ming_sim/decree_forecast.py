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
from typing import Any, Dict, Optional

from ming_sim import agents, audience_translation, decree, simulation
from ming_sim.audience_translate import build_translation_target_grounding
from ming_sim.declaration_dispatch import (
    held_dossier_decree_ref,
    pending_action_decree_ref,
    stage_declaration,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_transport import audience_transport_policy
from ming_sim.month_translate import translate_month_segment
from ming_sim.session_write_queue import get_session_write_queue

logger = logging.getLogger(__name__)
_owners_guard = threading.Lock()
_owners: Dict[int, "weakref.ReferenceType[Any]"] = {}
_inflight_guard = threading.Lock()
_inflight: set[tuple] = set()


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


def _claim_inflight(key: tuple) -> bool:
    with _inflight_guard:
        if key in _inflight:
            return False
        _inflight.add(key)
        return True


def _release_inflight(key: tuple) -> None:
    with _inflight_guard:
        _inflight.discard(key)


def _call_exhausted(exc: BaseException) -> bool:
    """夜里预算用尽：typed 不可用，或提供方 HTTP 429。不读错误散文。"""
    if isinstance(exc, LLMUnavailable):
        return True
    status = getattr(exc, "status_code", None)
    try:
        return int(status) == 429
    except (TypeError, ValueError):
        return False


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
    prepared = db._prepare_pending_directive(
        state, pending, content=getattr(session, "content", None),
    )
    if prepared.get("classification") != "valid":
        return None
    payload = dict(prepared["payload"])
    action_type = db._directive_dossier_action_type(payload)
    executor_kind, executor_id = db._directive_executor(action_type, payload)
    next_id = int(db.conn.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM decree_dossiers"
    ).fetchone()[0])
    candidate: Dict[str, object] = {
        "id": next_id,
        "pending_action_id": int(pending_action_id),
        "action_type": action_type,
        "decree_text": str(prepared["text"]),
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
    context = decree.build_promulgation_judge_context(db, state, [candidate])
    visible = copy.deepcopy(candidate)
    visible["settlement_verdict"] = "promulgated"
    visible["promulgation_decision"] = "promulgated"
    visible["promulgated_turn"] = int(state.turn)
    projected = decree.project_dossiers_for_simulator([visible], db, state)
    sim_payload = simulation.build_simulator_payload(
        state, db, str(prepared["text"]), "", decree_dossiers=projected,
    )
    # Nightly forecasting is limited to this decree, not a second world-event run.
    sim_payload["candidate_events"] = []
    return {
        "candidate": candidate,
        "context": context,
        "simulator_payload": sim_payload,
        "target_grounding": build_translation_target_grounding(db),
        "decree_ref": decree_ref,
        "pending_action_id": int(pending_action_id),
        "version": version,
        "night_id": int(night_id),
        "turn": int(state.turn),
    }


def _held_snapshot(session: Any, dossier_id: int) -> Optional[Dict[str, Any]]:
    db, state = session.db, session.state
    row = db.get_decree_dossier(int(dossier_id))
    if row is None or not _is_held_for_rejudgment(row, int(state.turn)):
        return None
    candidate = copy.deepcopy(row)
    context = decree.build_promulgation_judge_context(db, state, [candidate])
    visible = copy.deepcopy(candidate)
    # The verdict is prospective; make the already-existing proposal visible to
    # the simulator without materializing or persisting its outcome.
    visible["settlement_verdict"] = "promulgated"
    visible["promulgation_decision"] = "promulgated"
    projected = decree.project_dossiers_for_simulator([visible], db, state)
    sim_payload = simulation.build_simulator_payload(
        state, db, str(candidate.get("decree_text") or ""), "",
        decree_dossiers=projected,
    )
    sim_payload["candidate_events"] = []
    return {
        "candidate": candidate,
        "context": context,
        "simulator_payload": sim_payload,
        "target_grounding": build_translation_target_grounding(db),
        "decree_ref": held_dossier_decree_ref(int(dossier_id)),
        "dossier_id": int(dossier_id),
        "turn": int(state.turn),
    }


def _is_held_for_rejudgment(row: Dict[str, Any], turn: int) -> bool:
    return (
        str(row.get("status") or "") == "proposed"
        and str(row.get("promulgation_decision") or "") == "rejected"
        and not bool(row.get("rescript_pending"))
        and int(row.get("held_turn") or 0) > 0
        and int(turn) > int(row.get("held_turn") or 0)
    )


def _forecast(session: Any, snapshot: Dict[str, Any]) -> None:
    candidate = snapshot["candidate"]
    payload = candidate.get("payload")
    if not isinstance(payload, dict):
        payload = json.loads(str(candidate.get("payload_json") or "{}"))
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
        candidate["settlement_verdict"] = "promulgated"
        candidate["promulgation_decision"] = "promulgated"
        candidate["promulgated_turn"] = int(snapshot["turn"])
        agent = agents.create_decree_forecast_agent(
            session.llm_config, snapshot["simulator_payload"],
        )
        narrative = agents.run_agent_text(
            agent,
            json.dumps({"instruction": "推演这一道旨在当前盘面上的可能后果。"}, ensure_ascii=False),
            tag="decree-forecast",
            transport_policy=audience_transport_policy(),
        )
        prefix = str(narrative or "")
        questions = []
        for match in decree._DECISION_RE.finditer(prefix):
            parsed = decree.parse_decision_blocks(match.group(0))[1]
            if parsed:
                questions = parsed
                prefix = prefix[:match.start()]
                break
        forecast_text = prefix
        if prefix.strip():
            declaration = translate_month_segment(
                segment=prefix,
                target_grounding=str(snapshot["target_grounding"]),
                decree_payload=payload,
                llm_config=session.llm_config,
            )

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
        )

    get_session_write_queue(session).run(snapshot["ticket"], stage_if_current)


def _submit_snapshot_job(
    session: Any, *, key: tuple, snapshot_fn: Any, inflight_key: tuple,
) -> bool:
    queue = get_session_write_queue(session)
    ticket = queue.claim(key=key)
    if ticket is None:
        _release_inflight(inflight_key)
        return False

    def run() -> None:
        try:
            snapshot = queue.run(ticket, snapshot_fn)
            if snapshot is None:
                return
            snapshot["ticket"] = ticket
            try:
                _forecast(session, snapshot)
            except Exception as exc:
                if _call_exhausted(exc):
                    return
                raise
        finally:
            queue.complete(ticket)
            _release_inflight(inflight_key)

    try:
        future = audience_translation._executor.submit(run)
    except BaseException:
        queue.complete(ticket)
        _release_inflight(inflight_key)
        raise
    future.add_done_callback(
        lambda done: audience_translation._observe_finished_future(
            done, where="decree forecast", key=key,
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
    inflight_key = ("pending", action_id, version, nid)
    if not _claim_inflight(inflight_key):
        return False
    return _submit_snapshot_job(
        session,
        key=("decree_forecast", action_id, version, nid),
        snapshot_fn=lambda: _pending_snapshot(session, action_id, nid),
        inflight_key=inflight_key,
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
    """At a newly opened night, rejudge and forecast held historical proposals."""
    from ming_sim.audience_night import get_open_night

    if not _forecast_configured(session):
        return False
    night = get_open_night(session.db)
    if night is None:
        return False
    night_id = int(night["id"])
    inflight_key = ("held-scan", night_id)
    if not _claim_inflight(inflight_key):
        return False

    def snapshot_held_ids() -> list[int]:
        rows = session.db.list_decree_dossiers_for_simulation(int(session.state.turn))
        return [
            int(row["id"]) for row in rows
            if _is_held_for_rejudgment(row, int(session.state.turn))
        ]

    def scan_and_forecast() -> None:
        queue = get_session_write_queue(session)
        try:
            ids = queue.run(scan_ticket, snapshot_held_ids)
            for dossier_id in ids:
                snapshot = queue.run(
                    scan_ticket,
                    lambda dossier_id=dossier_id: _held_snapshot(session, dossier_id),
                )
                if snapshot is None:
                    continue
                snapshot["ticket"] = scan_ticket
                try:
                    _forecast(session, snapshot)
                except Exception as exc:
                    if _call_exhausted(exc):
                        continue
                    raise
        finally:
            queue.complete(ticket)
            _release_inflight(inflight_key)

    queue = get_session_write_queue(session)
    ticket = queue.claim(key=("held_decree_forecast_scan", night_id))
    if ticket is None:
        _release_inflight(inflight_key)
        return False
    scan_ticket = ticket
    try:
        future = audience_translation._executor.submit(scan_and_forecast)
    except BaseException:
        queue.complete(scan_ticket)
        _release_inflight(inflight_key)
        raise
    future.add_done_callback(
        lambda done: audience_translation._observe_finished_future(
            done, where="held decree forecast scan", night_id=night_id,
        )
    )
    return True
