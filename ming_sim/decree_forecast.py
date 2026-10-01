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
from ming_sim.declaration_dispatch import (
    held_dossier_decree_ref,
    pending_action_decree_ref,
    stage_declaration,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_transport import audience_transport_policy
from ming_sim.materials import (
    continuing_dossier_facts,
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
    return _is_provider_rate_limit(exc)


def _is_provider_rate_limit(exc: BaseException) -> bool:
    """只认提供方状态码 429。夜里 429 仍算未预成，不记失败相位。"""
    status = getattr(exc, "status_code", None)
    try:
        return int(status) == 429
    except (TypeError, ValueError):
        return False


def _progress_key(decree_ref: str) -> str:
    return f"forecast-progress:{decree_ref}"


def load_forecast_progress(db: Any, decree_ref: str) -> Dict[str, Any]:
    raw = db.kv_get(_progress_key(str(decree_ref or ""))) if decree_ref else None
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_forecast_progress(db: Any, decree_ref: str, progress: Dict[str, Any]) -> None:
    if not decree_ref:
        return
    db.kv_set(_progress_key(str(decree_ref)), json.dumps(progress, ensure_ascii=False))


def discard_forecast_progress(db: Any, decree_ref: str) -> None:
    ref = str(decree_ref or "")
    if not ref or not hasattr(db, "conn"):
        return
    db.conn.execute("DELETE FROM kv_store WHERE key=?", (_progress_key(ref),))
    if (
        not bool(getattr(db.conn, "_commit_suspended", False))
        and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0
    ):
        db.conn.commit()


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
    from ming_sim.materials import dossier_paid_amount, revoke_target_facts

    payload = _payload_dict(candidate)
    paid = dossier_paid_amount(db, candidate.get("id")) if db is not None else 0
    fact: Dict[str, object] = {
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
    # #1894：撤令连同原旨、已投入与实际办理进度一起进推演输入（ADR 0155 本旨
    # 事实走随调用消息，不进材料目录）。同一 run 内既有准行/劝回的判，也有
    # 准行后原案卷办理结果的推演——不新增调用。
    if str(candidate.get("action_type") or "") == "revoke_decree" and db is not None:
        fact["revoke_target"] = revoke_target_facts(db, payload, candidate)
    return fact


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
        this_decree = _this_decree_fact(body, decree_text=text, db=db)
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
    """判官、逐旨推演、过月段转译三步。只产出暂存物，不落账。

    已完成的子步记在既有 kv（forecast-progress:{decree_ref}）。重入跳过已成调用，
    不另建断点表，也不把半成品声明写进 staged。
    """
    decree_ref = str(snapshot.get("decree_ref") or "")
    progress = load_forecast_progress(session.db, decree_ref)
    try:
        candidate = snapshot["candidate"]
        payload = _payload_dict(candidate)
        saved_verdict = progress.get("verdict")
        if isinstance(saved_verdict, dict):
            verdict = dict(saved_verdict)
        else:
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
            progress = {**progress, "verdict": verdict}
            save_forecast_progress(session.db, decree_ref, progress)
        declaration: Dict[str, object] = {}
        questions = progress.get("questions") if progress.get("narrative_done") else None
        forecast_text = progress.get("forecast_text") if progress.get("narrative_done") else None
        if str(verdict.get("decision") or "") == "promulgated":
            if not progress.get("narrative_done"):
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
                forecast_text, questions = _split_at_question(str(narrative or ""))
                progress = {
                    **progress,
                    "narrative_done": True,
                    "forecast_text": forecast_text,
                    "questions": questions,
                }
                save_forecast_progress(session.db, decree_ref, progress)
            saved_declaration = progress.get("declaration") if "declaration" in progress else None
            if isinstance(saved_declaration, dict):
                declaration = saved_declaration
            else:
                prefix = str(forecast_text or "")
                if prefix.strip():
                    # #1894：在途案卷清单同世界段一份读口（materials.continuing_
                    # dossier_facts）——撤令的办理结果由执行格判官在本段声明
                    # dossier_executions，清单不给它就无从落原案卷的执行格。
                    declaration = translate_month_segment(
                        segment=prefix,
                        target_grounding=str(snapshot["target_grounding"]),
                        decree_payload=payload,
                        llm_config=session.llm_config,
                        continuing_dossiers=continuing_dossier_facts(
                            session.db, int(snapshot["turn"]),
                        ),
                    )
                else:
                    declaration = {}
                progress = {**progress, "declaration": declaration}
                save_forecast_progress(session.db, decree_ref, progress)
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
            note_forecast_staged(
                session.db, str(snapshot["decree_ref"]),
                pending_action_id=int(snapshot.get("pending_action_id") or 0),
            )
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
                    discard_forecast_progress(session.db, str(snapshot["decree_ref"]))
                    release_forecast_failure_if_idle(
                        session.db, _forecast_source_turn(session.db, snapshot),
                    )
                    return
            else:
                current = session.db.get_decree_dossier(snapshot["dossier_id"])
                if current is None or not _is_held_for_rejudgment(current, int(session.state.turn)):
                    return
            if session.db.staged_declarations.staged_for(str(snapshot["decree_ref"])):
                note_forecast_staged(
                    session.db, str(snapshot["decree_ref"]),
                    pending_action_id=int(snapshot.get("pending_action_id") or 0),
                )
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
            note_forecast_staged(
                session.db, str(snapshot["decree_ref"]),
                pending_action_id=int(snapshot.get("pending_action_id") or 0),
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
            try:
                if write_lock is None:
                    snapshot = queue.run(ticket, snapshot_fn)
                else:
                    with write_lock:
                        snapshot = queue.run(ticket, snapshot_fn)
            except Exception as exc:
                _persist_forecast_failure(
                    queue, ticket, session, _snapshot_for_failure(ticket), exc,
                )
                if _call_exhausted(exc):
                    return
                raise
            if snapshot is None:
                return
            snapshot["ticket"] = ticket
            try:
                _forecast(session, snapshot, write_lock=write_lock)
            except Exception as exc:
                _persist_forecast_failure(queue, ticket, session, snapshot, exc)
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


# #1853：夜里预推未成的持久失败相位。复用召对既有 post_reply 恢复行（源轮下一行一钮），
# 不新造前端重试器。相位名进 chat_turns.post_reply_recovery，与 after_reply / court_break 同列。
FORECAST_RECOVERY_PHASE = "decree_forecast"


def _forecast_source_turn(db: Any, snapshot: Optional[Dict[str, Any]]) -> int:
    """本预推的来源对话轮（拟旨暂存的 source_chat_turn_id，#1890）；无来源轮返 0。"""
    action_id = int((snapshot or {}).get("pending_action_id") or 0)
    if action_id <= 0 or not hasattr(db, "conn"):
        return 0
    row = db.conn.execute(
        "SELECT source_chat_turn_id FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    return int(row["source_chat_turn_id"] or 0) if row is not None else 0


def _snapshot_for_failure(ticket: Any) -> Dict[str, Any]:
    """快照还没准备出来时，用票据上的动作号记相位。"""
    key = getattr(ticket, "key", None)
    if isinstance(key, tuple) and len(key) >= 2 and key[0] == "decree_forecast":
        try:
            return {"pending_action_id": int(key[1])}
        except (TypeError, ValueError):
            return {"pending_action_id": 0}
    return {"pending_action_id": 0}


def _persist_forecast_failure(
    queue: Any, ticket: Any, session: Any, snapshot: Optional[Dict[str, Any]], exc: BaseException,
) -> None:
    """429 不记相位。写包失败只记日志，仍落失败标记，且不顶替原异常。"""
    if _is_provider_rate_limit(exc):
        return

    def write() -> None:
        record_forecast_failure(session, snapshot, exc)

    try:
        queue.run(ticket, write)
    except Exception:
        logger.exception("[decree-forecast] 预推失败相位记录未落")


def record_forecast_failure(
    session: Any, snapshot: Optional[Dict[str, Any]], exc: BaseException,
) -> int:
    """把夜里预推未成记到来源轮。429 不记。非 429 的模型耗尽只留相位，代码异常另附错误包。"""
    if _is_provider_rate_limit(exc):
        return 0
    db = session.db
    ctid = _forecast_source_turn(db, snapshot)
    if ctid <= 0:
        return 0
    pack_path = ""
    if not isinstance(exc, LLMUnavailable):
        from ming_sim.audience_night import write_audience_error_pack

        try:
            pack_path = write_audience_error_pack(
                kind=FORECAST_RECOVERY_PHASE, message=str(exc),
                detail={
                    "chat_turn_id": ctid,
                    "pending_action_id": int((snapshot or {}).get("pending_action_id") or 0),
                    "decree_ref": str((snapshot or {}).get("decree_ref") or ""),
                },
                db=db, exc=exc,
            )
        except Exception:
            logger.exception("[decree-forecast] 预推错误包未落")
    db.mark_post_reply_failure(ctid, FORECAST_RECOVERY_PHASE, pack_path)
    return ctid


def note_forecast_staged(
    db: Any, decree_ref: str, *, pending_action_id: int = 0, chat_turn_id: int = 0,
) -> None:
    """暂存落成后丢掉续跑进度。来源轮已没有未成拟旨时才清失败相位。"""
    discard_forecast_progress(db, decree_ref)
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 and int(pending_action_id or 0) > 0:
        ctid = _forecast_source_turn(db, {"pending_action_id": int(pending_action_id)})
    release_forecast_failure_if_idle(db, ctid)


def release_forecast_failure_if_idle(db: Any, chat_turn_id: int) -> None:
    """一旨补成不清同轮另一道未成旨的失败入口。"""
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "conn"):
        return
    if _unfinished_forecast_actions(db, ctid):
        return
    clear_forecast_failure(db, ctid)


def clear_forecast_failure(db: Any, chat_turn_id: int) -> None:
    """预推补成后清相位。只清本相位，不动 after_reply / court_break 的失败行。"""
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "conn"):
        return
    db.conn.execute(
        "UPDATE chat_turns SET post_reply_recovery='', post_reply_error_pack_path='' "
        "WHERE id=? AND post_reply_recovery IN (?, ?)",
        (ctid, FORECAST_RECOVERY_PHASE, f"recovering:{FORECAST_RECOVERY_PHASE}"),
    )
    db.conn.commit()


def _unfinished_forecast_actions(db: Any, chat_turn_id: int) -> list[int]:
    """该轮已应允、仍 pending、且尚无暂存产物的拟旨 id（已成不重落）。"""
    rows = db.conn.execute(
        "SELECT id, version FROM pending_actions "
        "WHERE source_chat_turn_id=? AND kind='directive' AND action='拟旨' "
        "AND status='pending' AND night_approved=1 ORDER BY id",
        (int(chat_turn_id),),
    ).fetchall()
    out: list[int] = []
    for row in rows:
        ref = pending_action_decree_ref(int(row["id"]), int(row["version"] or 1))
        if not db.staged_declarations.staged_for(ref):
            out.append(int(row["id"]))
    return out


def schedule_unfinished_forecasts(session: Any, chat_turn_id: int) -> bool:
    """把该轮仍未预成的拟旨交回现役后台调度。返回是否还有未成。

    用各动作自己的夜与真实版本领票。不在调用方线程里重跑模型链。
    """
    db, ctid = session.db, int(chat_turn_id or 0)
    if ctid <= 0:
        return False
    bind_forecast_owner(session)
    for action_id in _unfinished_forecast_actions(db, ctid):
        row = db.conn.execute(
            "SELECT night_id FROM pending_actions WHERE id=?", (action_id,),
        ).fetchone()
        night_id = int(row["night_id"] or 0) if row is not None else 0
        if night_id > 0:
            schedule_pending_decree_forecast(session, action_id, night_id=night_id)
    return bool(_unfinished_forecast_actions(db, ctid))


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
