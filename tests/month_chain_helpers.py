"""Light GameSession and canned external model seams for real player-month tests."""

from __future__ import annotations

from typing import Optional

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
    session._write_gate = get_session_write_queue(session).write_gate
    session.auto_save = lambda *a, **k: None
    bind_forecast_owner(session)
    from tests.conftest import note_queue_until_game_teardown

    note_queue_until_game_teardown(db, get_session_write_queue(session))
    return session


def canned_full_settlement(
    monkeypatch,
    *,
    narrative: str = "本月边情邸报：辽饷催征，流寇未息。",
    simulator_calls: Optional[list] = None,
    skip_fixed_flows: bool = False,
) -> list:
    """Replace only external LLM seams; keep production settlement spine."""
    simulator_calls = simulator_calls if simulator_calls is not None else []

    # #658：真实 ensure 成案后颁布判官亦为外部 LLM 缝——canned 默认全顺颁。
    def _promulgate(dossiers, *_a, **_k):
        return [
            {"dossier_id": int(row["id"]), "decision": "promulgated"}
            for row in dossiers
        ]

    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", _promulgate)

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
    if skip_fixed_flows:
        monkeypatch.setattr(decree_mod, "apply_fixed_period_flows", lambda *_a, **_k: None)

    return simulator_calls
