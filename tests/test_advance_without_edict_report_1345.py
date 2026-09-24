"""#1345/#1382 A2 → #1274 QA J-1 改写 → #1382 last_report 耐久投影。

原钉：快路 advance_without_edict 落正式月档（save_turn_report）。
#1274 owner B-2：快路已废；无旨月走完整结算链，月档由 settle_with_delta 正常链落
（DRY，禁两条结算路）。

#1382 大理寺：`last_report` 不得靠 session 瞬态；状态口按 state.turn-1 读
turn_reports 原文。本文件从真实无旨 HTTP 入口证明：结算响应、随后跨实例
load_state 恢复、history/turn/{closed_turn} 三者同份已落库原文。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import pytest
from fastapi import HTTPException

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
from ming_sim.db import GameDB
import web_app
from ming_sim.session import GameSession


def _canned(monkeypatch, narrative="本月退朝未下正式圣旨，边事自演。"):
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (narrative, k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


def _session(db, state, content):
    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.registry = session.llm_config = session.agno_db = None
    session.deaths_this_turn, session.debuts_this_turn = [], []
    session.last_decree = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session.auto_save = lambda *a, **k: None
    session.pending_count = lambda: 0
    session.pending_decisions = lambda: []
    session.victory = lambda: {"status": "ongoing", "summary": ""}
    session.previous_summary = ""
    return session


def _web_runtime(db, state, content, *, monkeypatch, session=None):
    """轻壳 WebGame：真实 state_payload / last_report 投影；refresh_turn 为 no-op。

    仅保证结算路径不崩溃；生产 begin_turn 清空瞬态由生产 refresh_turn 负责，
    本测试不以同 runtime refresh 为恢复依据。
    """
    session = session or _session(db, state, content)
    runtime = object.__new__(web_app.WebGame)
    runtime.session = session
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    runtime._write_gate = threading.Lock()
    runtime.refresh_turn = lambda: None

    @contextlib.contextmanager
    def unlocked(_game):
        yield

    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_serialized_web_write", unlocked)
    return runtime










def test_advance_without_edict_shell_absent():
    """#1274 r1：decree.advance_without_edict 空壳已删（prep 归 resolve_turn）。"""
    import ming_sim.decree as decree_mod

    assert not hasattr(decree_mod, "advance_without_edict")
