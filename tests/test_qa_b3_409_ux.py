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
from ming_sim.models import TurnPhase
from concurrent.futures import ThreadPoolExecutor
"""#1274 QA A-新3：409/超时 UX 族（#1301/#1306/#1312/#1319(a)/#1322）。

保留 authority 投影权限与 resolve 锁前准入负向；
ADR 0036/0006 机制零动。
"""





# ── #1301 玩家面 409 去裸 night_id ──────────────────────────────────────────


# ── #1306 FRONT_HALF_DONE 分相位文案 ────────────────────────────────────────


# ── #1319(a) authority 停用 notes 别名 ──────────────────────────────────────

def test_directive_payload_authority_not_notes_alias():
    """#1319(a)：notes 备注不得投影成 authority；无真 authority 则空串。"""
    game = web_app.WebGame.__new__(web_app.WebGame)
    row = dict(
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
    message = payload["message"] if isinstance(payload, dict) else str(payload)
    assert game.session._submit_called is False
    assert game.actions == []
