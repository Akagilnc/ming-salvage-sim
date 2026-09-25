"""ADR 0157 玩家过月主链：步骤 1–3，以及步骤 4–6 的继续条件。

#1846：模型调用用尽 / 代码异常停在当前过月 run，恢复真源 = 暂存声明 + 落账
状态 + 本链 call_failure；玩家重试只续未完成步，转译逃生口由同一颗重试触发。

#1847：步骤 4 请旨/打回三选统一收口既有 HITL 案头；答复后从问处续推再交步骤 5。
批红文书页呈现归 #1826；邸报作者归 #1862。不另造平行机制。不另建无旨快路，
也不再走五模块 extractor。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, atomic

_CHAIN_KEY = "month_chain"
_TRANSLATE_ESCAPE_STEPS = frozenset({"world_translate"})
_WORLD_QUESTION_PREFIX = "world-question:"
_DECREE_QUESTION_PREFIX = "decree-question:"


def run_world_segment_text(
    db: Any, state: Any, llm_config: Any, agno_db: Any = None,
    cheat_directive: str = "",
) -> str:
    """落账后的盘面只推演一次；缺模型时停在本段，不伪造已完成。"""
    del agno_db
    if llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段缺少模型配置", stage="world_text")
    from ming_sim.agents import create_world_segment_agent, run_agent_text
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import prepare_world_materials, release_material_tree

    prepared = prepare_world_materials(db, state)
    message = "推演本月世界段。"
    if str(cheat_directive or "").strip():
        message = str(cheat_directive).strip() + "\n" + message
    try:
        agent = create_world_segment_agent(llm_config, prepared)
        return run_agent_text(
            agent, message, tag="world-segment",
            transport_policy=audience_transport_policy(),
        )
    finally:
        release_material_tree(prepared.root)


def month_chain_call_failure(db: Any, turn: int) -> Optional[Dict[str, Any]]:
    """核账期恢复投影只读：本月链上未消费的调用失败（无则 None）。"""
    chain = _load_chain(db, int(turn))
    failure = chain.get("call_failure")
    return dict(failure) if isinstance(failure, dict) else None


def continue_world_after_answers(
    session: Any, chain: Dict[str, Any], *, answers: List[Dict[str, object]], source: Provenance,
) -> Optional[Dict[str, object]]:
    """批红答复后从问处续推世界段一次；问前已落不动，整段不重推。

    消费事实（清问 + world_continued）与落账同事务：LLM 先跑，失败零消费可重试；
    成功则随 dispatch_month_segment 的 alongside 原子落旗（ADR 0157 恢复幂等）。
    """
    from ming_sim.month_translate import dispatch_month_segment

    db, state = session.db, session.state
    turn = int(state.turn)
    if chain.get("world_continued"):
        chain["world_questions"] = []
        _save_chain(db, turn, chain, source=source)
        return chain.get("declaration_outcome")
    if session.llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段续推缺少模型配置", stage="world-segment-continue")
    text = _run_world_continuation_text(session, chain, answers)
    outcome = None

    def mark_continued(result: Any = None) -> None:
        nonlocal outcome
        candidate = _ending_from_dispatch_result(result)
        if candidate is not None:
            chain["declaration_outcome"] = candidate
            outcome = candidate
        chain["world_questions"] = []
        chain["world_continued"] = True
        _save_chain(db, turn, chain, source=source)

    if str(text or "").strip():
        # 续推若再吐 DECISION 机标，只落问前缀文，勿把机标喂进转译。
        prefix, _extra = _split_at_question(str(text))
        if prefix.strip():
            result = dispatch_month_segment(
                db, state, segment=prefix, llm_config=session.llm_config, source=source,
                alongside=mark_continued,
            )
            return _ending_from_dispatch_result(result) or outcome
    # 空续推：无落账后果，仍须原子记下已续，避免重入再烧。
    with atomic(db):
        mark_continued(None)
    return outcome


def continue_decree_after_answers(
    session: Any, *, decree_ref: str, answers: List[Dict[str, object]],
    source: Provenance = Provenance.player_decree,
) -> None:
    """批红答复后从问处续推该旨一次；问前已落声明不动。

    同一 decree_ref 问前声明可能已 settled，续推声明直接分派，不另造平行暂存身份。
    幂等：questions 已清则视为已续，同回合重入零新增效果。
    消费事实（清问）与落账同事务——先跑续推 LLM，失败保留 questions 可重试；
    有声明则 clear_questions 走既有段分派的 alongside（ADR 0157）。
    """
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.month_translate import dispatch_month_segment

    db, state = session.db, session.state
    if not db.staged_declarations.questions_for(decree_ref):
        return
    if session.llm_config is None:
        raise LLMUnavailable("旨意续推缺少模型配置", stage="decree-forecast-continue")
    dossier = _dossier_for_decree_ref(db, decree_ref)
    if dossier is None:
        return
    text = _run_decree_continuation_text(session, dossier, answers)
    prefix, _extra = _split_at_question(str(text or ""))
    if not prefix.strip():
        # LLM 已成功且无问后文：空后果终态，方可清问。
        db.staged_declarations.clear_questions(decree_ref)
        return
    payload = dossier.get("payload") if isinstance(dossier.get("payload"), dict) else {}

    def consume(_result: Any) -> None:
        db.staged_declarations.clear_questions(decree_ref)

    dispatch_month_segment(
        db, state, segment=prefix,
        decree_payload=payload if isinstance(payload, dict) else {},
        llm_config=session.llm_config,
        source=source,
        alongside=consume,
    )


def _run_decree_continuation_text(
    session: Any, dossier: Dict[str, Any], answers: List[Dict[str, object]],
) -> str:
    import json

    from ming_sim.agents import create_decree_forecast_agent, run_agent_text
    from ming_sim.decree_forecast import decree_ref_for_dossier
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim import decree as decree_mod
    from ming_sim import simulation

    db, state = session.db, session.state
    decree_ref = decree_ref_for_dossier(db, dossier)
    visible = dict(dossier)
    visible["promulgation_decision"] = "promulgated"
    projected = decree_mod.project_dossiers_for_simulator([visible], db, state)
    sim_payload = simulation.build_simulator_payload(
        state, db, str(dossier.get("decree_text") or ""), "",
        decree_dossiers=projected,
    )
    # 与夜里逐旨预推同一边界：续推这一道旨，不带世界候选事件。
    sim_payload["candidate_events"] = []
    sim_payload["rescript_answers"] = list(answers)
    agent = create_decree_forecast_agent(session.llm_config, sim_payload)
    return run_agent_text(
        agent,
        json.dumps({
            "instruction": "皇帝已批红答复本旨请旨。只续写问后后果，勿重写问前已落之事。",
            "prior_forecast_text": db.staged_declarations.forecast_text_for(decree_ref),
            "questions": db.staged_declarations.questions_for(decree_ref),
            "answers": answers,
        }, ensure_ascii=False),
        tag="decree-forecast-continue",
        transport_policy=audience_transport_policy(),
    )


def run_player_month_chain(
    state: Any,
    db: Any,
    agno_db: Any,
    llm_config: Any,
    *,
    decree_text: str = "",
    before_turn: int = 0,
    on_event: Any = None,
    content: Any = None,
    registry: Any = None,
    source: Provenance = Provenance.system_simulation,
    cheat_directive: str = "",
) -> Any:
    """从现有过月入口继续。已落的旨不动，未落的按序接着落。"""
    del on_event, before_turn
    from ming_sim.exceptions import LLMUnavailable, SettlementAbort

    turn = int(state.turn)
    chain = _load_chain(db, turn)

    def abort_from(exc: BaseException) -> None:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, SettlementAbort)):
            raise exc
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=str(getattr(exc, "stage", None) or "month_chain"),
            exc=exc,
            kind="model_exhausted" if isinstance(exc, LLMUnavailable) else "code_exception",
        )

    try:
        if str(cheat_directive or "").strip() and not chain.get("cheat_directive"):
            chain["cheat_directive"] = str(cheat_directive).strip()
            _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        _consume_call_failure_for_retry(db, chain, turn, decree_text, source)
    except Exception as exc:
        abort_from(exc)
    # 请旨续推的原故障原样上浮：问与 world_continued 都未消费，批红入口重试看见同一颗异常。
    _consume_rescript_answers(
        SimpleNamespace(
            db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content,
        ),
        chain, source=source,
    )
    try:
        return _run_loaded_month_chain(
            state, db, agno_db, llm_config, chain,
            decree_text=decree_text, content=content, registry=registry,
            source=source,
        )
    except Exception as exc:
        abort_from(exc)
    raise AssertionError("month chain abort must raise")


def _run_loaded_month_chain(
    state: Any,
    db: Any,
    agno_db: Any,
    llm_config: Any,
    chain: Dict[str, Any],
    *,
    decree_text: str,
    content: Any,
    registry: Any,
    source: Provenance,
) -> Any:
    """已装入的月链。代码异常由入口收成同一条 call_failure，不在这里另做恢复。"""
    from ming_sim.decree import ResolveResult

    turn = int(state.turn)
    session = SimpleNamespace(
        db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content,
    )
    _run_opening_levy(db, chain, turn, decree_text, source)

    def persist_declaration_outcome(outcome: Dict[str, object]) -> None:
        chain["declaration_outcome"] = outcome
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)

    declaration_outcome = _settle_edicts(
        session, registry=registry, chain=chain, on_outcome=persist_declaration_outcome,
    )
    world_outcome = _run_world_segment(session, chain, source=source)
    declaration_outcome = world_outcome or declaration_outcome
    _run_month_drift(db, state, chain, turn, decree_text, source)
    desk = _materialize_rescript_desk(db, state, chain)
    if desk is not None:
        return ResolveResult(
            awaiting=True, decisions=desk, advanced=False, stage="rescript",
        )
    archive = db.get_turn_report_archive(turn)
    if archive is None or not str(archive.get("report") or "").strip():
        return _pause(db, turn, chain, decree_text, source, "gazette")
    advanced = _advance_after_gazette(
        db, state, chain, turn, decree_text, source, content=content,
        declaration_outcome=declaration_outcome,
    )
    return ResolveResult(
        awaiting=False, advanced=advanced, stage="advanced" if advanced else "gazette",
    )


def _run_opening_levy(
    db: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    """月初旧账只消费一次，先于本月旨意改账。"""
    if chain.get("opening_levy_done"):
        return
    from ming_sim.issues import _apply_levy_driven_transfers
    from ming_sim.applier import RejectionCollector, mirror_rejections_after_commit
    from ming_sim.decree import _collect_inline_rejections
    from ming_sim.error_pack import rejections_jsonl_path

    collector = RejectionCollector()
    with atomic(db):
        _applied, rejected = _apply_levy_driven_transfers(db, commit=False)
        if rejected:
            _collect_inline_rejections(
                collector, {"population_transfers_rejections": rejected}, turn,
                source,
            )
            collector.flush_to_db(db)
        chain["opening_levy_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        mirror_rejections_after_commit(db, collector, rejections_jsonl_path)


def _consume_call_failure_for_retry(
    db: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    """玩家点「重试」再入主链：按需丢段，然后清失败标记，只续未完成步。"""
    failure = chain.get("call_failure")
    if not isinstance(failure, dict):
        return
    step = str(failure.get("step") or "")
    if failure.get("escape_armed") and step in _TRANSLATE_ESCAPE_STEPS:
        _discard_segment_for_escape(chain, failure)
        chain["translate_exhaust_stops"] = 0
    chain.pop("call_failure", None)
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)


def _discard_segment_for_escape(
    chain: Dict[str, Any], failure: Dict[str, Any],
) -> None:
    """完整段文转译反复用尽后的逃生口：丢未落段文，已落账不动。"""
    step = str(failure.get("step") or "")
    if step == "world_translate":
        chain.pop("world_text", None)
        chain["world_text_ready"] = False
        chain.pop("world_questions", None)


def _abort_month_call(
    db: Any,
    state: Any,
    chain: Dict[str, Any],
    *,
    decree_text: str,
    source: Provenance,
    step: str,
    exc: BaseException,
    kind: str,
    decree_ref: str = "",
) -> None:
    """停住当前过月 run：持久化相位内 call_failure + 错误包，再 SettlementAbort。"""
    from ming_sim.error_pack import settlement_abort_message, write_error_pack
    from ming_sim.exceptions import SettlementAbort

    turn = int(state.turn)
    # 事务已回滚时，失败记录只叠在已提交链上。调用方链在 alongside 里改过的
    # 内存相位（world_committed 等）不随失败写回。
    if (
        kind == "code_exception"
        and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0
    ):
        from ming_sim.decree import reload_state_from_db
        reload_state_from_db(db, state, content=getattr(db, "content", None))
    committed = _load_chain(db, turn)
    escape_armed = False
    if kind == "model_exhausted" and step in _TRANSLATE_ESCAPE_STEPS:
        stops = int(committed.get("translate_exhaust_stops") or 0) + 1
        committed["translate_exhaust_stops"] = stops
        escape_armed = stops >= 2
    original = str(getattr(exc, "message", None) or exc)
    pack_path = ""
    pack_exc: Optional[BaseException] = None
    try:
        pack_path = write_error_pack(
            db, state, exc=exc, extracted=None, resolve_ctx=None,
        )
    except Exception as caught_pack:
        # 写包失败不得顶替原故障，也不得挡住已提交相位上的失败标记。
        pack_exc = caught_pack
    failure: Dict[str, Any] = {
        "kind": kind,
        "step": step,
        "message": original,
        "escape_armed": escape_armed,
    }
    if pack_path:
        failure["error_pack_path"] = pack_path
    if decree_ref:
        failure["decree_ref"] = decree_ref
    committed["call_failure"] = failure
    chain.clear()
    chain.update(committed)
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    if pack_exc is not None:
        raise SettlementAbort(
            original, turn=turn, stage=step, error_pack_path=None,
        ) from pack_exc
    abort_message = (
        settlement_abort_message(pack_path) if kind == "code_exception" else original
    )
    raise SettlementAbort(
        abort_message,
        turn=turn,
        stage=step,
        error_pack_path=pack_path,
    ) from exc


def _guard_month_call(
    db: Any,
    state: Any,
    chain: Dict[str, Any],
    *,
    decree_text: str,
    source: Provenance,
    step: str,
    operation: Any,
    decree_ref: str = "",
    code_step: Optional[str] = None,
) -> Any:
    """模型用尽 → 停住可重试；其它代码异常 → 错误包后停住；中断类原样上浮。"""
    from ming_sim.exceptions import LLMUnavailable, SettlementAbort

    try:
        return operation()
    except LLMUnavailable as exc:
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=step, exc=exc, kind="model_exhausted", decree_ref=decree_ref,
        )
    except (KeyboardInterrupt, SystemExit, SettlementAbort):
        raise
    except Exception as exc:
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=code_step or step, exc=exc, kind="code_exception", decree_ref=decree_ref,
        )
    raise AssertionError("month call abort must raise")


def _settle_edicts(
    session: Any, *, registry: Any, chain: Dict[str, Any], on_outcome: Any = None,
) -> Optional[Dict[str, object]]:
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    from ming_sim.decree import _is_stalled_deliberation
    from ming_sim.decree_forecast import (
        _is_held_for_rejudgment,
        decree_ref_for_dossier,
        produce_forecast_product,
        snapshot_for_existing_dossier,
        stage_declaration,
    )

    db, state = session.db, session.state
    outcome = None
    for dossier in db.list_decree_dossiers():
        if _is_stalled_deliberation(dossier):
            continue
        status = str(dossier.get("status") or "")
        created = int(dossier.get("created_turn") or 0)
        held = _is_held_for_rejudgment(dossier, int(state.turn))
        ref = decree_ref_for_dossier(db, dossier)
        promulgated = str(dossier.get("promulgation_decision") or "") in {
            "promulgated", "force_promulgated",
        } or status == "promulgated"
        this_month = created == int(state.turn) or held
        pending_settle = (
            promulgated and not db.staged_declarations.is_settled(ref)
            and bool(db.staged_declarations.staged_for(ref))
        )
        if not (this_month and status == "proposed") and not pending_settle:
            continue
        if (
            status == "proposed"
            and (not dossier.get("promulgation_decision") or held)
            and not db.staged_declarations.is_settled(ref)
        ):
            staged = db.staged_declarations.staged_for(ref)
            verdict = staged[0].verdict if staged else None
            if verdict is None and session.llm_config is not None:
                snapshot = snapshot_for_existing_dossier(session, dossier)

                def _produce() -> Dict[str, Any]:
                    return produce_forecast_product(session, snapshot)

                product = _guard_month_call(
                    db, state, chain, decree_text="", source=Provenance.player_decree,
                    step="edict_forecast", operation=_produce, decree_ref=ref,
                )
                stage_declaration(
                    db, decree_ref=ref,
                    declaration=product["declaration"] or {},
                    turn=int(state.turn),
                    verdict=product["verdict"],
                    questions=product["questions"],
                    forecast_text=product["forecast_text"],
                    visible_refs=snapshot.get("visible_refs"),
                )
                verdict = product["verdict"]
            if isinstance(verdict, dict) and verdict.get("decision"):
                current = db.get_decree_dossier(int(dossier["id"])) or dossier
                if str(current.get("status") or "") == "proposed":
                    db.apply_dossier_promulgation(
                        state, int(dossier["id"]), str(verdict["decision"]),
                        blocked_layer=str(verdict.get("blocked_layer") or ""),
                        reason=str(verdict.get("reason") or ""),
                        legal_reason_code=str(verdict.get("legal_reason_code") or ""),
                        primary_opponents=verdict.get("primary_opponents") or [],
                        gatekeeper_id=verdict.get("gatekeeper_id"),
                        criteria_snapshot=verdict.get("criteria_snapshot") or {},
                        content=session.content, registry=registry,
                    )
        current = db.get_decree_dossier(int(dossier["id"])) or dossier
        if str(current.get("promulgation_decision") or "") == "promulgated":
            def persist_result(_ref: str, result: Any) -> None:
                nonlocal outcome
                candidate = _ending_from_dispatch_result(result)
                if candidate is not None:
                    outcome = candidate
                    if on_outcome is not None:
                        on_outcome(candidate)

            settle_staged_declarations_in_decree_order(
                db, state, [ref], source=Provenance.player_decree,
                alongside=persist_result,
            )
    return outcome


def _ending_from_dispatch_result(result: Any) -> Optional[Dict[str, object]]:
    if result is None:
        return None
    for report in result.effects.applied:
        candidate = report.get("victory_status") if isinstance(report, dict) else None
        if isinstance(candidate, dict) and candidate.get("status") != "ongoing":
            return candidate
    return None


def _run_world_segment(
    session: Any, chain: Dict[str, Any], *, source: Provenance,
) -> Optional[Dict[str, object]]:
    from ming_sim.month_translate import dispatch_month_segment

    db, state = session.db, session.state
    turn = int(state.turn)
    if not chain.get("world_text_ready"):
        def _push() -> str:
            return run_world_segment_text(
                db, state, session.llm_config, session.agno_db,
                cheat_directive=str(chain.get("cheat_directive") or ""),
            )

        chain["world_text"] = _guard_month_call(
            db, state, chain, decree_text="", source=source,
            step="world_text", operation=_push,
        )
        chain["world_text_ready"] = True
        _save_chain(db, turn, chain, decree_text="", source=source)
    if chain.get("world_committed"):
        return chain.get("declaration_outcome")
    prefix, questions = _split_at_question(str(chain.get("world_text") or ""))
    chain["world_questions"] = questions

    def mark(result: Any) -> None:
        # 完成标记与世界效果同一事务；调用方链要等提交成功后再采纳。
        persisted = dict(chain)
        outcome = _ending_from_dispatch_result(result)
        if outcome is not None:
            persisted["declaration_outcome"] = outcome
        persisted["world_committed"] = True
        persisted.pop("translate_exhaust_stops", None)
        _save_chain(db, turn, persisted, source=source)

    def adopt_committed() -> None:
        chain.clear()
        chain.update(_load_chain(db, turn))

    if prefix.strip():
        result = _guard_month_call(
            db, state, chain, decree_text="", source=source,
            step="world_translate", code_step="world_commit",
            operation=lambda: dispatch_month_segment(
                db, state, segment=prefix, llm_config=session.llm_config, source=source,
                alongside=mark,
            ),
        )
        adopt_committed()
        return _ending_from_dispatch_result(result)
    with atomic(db):
        mark(None)
    adopt_committed()
    return None


def _run_month_drift(
    db: Any, state: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    if chain.get("inertia_done") or not chain.get("world_committed"):
        return
    from ming_sim.issues import apply_issue_inertia_and_ongoing, clear_gated_legacies
    from ming_sim.due_review import apply_pending_due_reviews
    from ming_sim.staged_commitment import write_due_staged_commitment_todos
    from ming_sim.breach_plea import expire_breach_pleas_on_due, scan_and_write_breach_pleas
    from ming_sim.covert_progress import settle_due_secret_orders
    from ming_sim.urge_lever import consume_pending_urge_audience_todos
    from ming_sim.audience_night import retire_unsettled_summons_for_inactive
    from ming_sim.applier import RejectionCollector, mirror_rejections_after_commit
    from ming_sim.decree import _collect_inline_rejections
    from ming_sim.error_pack import rejections_jsonl_path

    collector = RejectionCollector()
    with atomic(db):
        db.record_monthly_supervision_presence(turn, commit=False)
        retire_unsettled_summons_for_inactive(db)
        rejections = apply_issue_inertia_and_ongoing(db, state)
        if rejections:
            _collect_inline_rejections(
                collector, {"issue_inertia": {"entity_rejections": rejections}},
                turn, source,
            )
            collector.flush_to_db(db)
        db.recompute_all_faction_leverage()
        clear_gated_legacies(db, state)
        apply_pending_due_reviews(db, state, commit=False)
        settle_due_secret_orders(db, state, commit=False)
        expire_breach_pleas_on_due(db, state, commit=False)
        consume_pending_urge_audience_todos(db, state, commit=False)
        write_due_staged_commitment_todos(db, state, commit=False)
        scan_and_write_breach_pleas(db, state, commit=False)
        chain["inertia_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        mirror_rejections_after_commit(db, collector, rejections_jsonl_path)


def _open_rescript_items(
    db: Any, state: Any, chain: Dict[str, Any],
) -> Dict[str, Any]:
    """本回合待答：打回三选 + 旨意请旨 + 世界段请旨。上月已答项不入。"""
    from ming_sim.decree_forecast import decree_ref_for_dossier

    turn = int(state.turn)
    triad = _this_turn_rescript_dossiers(db, turn)
    decree_questions: List[tuple[str, list]] = []
    seen_refs: set[str] = set()
    for dossier in db.list_decree_dossiers():
        ref = decree_ref_for_dossier(db, dossier)
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        questions = db.staged_declarations.questions_for(ref)
        if questions:
            # 未答请旨不论案卷创建回合，均须本回合收口（#1847 / 留中回流同审）。
            decree_questions.append((ref, questions))
    world_questions = [
        q for q in (chain.get("world_questions") or []) if isinstance(q, dict)
    ]
    return {
        "triad": triad,
        "decree_questions": decree_questions,
        "world_questions": world_questions,
    }


def _this_turn_rescript_dossiers(db: Any, turn: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for dossier in db.list_decree_dossiers():
        if not dossier.get("rescript_pending"):
            continue
        if not _dossier_rejection_is_this_turn(db, dossier, turn):
            continue
        out.append(dossier)
    return out


def _dossier_rejection_is_this_turn(db: Any, dossier: Dict[str, Any], turn: int) -> bool:
    dossier_id = int(dossier["id"])
    if int(dossier.get("created_turn") or 0) == turn:
        return True
    row = db.conn.execute(
        "SELECT turn, rescript_action FROM decree_dossier_decisions "
        "WHERE dossier_id=? AND decision='rejected' ORDER BY id DESC LIMIT 1",
        (dossier_id,),
    ).fetchone()
    if row is None:
        return False
    # 上月已作三选（hold/withdrawn/force）的旧件即使残留 pending 也不再挡本月。
    if str(row["rescript_action"] or "").strip():
        return False
    return int(row["turn"] or 0) == turn


def _materialize_rescript_desk(
    db: Any, state: Any, chain: Dict[str, Any],
) -> Optional[List[Dict[str, object]]]:
    from ming_sim.decree import _rescript_decisions

    open_items = _open_rescript_items(db, state, chain)
    turn = int(state.turn)
    decisions: List[Dict[str, object]] = []
    if open_items["triad"]:
        verdicts = []
        for dossier in open_items["triad"]:
            hist = db.list_decree_dossier_decisions(int(dossier["id"]))
            latest = hist[-1] if hist else {}
            verdicts.append({
                "dossier_id": int(dossier["id"]),
                "decision": "rejected",
                "reason": str(
                    dossier.get("promulgation_reason") or latest.get("reason") or ""
                ),
                "primary_opponents": (
                    dossier.get("primary_opponents")
                    or latest.get("primary_opponents")
                    or []
                ),
                "midzhi_unpromulgatable": bool(
                    (latest or {}).get("midzhi_unpromulgatable")
                ),
            })
        decisions.extend(_rescript_decisions(verdicts, open_items["triad"]))
    for ref, questions in open_items["decree_questions"]:
        for idx, question in enumerate(questions):
            if not isinstance(question, dict):
                continue
            decisions.append(_question_as_decision(
                question, event_id=f"{_DECREE_QUESTION_PREFIX}{ref}:{idx}",
            ))
    for idx, question in enumerate(open_items["world_questions"]):
        decisions.append(_question_as_decision(
            question, event_id=f"{_WORLD_QUESTION_PREFIX}{turn}:{idx}",
        ))
    if decisions:
        db.save_pending_decisions(turn, decisions)
    # 已应用 return_revise 仍 pending，但是本批已办，不是新待裁。
    # 清锚仍只走推进事务里的 clear_return_revise_choice_anchors。
    desk = [
        row for row in db.list_rescript_desk(turn)
        if not _row_is_applied_return_revise(row)
    ]
    if not desk:
        return None
    chain["stage"] = "rescript"
    _save_chain(db, turn, chain, source=Provenance.system_simulation)
    return desk


def _row_is_applied_return_revise(row: Dict[str, object]) -> bool:
    """行上已应用改票锚。谓词只认 rescript_actions._is_applied_revise_anchor。"""
    from ming_sim.rescript_actions import _is_applied_revise_anchor

    choice = row.get("choice")
    if not isinstance(choice, dict):
        return False
    return _is_applied_revise_anchor(row, choice)


def _question_as_decision(question: Dict[str, object], *, event_id: str) -> Dict[str, object]:
    options = question.get("options") if isinstance(question.get("options"), list) else []
    cleaned = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        label = str(opt.get("label") or "").strip()
        if not label:
            continue
        cleaned.append({
            "label": label,
            "hint": str(opt.get("hint") or "").strip(),
            **{
                key: opt[key] for key in opt
                if key not in {"label", "hint"} and opt[key] is not None
            },
        })
    return {
        "event_id": event_id,
        "title": str(question.get("title") or "").strip() or "请旨",
        "context": str(question.get("context") or "").strip(),
        "options": cleaned,
    }


def _consume_rescript_answers(
    session: Any, chain: Dict[str, Any], *, source: Provenance,
) -> None:
    """把已裁批红接回案卷 / 请旨续推；幂等，已落不动。

    同一旨 / 同一世界段多问须全部答完才续推一次（ADR 0157 步骤 4）。
    """
    db, state = session.db, session.state
    turn = int(state.turn)
    rows = db.list_pending_decisions(turn)
    decided = [r for r in rows if str(r.get("status") or "") == "decided"]
    if not decided:
        return

    def _answer_from_row(row: Dict[str, object]) -> Dict[str, object]:
        choice = row.get("choice") if isinstance(row.get("choice"), dict) else {}
        return {
            "label": str(choice.get("label") or "").strip(),
            "hint": str(choice.get("hint") or "").strip(),
            "note": str(choice.get("note") or "").strip(),
            "context": str(row.get("context") or "").strip(),
            "event_id": str(row.get("event_id") or ""),
            "title": str(row.get("title") or ""),
        }

    for row in decided:
        event_id = str(row.get("event_id") or "")
        if not event_id.startswith("dossier:"):
            continue
        choice = row.get("choice") if isinstance(row.get("choice"), dict) else {}
        _apply_decided_triad(db, state, row, choice, content=session.content)

    world_rows = [
        r for r in rows
        if str(r.get("event_id") or "").startswith(_WORLD_QUESTION_PREFIX)
    ]
    if (
        world_rows
        and all(str(r.get("status") or "") == "decided" for r in world_rows)
        and chain.get("world_questions")
    ):
        continue_world_after_answers(
            session, chain,
            answers=[_answer_from_row(r) for r in world_rows],
            source=source,
        )

    decree_rows_by_ref: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        event_id = str(row.get("event_id") or "")
        if not event_id.startswith(_DECREE_QUESTION_PREFIX):
            continue
        body = event_id[len(_DECREE_QUESTION_PREFIX):]
        ref = body.rsplit(":", 1)[0] if ":" in body else body
        decree_rows_by_ref.setdefault(ref, []).append(row)
    for ref, ref_rows in decree_rows_by_ref.items():
        if not all(str(r.get("status") or "") == "decided" for r in ref_rows):
            continue
        continue_decree_after_answers(
            session, decree_ref=ref,
            answers=[_answer_from_row(r) for r in ref_rows],
            source=source,
        )


def _apply_decided_triad(
    db: Any, state: Any, row: Dict[str, object], choice: Dict[str, object], *, content: Any,
) -> None:
    event_id = str(row.get("event_id") or "")
    raw_id = event_id.split(":", 1)[1] if ":" in event_id else ""
    if not raw_id.isdigit():
        return
    dossier_id = int(raw_id)
    dossier = db.get_decree_dossier(dossier_id)
    if dossier is None or not dossier.get("rescript_pending"):
        return
    decision = str(
        choice.get("dossier_decision") or choice.get("action") or ""
    ).strip()
    if decision not in {"force_promulgated", "withdrawn", "hold"}:
        return
    db.apply_dossier_promulgation(
        state, dossier_id, decision, content=content,
    )


def _run_world_continuation_text(
    session: Any, chain: Dict[str, Any], answers: List[Dict[str, object]],
) -> str:
    if session.llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段续推缺少模型配置", stage="world-segment-continue")
    from ming_sim.agents import create_world_segment_agent, run_agent_text
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import prepare_world_materials, release_material_tree
    import json

    prepared = prepare_world_materials(session.db, session.state)
    try:
        agent = create_world_segment_agent(session.llm_config, prepared)
        payload = {
            "instruction": "皇帝已批红答复世界段请旨。只续写问后后果，勿重写问前已落之事。",
            "answers": answers,
            "prior_world_text": str(chain.get("world_text") or ""),
        }
        return run_agent_text(
            agent, json.dumps(payload, ensure_ascii=False), tag="world-segment-continue",
            transport_policy=audience_transport_policy(),
        )
    finally:
        release_material_tree(prepared.root)


def _dossier_for_decree_ref(db: Any, decree_ref: str) -> Optional[Dict[str, Any]]:
    from ming_sim.decree_forecast import decree_ref_for_dossier

    for dossier in db.list_decree_dossiers():
        if decree_ref_for_dossier(db, dossier) == decree_ref:
            return dossier
    if decree_ref.startswith("dossier:"):
        raw = decree_ref.split(":", 1)[1]
        if raw.isdigit():
            return db.get_decree_dossier(int(raw))
    return None


def _advance_after_gazette(
    db: Any, state: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
    *, content: Any = None, declaration_outcome: Optional[Dict[str, object]] = None,
) -> bool:
    if chain.get("advanced"):
        return True
    from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
    from ming_sim.decree import (
        TIMEOUT_TURN, _carry_pending_clarification_actions, atomic_and_reload,
    )
    from ming_sim.rescript_actions import clear_return_revise_choice_anchors

    with atomic_and_reload(db, state, content=content):
        if not state.ended:
            outcome = declaration_outcome or chain.get("declaration_outcome") or victory_status(db, state)
            if (
                isinstance(outcome, dict)
                and outcome.get("status") == ENDING_ONGOING
                and state.turn >= TIMEOUT_TURN
            ):
                outcome = {
                    "status": ENDING_TIMEOUT,
                    "summary": ENDING_LABELS.get(ENDING_TIMEOUT, ""),
                }
            if isinstance(outcome, dict) and outcome.get("status") != ENDING_ONGOING:
                state.ended = True
                state.ending_status = str(outcome.get("status") or "")
        db.mark_directives_issued(state)
        clear_return_revise_choice_anchors(db, None)
        state.next_period()
        _carry_pending_clarification_actions(db, state, turn, content=content)
        state.turn_phase = "issued"
        db.save_state(state)
        db.clear_month_open_snapshot(turn)
        chain["advanced"] = True
        chain["stage"] = "advanced"
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    return True


def _pause(
    db: Any, turn: int, chain: Dict[str, Any], decree_text: str, source: Provenance, stage: str,
) -> Any:
    from ming_sim.decree import ResolveResult

    chain["stage"] = stage
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    return ResolveResult(awaiting=False, advanced=False, stage=stage)


def _split_at_question(text: str) -> tuple[str, List[dict]]:
    """前缀 = 首个合法 DECISION 之前；questions = 该段全部合法请旨块。"""
    from ming_sim.decree import _DECISION_RE, parse_decision_blocks

    questions: List[dict] = []
    first_start: Optional[int] = None
    for match in _DECISION_RE.finditer(text):
        parsed = parse_decision_blocks(match.group(0))[1]
        if not parsed:
            continue
        if first_start is None:
            first_start = match.start()
        questions.extend(parsed)
    if first_start is None:
        return text, []
    return text[:first_start], questions


def _load_chain(db: Any, turn: int) -> Dict[str, Any]:
    ctx = db.get_resolve_context(turn) or {}
    payload = ctx.get("simulator_payload") or {}
    chain = payload.get(_CHAIN_KEY) if isinstance(payload, dict) else None
    return dict(chain) if isinstance(chain, dict) else {}


def _save_chain(
    db: Any, turn: int, chain: Dict[str, Any], *,
    decree_text: str = "", source: Provenance = Provenance.system_simulation,
) -> None:
    ctx = db.get_resolve_context(turn) or {}
    payload = dict(ctx.get("simulator_payload") or {})
    payload[_CHAIN_KEY] = chain
    stored_source = ctx.get("source") or source
    source_value = stored_source.value if isinstance(stored_source, Provenance) else str(stored_source)
    db.save_resolve_context(
        turn,
        decree_text or str(ctx.get("decree_text") or ""),
        str(ctx.get("narrative") or ""),
        payload,
        secret_orders=ctx.get("secret_orders"),
        relevant_memories=ctx.get("relevant_memories"),
        extracted=ctx.get("extracted"),
        source=source_value or Provenance.system_simulation.value,
        attendant_message=str(ctx.get("attendant_message") or ""),
    )
