"""Shared light GameSession + canned monthly LLM seams (no external model).

Used by full-settlement tracers (#1274 no-edict, #652 judge chain, …).
Only replaces outer LLM factories/calls; production spine stays real.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import ming_sim.decree as decree_mod
from ming_sim.session import GameSession


def make_light_session(db, state, content):
    """Minimal GameSession shell for advance_without_decree tracers."""
    from ming_sim.decree_forecast import bind_forecast_owner
    from ming_sim.session_write_queue import get_session_write_queue

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.content = content
    session.registry = None
    session.llm_config = None
    session.agno_db = None
    session.deaths_this_turn = []
    session.debuts_this_turn = []
    session.last_decree = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session._write_gate = None
    session.auto_save = lambda *a, **k: None
    bind_forecast_owner(session)
    from tests.conftest import note_queue_until_game_teardown

    note_queue_until_game_teardown(db, get_session_write_queue(session))
    return session


def canned_full_settlement(
    monkeypatch,
    *,
    narrative: str = "本月边情邸报：辽饷催征，流寇未息。",
    decisions: Optional[List[Dict[str, object]]] = None,
    simulator_calls: Optional[list] = None,
    source_spy: Optional[list] = None,
    skip_fixed_flows: bool = False,
    skip_relation_brew: bool = False,
) -> list:
    """Replace only external LLM seams; keep production settlement spine.

    """
    simulator_calls = simulator_calls if simulator_calls is not None else []
    decisions = list(decisions or [])
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    # #658：真实 ensure 成案后颁布判官亦为外部 LLM 缝——canned 默认全顺颁。
    # 替身换 llm_promulgation_verdicts 后生产不触 get_or_create，无需再 patch 工厂。
    def _promulgate(dossiers, *_a, **_k):
        return [
            {"dossier_id": int(row["id"]), "decision": "promulgated"}
            for row in dossiers
        ]

    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", _promulgate)

    def _sim(*a, **k):
        payload = k.get("simulator_payload") or (a[10] if len(a) > 10 else None) or {}
        simulator_calls.append({
            "decree_text": a[3] if len(a) > 3 else k.get("decree_text", ""),
            "payload": payload,
        })
        text = narrative
        if decisions:
            blocks = []
            for i, d in enumerate(decisions):
                title = d.get("title") or f"决策{i}"
                opts = d.get("options") or ["准", "不准"]
                opt_lines = "\n".join(f"- {o}" for o in opts)
                blocks.append(
                    f"<<DECISION title=\"{title}\">>\n{opt_lines}\n<</DECISION>>"
                )
            text = text + "\n" + "\n".join(blocks)
        return text, payload

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _sim)

    def _world(*_a, **_k):
        simulator_calls.append({"world": True, "narrative": narrative})
        return narrative

    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", _world)
    monkeypatch.setattr(
        "ming_sim.month_chain.run_gazette_text",
        lambda *_a, **_k: ("邸报", narrative),
    )
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment",
        lambda *_a, **_k: {"effects": {}},
    )
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    # #1745：复用单一 agent 边界夹具（不整换 run_settlement_attendant_message）。
    from tests.section_rejection_helpers import install_settlement_attendant_agent_stub
    install_settlement_attendant_agent_stub(monkeypatch, decree_mod)
    if skip_fixed_flows:
        monkeypatch.setattr(decree_mod, "apply_fixed_period_flows", lambda *_a, **_k: None)

    # #1843 reopen：旧 settle_with_delta / relation_brew_runner 已删；月链机械尾自带酿制。
    if source_spy is not None:
        # 新月链不经 settle_with_delta；source 由 chain 入口写入 resolve_context。
        pass

    return simulator_calls


def settle_effects(
    state,
    db,
    extracted,
    *,
    before_turn=None,
    content=None,
    registry=None,
    source=None,
    dossier_verdicts=None,
    dossier_rescript_actions=None,
    **_ignored,
):
    """Domain-test seam after settle_with_delta retirement (#1843 reopen).

    Applies one effects envelope through declaration_dispatch (player month-chain
    apply path, including #670/#651 post-apply hooks), then runs the month-drift
    hooks the new chain owns and advances the turn. Full world/gazette/4a are not
    run — use canned run_player_month_chain for those.
    """
    from ming_sim.applier import Provenance, atomic
    from ming_sim.declaration_dispatch import dispatch_declaration
    from ming_sim.exceptions import SettlementAbort
    from ming_sim.models import TurnPhase

    if before_turn is None:
        before_turn = int(state.turn)
    if source is None:
        source = Provenance.player_decree
    try:
        with atomic(db):
            if dossier_verdicts:
                db.apply_dossier_verdicts(
                    state, dossier_verdicts, content=content, registry=None,
                )
            if dossier_rescript_actions:
                for action in dossier_rescript_actions:
                    db.apply_dossier_promulgation(
                        state,
                        int(action["dossier_id"]),
                        str(action["decision"]),
                        content=content,
                        registry=None,
                    )
        if extracted:
            dispatch_declaration(
                db, state, {"effects": extracted},
                source=source,
            )
        else:
            # 空 delta 旧核仍走 apply_score_extraction（含回流等 always-on 步）。
            from ming_sim.issues import apply_score_extraction
            with atomic(db):
                applied = apply_score_extraction(
                    db, state, {}, content=content, registry=registry,
                )
                from ming_sim.audience_night import settle_applied_arrived_summons
                from ming_sim.covert_levy import (
                    settle_exposure_from_canonical_actions,
                    write_exposure_todos,
                )
                settle_applied_arrived_summons(db, applied)
                write_exposure_todos(db, state, applied)
                settle_exposure_from_canonical_actions(db, state, applied)
        from ming_sim.issues import apply_issue_inertia_and_ongoing, clear_gated_legacies
        from ming_sim.audience_night import retire_unsettled_summons_for_inactive
        from ming_sim.covert_levy import settle_exposure_from_canonical_actions
        from ming_sim.due_review import apply_pending_due_reviews
        from ming_sim.staged_commitment import write_due_staged_commitment_todos
        from ming_sim.breach_plea import expire_breach_pleas_on_due, scan_and_write_breach_pleas
        from ming_sim.covert_progress import settle_due_secret_orders
        from ming_sim.urge_lever import consume_pending_urge_audience_todos

        with atomic(db):
            retire_unsettled_summons_for_inactive(db)
            settle_exposure_from_canonical_actions(db, state, {})
            apply_issue_inertia_and_ongoing(db, state)
            db.recompute_all_faction_leverage()
            clear_gated_legacies(db, state)
            apply_pending_due_reviews(db, state, commit=False)
            settle_due_secret_orders(db, state, commit=False)
            db.release_held_audience_knowledge(commit=False)
            expire_breach_pleas_on_due(db, state, commit=False)
            consume_pending_urge_audience_todos(db, state, commit=False)
            write_due_staged_commitment_todos(db, state, commit=False)
            scan_and_write_breach_pleas(db, state, commit=False)
            db.mark_directives_issued(state)
            state.next_period()
            state.turn_phase = TurnPhase.ISSUED.value
            db.save_state(state)
            db.clear_month_open_snapshot(before_turn)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        # Match old settle_with_delta failure shape for domain tests that pin abort.
        raise SettlementAbort(str(exc), turn=int(before_turn), stage="settle_effects") from exc
    return ""
