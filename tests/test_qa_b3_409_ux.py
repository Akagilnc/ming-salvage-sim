"""#1274 QA A-新3：409/超时 UX 族（#1301/#1306/#1312/#1319(a)/#1322）。

刀口只锁玩家面文案、相位分文、authority 投影与 resolve 锁前预检；
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

def test_closing_night_rejects_chat_before_any_write(game):
    from tests.test_chat_stream_failpaths_393 import _base_runtime

    db, state, _content = game
    night = an.open_night(db, state)
    db.conn.execute(
        "UPDATE audience_nights SET status=? WHERE id=?",
        (an.NIGHT_STATUS_CLOSING, night["id"]),
    )
    db.conn.commit()
    before = an.get_night(db, night["id"])
    counts = {
        table: db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("chat_turns", "chat_messages")
    }
    runtime, _minister = _base_runtime(db)
    events = list(runtime.chat_stream(an.SCENE_CHAT_SPEAKER, "辽东军情如何？"))
    assert [(event["type"], event.get("code")) for event in events] == [
        ("error", "night_closing"),
    ]
    assert an.get_night(db, night["id"]) == before
    for table, count in counts.items():
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count


def test_favorite_write_rejected_in_front_half_done_phases(game, monkeypatch):
    db, state, _content = game
    name = "毕自严"
    live = SimpleNamespace(
        state=state, db=db, favorites={name},
        _write_gate=ClassifiedWriteGate(),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: live)
    original_phase = state.turn_phase
    state.turn_phase = TurnPhase.SUMMONING.value
    result = asyncio.run(web_app.api_remove_favorite(name))
    assert result == {"favorites": []}
    assert json.loads(db.kv_get("favorites")) == []
    live.favorites.add(name)
    db.kv_set("favorites", json.dumps([name]))
    try:
        for phase in FRONT_HALF_DONE_PHASES:
            state.turn_phase = phase
            with pytest.raises(HTTPException) as ei:
                asyncio.run(web_app.api_remove_favorite(name))
            assert ei.value.status_code == 409
            assert live.favorites == {name}
            assert json.loads(db.kv_get("favorites")) == [name]
    finally:
        state.turn_phase = original_phase


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
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())

    try:
        # gate held: precheck must finish without acquiring it (hang → CI final line)
        events = asyncio.run(_consume_resolve_sse())
    finally:
        gate.release()

    assert events, "expected at least one SSE event"
    event, payload = events[-1]
    assert event == "error"
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
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(
        web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: []
    )

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

    def _failures_after_submit(*_a, **_k):
        # web_app resolve stream calls this after submit returns, before tail write.
        body_ready.set()
        release_body.wait()
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
