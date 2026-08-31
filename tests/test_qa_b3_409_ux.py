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


# ── #1702 热替换 × settlement entry 共用临界区 ──────────────────────────────

class _HotReplaceGame:
    """轻壳：真实 _hot_replace_when_idle / resolve stream 接缝。"""

    def __init__(self, phase: str = TurnPhase.SUMMONING.value):
        self.state = SimpleNamespace(turn=3, ended=False, turn_phase=phase)
        self.session = SimpleNamespace(
            last_decree="诏曰：发帑。",
            state=self.state,
        )
        self.db = SimpleNamespace(list_pending_actions=lambda *_a, **_k: [])
        self._write_gate = threading.Lock()
        self._settlement_entry_lock = threading.Lock()
        self._settlement_entry_inflight = 0
        self.actions: list[str] = []
        self.replacements: list[str] = []
        self._session_token = object()

        def _end_turn():
            self.actions.append("end_turn")
            # 记录尾写时 session 身份，供交错窗断言
            self.actions.append(f"end_on:{id(self.session)}")

        self.session.end_turn = _end_turn  # type: ignore[method-assign]
        self.session.current_phase = lambda: TurnPhase(self.state.turn_phase)  # type: ignore[method-assign]

    def _runtime_write_gate(self):
        return self._write_gate

    def refresh_turn(self):
        self.actions.append("refresh")

    def load_save(self, name: str) -> None:
        self.replacements.append(name)
        # 热替换换新 session 身份
        self.session = SimpleNamespace(last_decree="", state=self.state)
        self._session_token = object()

    def state_payload(self):
        return {"ok": True, "session_id": id(self.session)}


def test_load_save_409_while_settlement_entry_inflight(monkeypatch):
    """#1702 在办窗：entry inflight>0 时 load → 409；session 身份不变；无 replace 副作用。"""
    game = _HotReplaceGame()
    old_session = game.session
    old_token = game._session_token
    web_app._begin_settlement_entry(game)
    assert web_app._settlement_entry_inflight(game) == 1
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(web_app.api_load_save("存档"))

    assert ei.value.status_code == 409
    assert game.replacements == []
    assert game.session is old_session
    assert game._session_token is old_token
    web_app._end_settlement_entry(game)
    assert web_app._settlement_entry_inflight(game) == 0


def test_load_and_resolve_tail_mutual_exclusion_gate_free_window(monkeypatch):
    """#1702 交错窗：resolve body 在办且 gate 空闲时 load 不得成功 replace 同时旧尾写。

    稳定结局：load 409 + 旧 session 尾写完整（end_turn/refresh 落在原 session）。
    修复前：gate-free 窗 load 可 replace，与旧尾写并发。
    """
    game = _HotReplaceGame(phase=TurnPhase.AWAITING_DECISION.value)
    old_session = game.session
    old_session_id = id(old_session)
    body_gate_free = threading.Event()
    release_body = threading.Event()
    resolve_done = threading.Event()
    load_result: dict = {}

    def _submit_hitl(choices, *, write_gate, on_event=None, cheat_directive=""):
        # 短持 gate 后释放——模拟 ①/③ 结束；join/尾前 gate 空闲、inflight 仍 >0
        with write_gate:
            game.actions.append("submit")
            if on_event:
                on_event("stage", "数值推演结算")
        assert not game._write_gate.locked(), "submit 短持后 gate 须释放（join 不整段持锁）"
        body_gate_free.set()
        assert release_body.wait(5.0), "测试须放行 resolve body"
        return "邸报：已裁。"

    game.session.submit_hitl_choices = _submit_hitl  # type: ignore[method-assign]
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(
        web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: []
    )
    # hold_write_for_body=False 路径会 barrier→auto_close；轻壳无真 db.conn → 跳过
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)

    def _run_resolve():
        try:
            asyncio.run(_consume_resolve_sse())
        finally:
            resolve_done.set()

    t_resolve = threading.Thread(target=_run_resolve, daemon=True)
    t_resolve.start()
    assert body_gate_free.wait(5.0), "resolve 须进入 gate-free body 窗"
    assert web_app._settlement_entry_inflight(game) >= 1
    assert not game._write_gate.locked()

    # 交错：body 在办、gate 空闲时打 load
    try:
        asyncio.run(web_app.api_load_save("存档"))
        load_result["ok"] = True
    except HTTPException as exc:
        load_result["status"] = exc.status_code
    except Exception as exc:  # noqa: BLE001
        load_result["err"] = exc

    release_body.set()
    assert resolve_done.wait(5.0), "resolve 须完成"
    t_resolve.join(2.0)

    assert load_result.get("status") == 409, load_result
    assert game.replacements == [], "在办窗不得 replace"
    assert game.session is old_session
    assert "end_turn" in game.actions
    assert "refresh" in game.actions
    assert f"end_on:{old_session_id}" in game.actions, (
        f"尾写须落在旧 session 上，actions={game.actions}"
    )
    assert web_app._settlement_entry_inflight(game) == 0


def test_replace_holds_entry_lock_so_begin_waits_for_new_session(monkeypatch):
    """#1702：replace 持 entry_lock 全程；begin 阻塞至 replace 结束，只在新 session 上 begin。"""
    game = _HotReplaceGame()
    old_session = game.session
    in_replace = threading.Event()
    release_replace = threading.Event()
    begin_done = threading.Event()
    begin_meta: dict = {}

    def _slow_load(name: str) -> None:
        game.replacements.append(name)
        in_replace.set()
        assert release_replace.wait(5.0), "测试须放行 replace"
        game.session = SimpleNamespace(last_decree="", state=game.state)
        game._session_token = object()

    game.load_save = _slow_load  # type: ignore[method-assign]
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    load_result: dict = {}

    def _run_load():
        try:
            asyncio.run(web_app.api_load_save("存档"))
            load_result["ok"] = True
        except Exception as exc:  # noqa: BLE001
            load_result["err"] = exc

    t_load = threading.Thread(target=_run_load, daemon=True)
    t_load.start()
    assert in_replace.wait(5.0), "load 须进入 replace"

    def _run_begin():
        try:
            # 若 replace 已持 entry_lock，此处阻塞至 replace 释放
            web_app._begin_settlement_entry(game)
            begin_meta["session_is_old"] = game.session is old_session
            begin_meta["session_id"] = id(game.session)
            begin_meta["inflight"] = web_app._settlement_entry_inflight(game)
        finally:
            begin_done.set()

    t_begin = threading.Thread(target=_run_begin, daemon=True)
    t_begin.start()
    # 给 begin 一点时间撞上 entry_lock
    time.sleep(0.05)
    assert not begin_done.is_set(), "replace 持锁期间 begin 不得完成"

    release_replace.set()
    assert begin_done.wait(5.0), "replace 结束后 begin 须完成"
    t_load.join(2.0)
    t_begin.join(2.0)

    assert load_result.get("ok") is True, load_result
    assert game.replacements == ["存档"]
    assert begin_meta.get("session_is_old") is False, begin_meta
    assert begin_meta.get("inflight") == 1
    web_app._end_settlement_entry(game)


def test_resolve_tail_write_holds_gate_briefly_not_whole_body(monkeypatch):
    """#1702 A2：end_turn/refresh 短持 gate；submit 与尾写之间 gate 曾释放（join 未整段持锁）。"""
    game = _HotReplaceGame(phase=TurnPhase.AWAITING_DECISION.value)
    gate_states: list[bool] = []

    def _submit_hitl(choices, *, write_gate, on_event=None, cheat_directive=""):
        with write_gate:
            game.actions.append("submit")
            assert game._write_gate.locked()
            if on_event:
                on_event("stage", "数值推演结算")
        gate_states.append(game._write_gate.locked())  # 须为 False：body 未整段持锁
        return "邸报：已裁。"

    real_end = game.session.end_turn

    def _end_turn():
        gate_states.append(game._write_gate.locked())  # 须为 True：尾写短持中
        real_end()

    game.session.submit_hitl_choices = _submit_hitl  # type: ignore[method-assign]
    game.session.end_turn = _end_turn  # type: ignore[method-assign]
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(
        web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: []
    )
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)

    events = asyncio.run(_consume_resolve_sse())
    assert game.actions[0] == "submit"
    assert "end_turn" in game.actions
    assert "refresh" in game.actions
    assert gate_states[0] is False, "submit 后 / 尾写前 gate 须空闲（未整段 body 持锁）"
    assert gate_states[1] is True, "end_turn 时须短持 write_gate"
    kinds = [ev for ev, _ in events]
    assert kinds and kinds[-1] == "done"


