"""#1274 QA A-新3：409/超时 UX 族（#1301/#1306/#1312/#1319(a)/#1322）。

刀口只锁玩家面文案、相位分文、authority 投影与 resolve 锁前预检；
ADR 0036/0006 机制零动。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim import audience_night as an
from ming_sim.models import FRONT_HALF_DONE_PHASES, TurnPhase


# ── #1301 玩家面 409 去裸 night_id ──────────────────────────────────────────

class _ClosingNightDB:
    def __init__(self, night_id: int = 7):
        self._night = {
            "id": night_id,
            "status": an.NIGHT_STATUS_CLOSING,
            "close_commit_cursor": 0,
        }

    def conn_execute(self, *_a, **_k):
        raise AssertionError("assert_night_accepts_player_input must not hit SQL here")


def test_closing_player_message_is_diegetic_without_bare_night_id(monkeypatch):
    """#1301：玩家面文案不得拼接裸 night_id；结构化 detail 仍带 night_id。"""
    night = {
        "id": 42,
        "status": an.NIGHT_STATUS_CLOSING,
        "close_commit_cursor": 0,
    }
    monkeypatch.setattr(an, "get_open_night", lambda _db: night)
    monkeypatch.setattr(an, "get_night", lambda _db, nid: night if int(nid) == 42 else None)

    with pytest.raises(an.AudienceNightError) as ei:
        an.assert_night_accepts_player_input(object(), what="召对")

    msg = str(ei.value)
    assert "收夜中" in msg
    assert "召对" in msg
    assert "42" not in msg
    assert ":42" not in msg.replace(" ", "")
    assert ei.value.code == "night_closing"
    assert ei.value.detail == {"night_id": 42, "what": "召对"}


# ── #1306 FRONT_HALF_DONE 分相位文案 ────────────────────────────────────────

def test_serialized_web_write_awaiting_decision_says_waiting_for_rescript():
    """#1306：awaiting_decision 报「等待批红」，不得报「月末结算进行中」。"""
    game = SimpleNamespace(
        state=SimpleNamespace(turn_phase=TurnPhase.AWAITING_DECISION.value),
        _write_gate=threading.Lock(),
    )
    with pytest.raises(HTTPException) as ei:
        with web_app._serialized_web_write(game):
            pass
    assert ei.value.status_code == 409
    detail = str(ei.value.detail)
    assert "等待批红" in detail
    assert "月末结算进行中" not in detail


def test_serialized_web_write_settling_keeps_settlement_in_progress_copy():
    """#1306：settling 仍报月末结算进行中。"""
    game = SimpleNamespace(
        state=SimpleNamespace(turn_phase=TurnPhase.SETTLING.value),
        _write_gate=threading.Lock(),
    )
    with pytest.raises(HTTPException) as ei:
        with web_app._serialized_web_write(game):
            pass
    assert ei.value.status_code == 409
    assert "月末结算进行中" in str(ei.value.detail)


def test_serialized_web_write_phase_messages_cover_front_half_done():
    """#1306 全 FRONT_HALF_DONE 相位均 409，且文案按相位分叉。"""
    for phase in FRONT_HALF_DONE_PHASES:
        game = SimpleNamespace(
            state=SimpleNamespace(turn_phase=phase),
            _write_gate=threading.Lock(),
        )
        with pytest.raises(HTTPException) as ei:
            with web_app._serialized_web_write(game):
                pass
        assert ei.value.status_code == 409
        detail = str(ei.value.detail)
        if phase == TurnPhase.AWAITING_DECISION.value:
            assert "等待批红" in detail
        else:
            assert "月末结算进行中" in detail


# ── #1319(a) authority 停用 notes 别名 ──────────────────────────────────────

class _Row(dict):
    def keys(self):
        return super().keys()


def test_directive_payload_authority_not_notes_alias(monkeypatch):
    """#1319(a)：notes 备注不得投影成 authority；无真 authority 则空串。"""
    monkeypatch.setattr(web_app, "skill_display_name", lambda _sid: "")
    game = web_app.WebGame.__new__(web_app.WebGame)
    row = _Row(
        id=9,
        event_id="",
        event_title="",
        actor="袁崇焕",
        skill_id="",
        text="发帑辽东",
        source="manual",
        status="draft",
        notes="家赀约十万两",
    )
    payload = web_app.WebGame.directive_payload(game, row)
    assert payload["notes"] == "家赀约十万两"
    assert payload["authority"] == ""
    assert payload["authority"] != payload["notes"]


# ── #1322 resolve stream 相位预检在抢锁前 ───────────────────────────────────

class _PhaseSession:
    def __init__(self, phase: str):
        self.state = SimpleNamespace(turn_phase=phase, turn=3, ended=False)
        self.last_decree = ""
        self._submit_called = False
        self._gate_held_during_precheck = False

    def current_phase(self):
        return TurnPhase(self.state.turn_phase)

    def submit_hitl_choices(self, *_a, write_gate=None, **_k):
        self._submit_called = True
        raise AssertionError("wrong-phase must not reach submit_hitl_choices")


class _ResolveGame:
    def __init__(self, phase: str, gate: threading.Lock):
        self.state = SimpleNamespace(turn=3, ended=False, turn_phase=phase)
        self.session = _PhaseSession(phase)
        self.session.state = self.state
        self.db = SimpleNamespace(list_pending_actions=lambda *_a, **_k: [])
        self._write_gate = gate
        self.actions = []
        self.session.end_turn = lambda: self.actions.append("end_turn")

    def refresh_turn(self):
        self.actions.append("refresh")


async def _consume_resolve_sse() -> list[tuple[str, object]]:
    """Drain the whole SSE; return [(event, payload), ...] in order."""
    response = await web_app.api_resolve_decisions_stream(
        web_app.ResolveDecisionsRequest(choices=[{"label": "发帑"}])
    )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    serialized = "".join(chunks)
    events: list[tuple[str, object]] = []
    for block in serialized.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_name = ""
        data_raw = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                ev_name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_raw += line[len("data: "):]
        if not ev_name or not data_raw:
            continue
        events.append((ev_name, json.loads(data_raw)))
    return events


def test_resolve_decisions_stream_phase_precheck_before_lock(monkeypatch):
    """#1322：非 awaiting 相位在抢锁前快速失败；持锁者不被卡住；submit 不进。"""
    gate = threading.Lock()
    gate.acquire()  # 模拟结算 worker 持锁；若预检在锁后，本测会阻塞至超时
    game = _ResolveGame(TurnPhase.SETTLING.value, gate)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())

    started = time.monotonic()
    try:
        events = asyncio.run(
            asyncio.wait_for(_consume_resolve_sse(), timeout=2.0)
        )
    finally:
        gate.release()
    elapsed = time.monotonic() - started

    assert elapsed < 1.5, f"phase precheck must not block on held write gate ({elapsed:.2f}s)"
    assert events, "expected at least one SSE event"
    event, payload = events[-1]
    assert event == "error"
    message = payload["message"] if isinstance(payload, dict) else str(payload)
    assert "待裁" in message or "亲裁" in message
    assert game.session._submit_called is False
    assert game.actions == []


def test_resolve_decisions_stream_awaiting_still_submits_under_lock(monkeypatch):
    """#1322：awaiting 相位仍经 submit_hitl 在 write_gate 内提交（权威复查保留）。"""
    gate = threading.Lock()
    game = _ResolveGame(TurnPhase.AWAITING_DECISION.value, gate)
    submitted = {"ok": False}

    def _submit_hitl(choices, *, write_gate, on_event=None, cheat_directive=""):
        with write_gate:
            assert gate.locked(), "submit must run while write gate held"
            game.actions.append("submit")
            submitted["ok"] = True
            if on_event:
                on_event("stage", "数值推演结算")
            return "邸报：已裁。"

    game.session.submit_hitl_choices = _submit_hitl  # type: ignore[method-assign]
    game.session.last_decree = "诏曰：发帑。"
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(
        web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: []
    )

    events = asyncio.run(_consume_resolve_sse())
    assert submitted["ok"] is True
    assert game.actions == ["submit", "end_turn", "refresh"]
    kinds = [ev for ev, _ in events]
    assert "stage" in kinds
    assert kinds[-1] == "done"
    payload = events[-1][1]
    assert payload["report"] == "邸报：已裁。"


def test_load_save_409_during_resolve_body_keeps_old_session_tail(monkeypatch):
    """#1702: load during resolve post-submit pre-tail window → 409; old session tail intact.

    Real API entry + Event handshake after submit returns ISSUED (gate free, inflight>0)
    and before tail write grabs the gate. Externally: load 409, end_turn/refresh on the
    original session. Does not lock gate.locked / entry_lock internals.
    """
    gate = threading.Lock()
    game = _ResolveGame(TurnPhase.AWAITING_DECISION.value, gate)
    old_session = game.session
    replacements: list[str] = []
    tail_sessions: list[object] = []
    body_ready = threading.Event()
    release_body = threading.Event()
    resolve_done = threading.Event()

    def _submit_hitl(choices, *, write_gate, on_event=None, cheat_directive=""):
        with write_gate:
            game.actions.append("submit")
            if on_event:
                on_event("stage", "数值推演结算")
            # Production finish_rescript_phase2 sets ISSUED before returning under the gate.
            game.state.turn_phase = TurnPhase.ISSUED.value
        return "邸报：已裁。"

    def _failures_after_submit(*_a, **_k):
        # web_app resolve stream calls this after submit returns, before tail write.
        body_ready.set()
        assert release_body.wait(5.0), "test must release post-submit pre-tail window"
        return []

    def _end_turn():
        game.actions.append("end_turn")
        tail_sessions.append(game.session)

    game.session.submit_hitl_choices = _submit_hitl  # type: ignore[method-assign]
    game.session.end_turn = _end_turn  # type: ignore[method-assign]
    game.session.last_decree = "诏曰：发帑。"
    game.load_save = lambda name: replacements.append(name)  # type: ignore[attr-defined]
    game.state_payload = lambda: {"ok": True}  # type: ignore[attr-defined]

    monkeypatch.setattr(web_app, "get_game", lambda: game)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(
        web_app, "_new_secret_order_failure_payloads_for_turn", _failures_after_submit
    )
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)

    def _run_resolve():
        try:
            asyncio.run(_consume_resolve_sse())
        finally:
            resolve_done.set()

    t_resolve = threading.Thread(target=_run_resolve, daemon=True)
    t_resolve.start()
    assert body_ready.wait(5.0), "resolve must enter post-submit pre-tail window"

    with pytest.raises(HTTPException) as ei:
        asyncio.run(web_app.api_load_save("存档"))
    assert ei.value.status_code == 409
    assert replacements == []
    assert game.session is old_session

    release_body.set()
    assert resolve_done.wait(5.0), "resolve must finish"
    t_resolve.join(2.0)

    assert game.actions == ["submit", "end_turn", "refresh"]
    assert tail_sessions == [old_session]


