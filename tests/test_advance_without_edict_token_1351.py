"""#1351/#1368 A1 — advance_without_edict 可选 expected_turn 防双发吃月。

接缝：
1. POST /api/decree/advance_without_edict 请求体可选 expected_turn（缺省=兼容现状）
2. _settlement_period_entry 获锁后、推进副作用前：game.state.turn 不匹配 → 409
   （detail 人话 + 当前 turn；样板 finally 清展示态；不开新锁）
3. 同令牌连发两次 → 第二次 409，月份只进一格
4. 不带令牌 → 行为同今（可连进两格）
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim.models import TurnPhase


def _web_runtime(db, state, content, *, monkeypatch):
    session = SimpleNamespace(
        registry=None,
        llm_config=None,
        _scene_registry=None,
        resolve_turn=lambda **_k: (_ for _ in ()).throw(
            AssertionError("本片快路不应落入 resolve_turn")
        ),
    )
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

    @contextlib.contextmanager
    def _real_serialized(game):
        # 保留非阻塞抢锁语义，走生产 _serialized_web_write。
        with web_app._serialized_web_write(game):
            yield

    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    # 不替换 write_cm 工厂本身：entry 内仍用 _serialized_web_write。
    return runtime


def _body(expected_turn: int | None):
    return web_app.AdvanceWithoutEdictRequest(expected_turn=expected_turn)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_double_advance_same_token_second_is_409_turn_plus_one(game, monkeypatch):
    """同 expected_turn 连发两次：第二次 409，月份只进一格。"""
    db, state, content = game
    assert state.turn_phase == TurnPhase.SUMMONING.value
    start = int(state.turn)
    _web_runtime(db, state, content, monkeypatch=monkeypatch)

    first = web_app.api_advance_without_edict(_body(start))
    assert int(first["state"]["turn"]["turn"]) == start + 1
    assert int(state.turn) == start + 1

    with pytest.raises(HTTPException) as ei:
        web_app.api_advance_without_edict(_body(start))

    assert ei.value.status_code == 409
    detail = ei.value.detail
    assert isinstance(detail, dict)
    assert int(detail["turn"]) == start + 1
    assert str(detail.get("message") or "")
    assert int(state.turn) == start + 1  # 未再推进


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_advance_without_token_keeps_legacy_double_advance(game, monkeypatch):
    """不带令牌：行为同今——连发两次可各进一格。"""
    db, state, content = game
    start = int(state.turn)
    _web_runtime(db, state, content, monkeypatch=monkeypatch)

    web_app.api_advance_without_edict()
    assert int(state.turn) == start + 1
    web_app.api_advance_without_edict()
    assert int(state.turn) == start + 2


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_mismatched_token_409_clears_display_snapshot(game, monkeypatch):
    """令牌不匹配 409 走样板 finally：展示态快照被清（非成功保留）。"""
    db, state, content = game
    start = int(state.turn)
    _web_runtime(db, state, content, monkeypatch=monkeypatch)

    # 先成功推进一格，制造 turn 漂移。
    web_app.api_advance_without_edict(_body(start))
    assert int(state.turn) == start + 1

    with pytest.raises(HTTPException) as ei:
        web_app.api_advance_without_edict(_body(start))
    assert ei.value.status_code == 409

    # 失败路径应出核账展示态（无残留月初快照）。
    assert db.get_month_open_snapshot(int(state.turn)) is None
