"""#1274 QA A-新3：409/超时 UX 族（#1301/#1306/#1312/#1319(a)/#1322）。

刀口锁状态码、结构化 detail、相位分叉与 resolve 锁前预检；
ADR 0036/0006 机制零动。
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim import audience_night as an
from ming_sim.session_write_queue import ClassifiedWriteGate
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
    assert msg
    assert ei.value.code == "night_closing"
    assert ei.value.detail == {"night_id": 42, "what": "召对"}

    with pytest.raises(an.AudienceNightError) as other:
        an.assert_night_accepts_player_input(object(), what="阅折")
    assert other.value.code == "night_closing"
    assert other.value.detail == {"night_id": 42, "what": "阅折"}


# ── #1306 FRONT_HALF_DONE 分相位文案 ────────────────────────────────────────

def _front_half_detail(phase: str) -> str:
    game = SimpleNamespace(
        state=SimpleNamespace(turn_phase=phase),
        _write_gate=ClassifiedWriteGate(),
    )
    with pytest.raises(HTTPException) as ei:
        with web_app._serialized_web_write(game):
            pass
    assert ei.value.status_code == 409
    detail = str(ei.value.detail)
    assert detail
    return detail


def test_serialized_web_write_phase_messages_cover_front_half_done():
    """#1306 全 FRONT_HALF_DONE 相位均 409，详情只按 awaiting / 其余两支分叉。"""
    awaiting = _front_half_detail(TurnPhase.AWAITING_DECISION.value)
    other = _front_half_detail(TurnPhase.SETTLING.value)
    assert awaiting != other
    for phase in FRONT_HALF_DONE_PHASES:
        detail = _front_half_detail(phase)
        if phase == TurnPhase.AWAITING_DECISION.value:
            assert detail == awaiting
        else:
            assert detail == other


# ── #1319(a) authority 停用 notes 别名 ──────────────────────────────────────

class _Row(dict):
    def keys(self):
        return super().keys()


def test_directive_payload_authority_not_notes_alias():
    """#1319(a)：notes 备注不得投影成 authority；无真 authority 则空串。"""
    game = web_app.WebGame.__new__(web_app.WebGame)
    row = _Row(
        id=9,
        event_id="",
        event_title="",
        actor="袁崇焕",
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

    def await_translations_before_month(self, after_drain=None):
        # #1842：过月入口在 auto_close 前闸外 join 转译；桩无在飞 Future。
        if after_drain is not None:
            after_drain()

    def submit_hitl_choices(self, *_a, write_gate=None, **_k):
        self._submit_called = True
        raise AssertionError("wrong-phase must not reach submit_hitl_choices")


class _ResolveGame:
    def __init__(self, phase: str, gate: ClassifiedWriteGate):
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
    gate = ClassifiedWriteGate()
    gate.acquire()  # 模拟结算 worker 持锁；若预检在锁后，本测会阻塞至超时
    game = _ResolveGame(TurnPhase.SETTLING.value, gate)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    try:
        # gate held: precheck must finish without acquiring it (hang → CI final line)
        events = asyncio.run(_consume_resolve_sse())
    finally:
        gate.release()

    assert events, "expected at least one SSE event"
    event, payload = events[-1]
    assert event == "error"
    assert isinstance(payload, dict) and payload.get("message")
    assert game.session._submit_called is False
    assert game.actions == []


def test_resolve_decisions_stream_awaiting_still_submits_under_lock(monkeypatch):
    """#1322：awaiting 相位仍经 submit_hitl 在 write_gate 内提交（权威复查保留）。"""
    gate = ClassifiedWriteGate()
    game = _ResolveGame(TurnPhase.AWAITING_DECISION.value, gate)
    submitted = {"ok": False}

    def _submit_hitl(choices, *, write_gate, cheat_directive=""):
        with write_gate:
            assert gate.locked(), "submit must run while write gate held"
            game.actions.append("submit")
            submitted["ok"] = True
            return "邸报：已裁。"

    game.session.submit_hitl_choices = _submit_hitl  # type: ignore[method-assign]
    game.session.last_decree = "诏曰：发帑。"
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    events = asyncio.run(_consume_resolve_sse())
    assert submitted["ok"] is True
    kinds = [ev for ev, _ in events]
    assert "stage" not in kinds
    assert kinds[-1] == "done"
    payload = events[-1][1]
    assert payload["report"] == "邸报：已裁。"


def test_load_save_409_during_resolve_body_keeps_old_session_tail(monkeypatch):
    """#1702: load during resolve post-submit pre-tail window → 409; old session tail intact.

    Real API entry + Event handshake after submit returns ISSUED (gate free, inflight>0)
    and before tail write grabs the gate. Externally: load 409, end_turn/refresh on the
    original session. Does not lock gate.locked / entry_lock internals.
    """
    gate = ClassifiedWriteGate()
    game = _ResolveGame(TurnPhase.AWAITING_DECISION.value, gate)
    old_session = game.session
    replacements: list[str] = []
    tail_sessions: list[object] = []
    body_ready = threading.Event()
    release_body = threading.Event()
    resolve_done = threading.Event()

    def _submit_hitl(choices, *, write_gate, cheat_directive=""):
        with write_gate:
            game.actions.append("submit")
            # Completed settlement advances the turn while still under the gate.
            game.state.turn_phase = TurnPhase.ISSUED.value
            game.state.turn += 1
        return "邸报：已裁。"

    def _end_turn():
        # #1853 J5：原握手挂在已删的 failed 载荷 helper；改挂尾写 end_turn（仍在短持 gate 内）。
        body_ready.set()
        release_body.wait()
        game.actions.append("end_turn")
        tail_sessions.append(game.session)

    game.session.submit_hitl_choices = _submit_hitl  # type: ignore[method-assign]
    game.session.end_turn = _end_turn  # type: ignore[method-assign]
    game.session.last_decree = "诏曰：发帑。"
    game.load_save = lambda name: replacements.append(name)  # type: ignore[attr-defined]
    game.state_payload = lambda: {"ok": True}  # type: ignore[attr-defined]

    monkeypatch.setattr(web_app, "get_game", lambda: game)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)

    def _run_resolve():
        try:
            asyncio.run(_consume_resolve_sse())
        finally:
            resolve_done.set()

    t_resolve = threading.Thread(target=_run_resolve, daemon=True)
    t_resolve.start()
    body_ready.wait()

    try:
        with pytest.raises(HTTPException) as ei:
            asyncio.run(web_app.api_load_save("存档"))
        assert ei.value.status_code == 409
        assert replacements == []
        assert game.session is old_session
    finally:
        release_body.set()
        resolve_done.wait()
        t_resolve.join()

    assert game.actions == ["submit", "end_turn", "refresh"]
    assert tail_sessions == [old_session]
