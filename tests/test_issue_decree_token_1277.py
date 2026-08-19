"""#1277 — issue/issue-stream 可选 expected_turn 防双发吃月（同 #1351 口径）。

接缝：
1. IssueDecreeRequest 可选 expected_turn（缺省=兼容现状）
2. 获锁后、resolve_turn 前：game.state.turn 不匹配 → 人话 409 + 当前 turn
3. 同令牌连发两次 → 第二次 409，月份只进一格
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim.decree import ResolveResult
from ming_sim.models import TurnPhase
from ming_sim.session import GameSession


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
        _write_gate=threading.Lock(),
    )

    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])
    return runtime


def _body(expected_turn: int | None, *, cheat: str = ""):
    return web_app.IssueDecreeRequest(cheat=cheat, expected_turn=expected_turn)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_double_issue_same_token_second_is_409_turn_plus_one(game, monkeypatch):
    """同 expected_turn 连发两次：第二次 409，月份只进一格；resolve 不二次执行。"""
    db, state, content = game
    assert state.turn_phase == TurnPhase.SUMMONING.value
    start = int(state.turn)
    runtime = _web_runtime(db, state, content, monkeypatch=monkeypatch)

    calls = {"n": 0}

    def _fake_resolve(**_k):
        calls["n"] += 1
        # 模拟 resolve_turn 成功推进一格（与生产同向副作用）。
        state.turn = start + 1
        state.turn_phase = TurnPhase.SUMMONING.value
        db.save_state(state)
        runtime.session.last_decree = "诏曰测试"
        return ResolveResult(awaiting=False, report="邸报测")

    runtime.session.resolve_turn = _fake_resolve

    first = web_app.api_issue_decree(_body(start))
    assert first.get("report") == "邸报测"
    assert int(state.turn) == start + 1
    assert calls["n"] == 1

    with pytest.raises(HTTPException) as ei:
        web_app.api_issue_decree(_body(start))

    assert ei.value.status_code == 409
    detail = ei.value.detail
    assert isinstance(detail, dict)
    assert int(detail["turn"]) == start + 1
    assert str(detail.get("message") or "")
    assert "令牌" in str(detail.get("message") or "")
    assert int(state.turn) == start + 1  # 未再推进
    assert calls["n"] == 1  # resolve 未二次执行
