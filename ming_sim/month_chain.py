"""ADR 0157 玩家过月主链：步骤 1–3，以及步骤 4–6 的继续条件。

批红答复、邸报作者不在这里实现。推进后的机械尾（#1845：关系／派系酿制与
结局总评）由本链在推进成功后调度到 SessionWriteQueue 后台票，下次过月前 join。
本链不另建无旨快路，也不再走五模块 extractor。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, atomic

_CHAIN_KEY = "month_chain"


def run_world_segment_text(
    db: Any, state: Any, llm_config: Any, agno_db: Any = None,
    cheat_directive: str = "",
) -> str:
    """落账后的盘面只推演一次；缺模型时停在本段，不伪造已完成。"""
    del agno_db
    if llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段缺少模型配置", stage="world-segment")
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
    from ming_sim.decree import ResolveResult
    from ming_sim.decree_forecast import _owner_for
    from ming_sim.mechanical_tail import ensure_mechanical_tails

    turn = int(state.turn)
    chain = _load_chain(db, turn)
    if str(cheat_directive or "").strip() and not chain.get("cheat_directive"):
        chain["cheat_directive"] = str(cheat_directive).strip()
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    session = SimpleNamespace(
        db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content,
    )
    # #1845：下次过月前 join／重开续接上月机械尾（票在 SessionWriteQueue；barrier 等终态）
    owner = _owner_for(db) or session
    if getattr(owner, "db", None) is None:
        owner = session
    else:
        # 保持活 state／模型配置与本链一致
        owner.state = state
        if getattr(owner, "llm_config", None) is None:
            owner.llm_config = llm_config
        if getattr(owner, "agno_db", None) is None:
            owner.agno_db = agno_db
    ensure_mechanical_tails(owner)
    _run_opening_levy(db, chain, turn, decree_text, source)
    def persist_declaration_outcome(outcome: Dict[str, object]) -> None:
        chain["declaration_outcome"] = outcome
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)

    declaration_outcome = _settle_edicts(
        session, registry=registry, on_outcome=persist_declaration_outcome,
    )
    world_outcome = _run_world_segment(session, chain, source=source)
    declaration_outcome = world_outcome or declaration_outcome
    _run_month_drift(db, state, chain, turn, decree_text, source)
    if _waiting_for_rescript(db, state, chain):
        return _pause(db, turn, chain, decree_text, source, "rescript")
    archive = db.get_turn_report_archive(turn)
    if archive is None or not str(archive.get("report") or "").strip():
        return _pause(db, turn, chain, decree_text, source, "gazette")
    advanced = _advance_after_gazette(
        db, state, chain, turn, decree_text, source, content=content,
        declaration_outcome=declaration_outcome,
        llm_config=llm_config, agno_db=agno_db,
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


def _settle_edicts(
    session: Any, *, registry: Any, on_outcome: Any = None,
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
                product = produce_forecast_product(session, snapshot)
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
        chain["world_text"] = run_world_segment_text(
            db, state, session.llm_config, session.agno_db,
            cheat_directive=str(chain.get("cheat_directive") or ""),
        )
        chain["world_text_ready"] = True
        _save_chain(db, turn, chain, decree_text="", source=source)
    if chain.get("world_committed"):
        return chain.get("declaration_outcome")
    prefix, questions = _split_at_question(str(chain.get("world_text") or ""))
    chain["world_questions"] = questions

    def mark(result: Any) -> None:
        outcome = _ending_from_dispatch_result(result)
        if outcome is not None:
            chain["declaration_outcome"] = outcome
        chain["world_committed"] = True
        _save_chain(db, turn, chain, source=source)

    if prefix.strip():
        result = dispatch_month_segment(
            db, state, segment=prefix, llm_config=session.llm_config, source=source,
            alongside=mark,
        )
        return _ending_from_dispatch_result(result)
    with atomic(db):
        mark(None)
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


def _waiting_for_rescript(db: Any, state: Any, chain: Dict[str, Any]) -> bool:
    from ming_sim.decree_forecast import decree_ref_for_dossier

    if chain.get("world_questions"):
        return True
    for dossier in db.list_decree_dossiers():
        if dossier.get("rescript_pending"):
            return True
        if db.staged_declarations.questions_for(decree_ref_for_dossier(db, dossier)):
            return True
    return False


def _advance_after_gazette(
    db: Any, state: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
    *, content: Any = None, declaration_outcome: Optional[Dict[str, object]] = None,
    llm_config: Any = None, agno_db: Any = None,
) -> bool:
    if chain.get("advanced"):
        return True
    from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
    from ming_sim.decree import (
        TIMEOUT_TURN, _carry_pending_clarification_actions, atomic_and_reload,
    )
    from ming_sim.rescript_actions import clear_return_revise_choice_anchors

    settled_year, settled_period = int(state.year), int(state.period)
    ending_outcome: Optional[Dict[str, object]] = None
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
                ending_outcome = dict(outcome)
        elif isinstance(declaration_outcome, dict):
            ending_outcome = dict(declaration_outcome)
        elif isinstance(chain.get("declaration_outcome"), dict):
            ending_outcome = dict(chain["declaration_outcome"])
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
    # #1845：推进后启动机械尾（后台；不挡新月前台）。结局总评属尾，判定已在上面完成。
    from ming_sim.decree_forecast import _owner_for
    from ming_sim.mechanical_tail import schedule_mechanical_tail_after_advance

    owner = _owner_for(db) or SimpleNamespace(
        db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content,
    )
    if getattr(owner, "db", None) is db:
        owner.state = state
        if llm_config is not None:
            owner.llm_config = llm_config
        if agno_db is not None:
            owner.agno_db = agno_db
    schedule_mechanical_tail_after_advance(
        owner,
        closed_turn=int(turn),
        settled_year=settled_year,
        settled_period=settled_period,
        ending_outcome=ending_outcome,
        source=source,
    )
    return True


def _pause(
    db: Any, turn: int, chain: Dict[str, Any], decree_text: str, source: Provenance, stage: str,
) -> Any:
    from ming_sim.decree import ResolveResult

    chain["stage"] = stage
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    return ResolveResult(awaiting=False, advanced=False, stage=stage)


def _split_at_question(text: str) -> tuple[str, List[dict]]:
    from ming_sim.decree import _DECISION_RE, parse_decision_blocks

    for match in _DECISION_RE.finditer(text):
        parsed = parse_decision_blocks(match.group(0))[1]
        if parsed:
            return text[:match.start()], list(parsed)
    return text, []


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
