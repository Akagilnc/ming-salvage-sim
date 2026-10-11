"""Shared test fixtures for rescript_draft row planting (explicit idx/event_id only)."""

from __future__ import annotations

import json


def sql_rescript_draft(
    db,
    turn,
    *,
    idx,
    event_id,
    title,
    context="",
    options=None,
    actor_name="",
    actor_office="",
    actor_faction="",
):
    """Single-row SQL plant: idx and event_id required; no retired write-path rules."""
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, event_id, title, context, options_json, choice_json, "
        " status, kind, actor_name, actor_office, actor_faction) "
        "VALUES (?, ?, ?, ?, ?, ?, '', 'pending', 'rescript_draft', ?, ?, ?)",
        (
            int(turn),
            int(idx),
            str(event_id),
            str(title),
            str(context),
            json.dumps(options or [], ensure_ascii=False),
            str(actor_name),
            str(actor_office),
            str(actor_faction),
        ),
    )


def _real_submit_session(monkeypatch, db, state, content, *, candidate_ids=()):
    """真 GameSession 壳 + 真 submit_hitl_choices；只中和外部 LLM 缝。

    本回合暂存上下文照真实 phase1 形状落一份（phase2 要读它续跑）。``candidate_ids``
    给本回合候选快照：核内 ``bind_decisions_to_candidate_events`` 只在快照非空时按
    快照重绑 event_id，故请旨等非事件身份那几条不传（它们的身份不是 events 表事件）。
    """
    from ming_sim.models import TurnPhase
    from tests.month_chain_helpers import make_light_session

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    simulator_payload = {
        "candidate_events": [{"id": cid, "title": ""} for cid in candidate_ids],
        "transit_semantics": [],
    } if candidate_ids else None
    db.save_resolve_context(
        int(state.turn), "测试诏书", {"simulator_payload": simulator_payload},
    )
    db.save_turn_report(state, "邸报已成")
    session = make_light_session(db, state, content)
    # 最外层 LLM 缝：世界段推演与月链转译。中和它们，核内编排与领域写全走真逻辑。
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    return session
