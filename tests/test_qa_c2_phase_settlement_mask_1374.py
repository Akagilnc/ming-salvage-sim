"""QA 包乙刀① #1374：resolve_decisions/stream 接入 _settlement_period_entry。

接缝：
1. worker 与 issue/stream/advance 同走受理样板（begin→accept→await→close→gate）
2. phase2 在办期间状态口 settlement_display 仍真（快照在）
3. decided 先写后跑时序不动；不在此刀改 session.submit_decisions 写序
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.models import TurnPhase
from ming_sim.month_open_snapshot import MONTH_OPEN_KEYS


@contextmanager
def _null_cm(*_a, **_k):
    yield None


def _click_before(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}


def _runtime(db, state):
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=SimpleNamespace(characters={}),
        previous_summary="",
        last_decree="诏曰测试",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: db.list_pending_decisions(int(state.turn)),
        victory=lambda: {"status": "ongoing", "summary": ""},
        current_phase=lambda: TurnPhase(state.turn_phase),
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    runtime.actions = []
    runtime.session.end_turn = lambda: runtime.actions.append("end_turn")
    runtime.refresh_turn = lambda: runtime.actions.append("refresh")
    runtime._write_gate = threading.Lock()
    runtime._settlement_entry_lock = threading.Lock()
    runtime._settlement_entry_inflight = 0
    return runtime


async def _drain_resolve_sse(choices):
    response = await web_app.api_resolve_decisions_stream(
        web_app.ResolveDecisionsRequest(choices=choices),
    )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    return "".join(chunks)


def test_resolve_stream_uses_settlement_period_entry(game, monkeypatch):
    """#1374：resolve/stream worker 必入 _settlement_period_entry（对照三入口样板）。"""
    db, state, _content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "evt-1",
        "title": "饷银",
        "context": "是否发帑",
        "options": [{"label": "发", "hint": "发内帑"}],
    }])

    runtime = _runtime(db, state)
    entered = {"n": 0}
    real_entry = web_app._settlement_period_entry

    @contextmanager
    def _spy_entry(g, *, write_cm, hold_write_for_body=True):
        entered["n"] += 1
        # 锁语义与 issue/stream 同：阻塞 _game_write_gate（禁 advance 的非阻塞 409 形）
        assert write_cm is web_app._game_write_gate
        # #657 resolve：hold_write_for_body=False（①/③ 分段）；展示态仍入样板
        with real_entry(
            g, write_cm=write_cm, hold_write_for_body=hold_write_for_body,
        ):
            yield

    phase2_started = threading.Event()
    release_phase2 = threading.Event()

    def _submit_hitl(choices, *, write_gate, on_event=None, cheat_directive=""):
        # 生产协议：submit_hitl_choices；纯 decision 路径持 write_gate。
        runtime.actions.append("submit")
        with write_gate:
            # 模拟 decided 先写（崩溃安全时序）——本刀不改 session 真写序，仅证展示态窗口。
            db.conn.execute(
                "UPDATE pending_decisions SET status='decided' WHERE turn=?",
                (int(state.turn),),
            )
            db.conn.commit()
            phase2_started.set()
            assert release_phase2.wait(5.0)
            if on_event:
                on_event("stage", "数值推演结算")
            return "邸报：测。"

    runtime.session.submit_hitl_choices = _submit_hitl
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_settlement_period_entry", _spy_entry)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    async def _go():
        # 并行：放行 phase2 前先观测展示态
        async def _watch():
            assert await asyncio.get_event_loop().run_in_executor(None, phase2_started.wait, 5.0)
            payload = runtime.state_payload()
            assert payload["turn"]["settlement_display"] is True
            for k in MONTH_OPEN_KEYS:
                assert payload["metrics"][k] == before[k]
            release_phase2.set()

        watch_task = asyncio.create_task(_watch())
        serialized = await _drain_resolve_sse([{"label": "发"}])
        await watch_task
        return serialized

    serialized = asyncio.run(_go())
    assert entered["n"] == 1
    assert runtime.actions == ["submit", "end_turn", "refresh"]
    assert "event: done" in serialized
    # 快照仍在（本替身 submit 未推进月份）；phase2 窗内展示态真源不灭
    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_resolve_stream_entry_failure_exits_display_when_not_front_half(game, monkeypatch):
    """异常路径走受理样板 finally：非常态前半段时清展示态。"""
    db, state, _content = game
    runtime = _runtime(db, state)
    # 非 awaiting：accept 会新建快照；submit 拒 → 失败 exit 须清。
    # gate 须为真锁：exit 路径 gate.acquire，禁 null cm 替身。
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)

    def _boom(*_a, **_k):
        raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")

    runtime.session.submit_hitl_choices = _boom
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    serialized = asyncio.run(_drain_resolve_sse([{"label": "发"}]))
    assert "event: error" in serialized
    assert db.get_month_open_snapshot(int(state.turn)) is None
    assert runtime.state_payload()["turn"]["settlement_display"] is False


def test_resolve_stream_clear_throw_emits_error_not_done(game, monkeypatch):
    """负向：stream __done__ 须在 clear 成功后入队——clear 抛不得先推 done。"""
    db, state, _content = game
    runtime = _runtime(db, state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.capture_month_open_snapshot(state)
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "evt-1",
        "title": "饷银",
        "context": "是否发帑",
        "options": [{"label": "发", "hint": "发内帑"}],
    }])

    def _submit_hitl(choices, *, write_gate, on_event=None, cheat_directive=""):
        runtime.actions.append("submit")
        with write_gate:
            if on_event:
                on_event("stage", "数值推演结算")
            # 回 summoning 常态，使成功支 clear_orphan 真触发
            state.turn_phase = TurnPhase.SUMMONING.value
            db.save_state(state)
            return "邸报：测。"

    runtime.session.submit_hitl_choices = _submit_hitl
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    import ming_sim.month_open_snapshot as mos

    def _boom_orphan(_db, _state):
        raise RuntimeError("stream clear boom")

    monkeypatch.setattr(mos, "clear_orphan_month_open_snapshot", _boom_orphan)

    serialized = asyncio.run(_drain_resolve_sse([{"label": "发"}]))
    assert runtime.actions == ["submit", "end_turn", "refresh"]
    assert "event: done" not in serialized, "clear 抛后禁推 done"
    assert "event: error" in serialized
    assert "stream clear boom" in serialized
    assert runtime.state_payload()["turn"]["settlement_display"] is False
