"""#1351/#1368 A1 — advance_without_edict 可选 expected_turn 防双发吃月。

接缝：
1. POST /api/decree/advance_without_edict 请求体可选 expected_turn（缺省=兼容现状）
2. _settlement_period_entry 获锁后、推进副作用前：game.state.turn 不匹配 → 409
   （detail 人话 + 当前 turn；样板 finally 清展示态；不开新锁）
3. 同令牌连发两次 → 第二次 409，月份只进一格
4. 不带令牌 → 行为同今（可连进两格）

#1274：端点改走 session.advance_without_decree 完整结算；夹具需 canned LLM。
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
import web_app
from ming_sim.models import TurnPhase
from ming_sim.session import GameSession


def _canned(monkeypatch):
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("令牌测无旨月邸报。", k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


def _session(db, state, content):
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
    session.last_report = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session.auto_save = lambda *a, **k: None
    return session


def _web_runtime(db, state, content, *, monkeypatch):
    session = _session(db, state, content)
    runtime = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        directive_rows=lambda: [],
        refresh_turn=lambda: None,
        state_payload=lambda: {
            "turn": {
                "turn": int(state.turn),
                "year": int(state.year),
                "period": int(state.period),
                "phase": state.turn_phase,
            }
        },
        _write_gate=__import__("threading").Lock(),
    )

    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    return runtime


def _body(expected_turn: int | None):
    return web_app.AdvanceWithoutEdictRequest(expected_turn=expected_turn)






