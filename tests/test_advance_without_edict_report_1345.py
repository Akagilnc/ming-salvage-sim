"""#1345/#1382 A2 → #1274 QA J-1 改写 → #1382 last_report 耐久投影。

原钉：快路 advance_without_edict 落正式月档（save_turn_report）。
#1274 owner B-2：快路已废；无旨月走完整结算链，月档由 settle_with_delta 正常链落
（DRY，禁两条结算路）。

#1382 大理寺：`last_report` 不得靠 session 瞬态；状态口按 state.turn-1 读
turn_reports 原文。本文件从真实无旨 HTTP 入口证明：结算响应、随后 state
重载、history/turn/{closed_turn} 三者同份已落库原文。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
import web_app
from ming_sim.session import GameSession


def _canned(monkeypatch, narrative="本月退朝未下正式圣旨，边事自演。"):
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (narrative, k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
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
    """轻壳 WebGame：真实 state_payload / last_report 投影；refresh 对齐生产 begin_turn 清空瞬态。"""
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

    def _refresh_turn():
        # 生产 refresh_turn → begin_turn：清空 last_decree 等瞬态。
        # 轻壳不跑完整 begin_turn（registry/LLM）；只复现会吃掉旧 last_report 的清空面。
        session.last_decree = ""
        session.previous_summary = db.previous_turn_summary(session.state) or ""

    runtime.refresh_turn = _refresh_turn

    @contextlib.contextmanager
    def unlocked(_game):
        yield

    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_serialized_web_write", unlocked)
    return runtime


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_full_chain_writes_turn_report_and_public_gazette(game, monkeypatch):
    """无旨完整结算后：closed turn 有正式 turn_report + 邸报公共知识事件。"""
    db, state, content = game
    closed_turn = int(state.turn)
    narrative = "本月退朝未下正式圣旨，边事自演。"
    _canned(monkeypatch, narrative)

    result = _session(db, state, content).advance_without_decree()
    assert result is not None and result.awaiting is False
    assert int(state.turn) == closed_turn + 1

    report = db.get_turn_report(closed_turn)
    assert report is not None
    assert "边事自演" in report or "退朝未下正式圣旨" in report

    archives = db.list_monthly_archives()
    month = next((row for row in archives if int(row["turn"]) == closed_turn), None)
    assert month is not None
    assert month["has_report"] is True

    row = db.conn.execute(
        """
        SELECT title, body, source_id FROM character_knowledge_events
        WHERE character_name='' AND turn=? AND title=?
        ORDER BY id DESC LIMIT 1
        """,
        (closed_turn, "邸报"),
    ).fetchone()
    assert row is not None
    assert str(row["source_id"] or "") == f"turn_report:{closed_turn}:public"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_previous_turn_summary_hits_narrative(game, monkeypatch):
    """推进后 previous_turn_summary 命中 simulator 叙事。"""
    db, state, content = game
    narrative = "本月退朝未下正式圣旨，诸事仍待来月处置——世界自演。"
    _canned(monkeypatch, narrative)
    _session(db, state, content).advance_without_decree()

    summary = db.previous_turn_summary(state)
    assert "退朝未下正式圣旨" in summary or "世界自演" in summary


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_http_last_report_matches_durable_and_history(game, monkeypatch):
    """#1382：无旨 HTTP 结算响应 / state 重载 / history 三者同 turn_reports 原文。"""
    db, state, content = game
    closed_turn = int(state.turn)
    narrative = "无旨月邸报原文钉测·边事自演。"
    _canned(monkeypatch, narrative)
    runtime = _web_runtime(db, state, content, monkeypatch=monkeypatch)

    body = web_app.AdvanceWithoutEdictRequest(expected_turn=closed_turn)
    response = web_app.api_advance_without_edict(body)

    durable = db.get_turn_report(closed_turn)
    assert durable  # 结构化：闭月有落库行；正文同值由下方三方相等钉，不盯措辞
    assert int(state.turn) == closed_turn + 1
    assert response.get("awaiting_decision") is False

    # 1) 结算响应内嵌 state.last_report ≡ 落库原文
    assert response["state"]["last_report"] == durable

    # 2) 随后 state 刷新/重载仍投影同一原文（refresh_turn 已跑过）
    reloaded = web_app.WebGame.state_payload(runtime)
    assert reloaded["last_report"] == durable
    # api_state 同缝
    assert asyncio.run(web_app.api_state())["last_report"] == durable

    # 3) history/turn/{closed_turn} 同份原文
    history = asyncio.run(web_app.api_history_turn(closed_turn))
    assert history["exists"] is True
    assert history["report"] == durable


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_history_turn_api_exists_true(game, monkeypatch):
    """Web 史册单月读口：exists:true 且 report 为正式档。"""
    db, state, content = game
    closed_turn = int(state.turn)
    narrative = "史册无旨月邸报。"
    _canned(monkeypatch, narrative)
    _session(db, state, content).advance_without_decree()

    runtime = type("R", (), {"db": db, "state": state})()
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    payload = asyncio.run(web_app.api_history_turn(closed_turn))
    assert payload["exists"] is True
    assert payload["report"]
    assert "史册无旨月" in payload["report"] or "邸报" in payload["report"]


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_double_token_only_one_month_archive(game, monkeypatch):
    """A1×A2 联验：同令牌连发两次 → 第二次 409，史册只多一档月报。"""
    db, state, content = game
    start = int(state.turn)
    before_archives = len(db.list_monthly_archives())
    _canned(monkeypatch, "令牌联验无旨月邸报。")
    _web_runtime(db, state, content, monkeypatch=monkeypatch)

    body = web_app.AdvanceWithoutEdictRequest(expected_turn=start)
    web_app.api_advance_without_edict(body)
    with pytest.raises(HTTPException) as ei:
        web_app.api_advance_without_edict(body)
    assert ei.value.status_code == 409
    assert int(state.turn) == start + 1
    assert len(db.list_monthly_archives()) == before_archives + 1
    assert db.get_turn_report(start)


def test_advance_without_edict_shell_absent():
    """#1274 r1：decree.advance_without_edict 空壳已删（prep 归 resolve_turn）。"""
    import inspect

    import ming_sim.decree as decree_mod

    assert not hasattr(decree_mod, "advance_without_edict")
    assert "def advance_without_edict" not in inspect.getsource(decree_mod)
