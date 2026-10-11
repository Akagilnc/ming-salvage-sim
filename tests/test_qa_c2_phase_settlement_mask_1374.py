"""QA 包乙刀① #1374：resolve_decisions/stream 接入 _settlement_period_entry。

接缝：
1. worker 与 issue/stream/advance 同走受理样板（begin→accept→await→close→gate）
2. phase2 在办期间状态口 settlement_display 仍真（快照在）
3. decided 先写后跑时序不动；不在此刀改 session.submit_decisions 写序
"""

from __future__ import annotations


import asyncio
import threading


import web_app
from ming_sim.models import TurnPhase
from ming_sim.month_open_snapshot import MONTH_OPEN_KEYS
from tests.test_chat_stream_failpaths_393 import _parse_sse
from tests.test_enter_settlement_period_1235 import _click_before


async def _drain_resolve_sse(choices):
    response = await web_app.api_resolve_decisions_stream(
        web_app.ResolveDecisionsRequest(choices=choices),
    )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    return "".join(chunks)


def test_resolve_stream_uses_settlement_period_entry(web_game, monkeypatch):
    """#1374：resolve/stream worker 必入 _settlement_period_entry（对照三入口样板）。"""
    db, state = web_game.db, web_game.state
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

    runtime = web_game
    phase2_started = threading.Event()
    release_phase2 = threading.Event()

    def _submit_hitl(choices, *, write_gate, cheat_directive=""):
        # 生产协议：submit_hitl_choices；纯 decision 路径持 write_gate。
        with write_gate:
            # 模拟 decided 先写（崩溃安全时序）——本刀不改 session 真写序，仅证展示态窗口。
            db.conn.execute(
                "UPDATE pending_decisions SET status='decided' WHERE turn=?",
                (int(state.turn),),
            )
            db.conn.commit()
            phase2_started.set()
            release_phase2.wait()
            return "邸报：测。"

    runtime.session.submit_hitl_choices = _submit_hitl
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    async def _go():
        # 并行：放行 phase2 前先观测展示态。
        # drain 终态必须先 stop/release，再 await watcher——禁在 finally 前无条件等 watch
        # （resolve 失败产出 error SSE 后 drain 正常返回，phase2 永不置位）。
        stop = threading.Event()

        async def _watch():
            # 可取消异步轮询（禁 executor 上 Event.wait：cancel 打不穿）。
            # release 归 watcher 持有：观察/断言失败也必达，打破 resolve↔drain 互等。
            try:
                while not phase2_started.is_set() and not stop.is_set():
                    await asyncio.sleep(0)
                if not phase2_started.is_set():
                    return
                payload = runtime.state_payload()
                assert payload["turn"]["settlement_display"] is True
                for k in MONTH_OPEN_KEYS:
                    assert payload["metrics"][k] == before[k]
            finally:
                release_phase2.set()

        watch_task = asyncio.create_task(_watch())
        body_exc: BaseException | None = None
        watch_exc: BaseException | None = None
        result = None
        try:
            result = await _drain_resolve_sse([{"label": "发"}])
        except BaseException as exc:
            body_exc = exc
        finally:
            # drain 已返回或失败：先 stop/release，再收 watcher。
            # 先排空并消费 watch 异常，再按 body>watch 次序重抛——收尾不替换主体原错。
            stop.set()
            release_phase2.set()
            if not watch_task.done():
                try:
                    await watch_task
                except BaseException as exc:
                    watch_exc = exc
            elif not watch_task.cancelled():
                watch_exc = watch_task.exception()
        if body_exc is not None:
            raise body_exc
        if watch_exc is not None:
            raise watch_exc
        return result

    serialized = asyncio.run(_go())
    events = _parse_sse(serialized)
    assert events and events[-1][0] == "done", events
    # 快照仍在（本替身 submit 未推进月份）；phase2 窗内展示态真源不灭
    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_resolve_stream_entry_failure_exits_display_when_not_front_half(web_game, monkeypatch):
    """异常路径走受理样板 finally：非常态前半段时清展示态。"""
    db, state = web_game.db, web_game.state
    runtime = web_game
    # 非 awaiting：accept 会新建快照；submit 拒 → 失败 exit 须清。
    # gate 须为真锁：exit 路径 gate.acquire，禁 null cm 替身。
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)

    def _boom(*_a, **_k):
        raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")

    runtime.session.submit_hitl_choices = _boom
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    serialized = asyncio.run(_drain_resolve_sse([{"label": "发"}]))
    events = _parse_sse(serialized)
    assert events and events[-1][0] == "error", events
    assert db.get_month_open_snapshot(int(state.turn)) is None
    assert runtime.state_payload()["turn"]["settlement_display"] is False


def test_resolve_stream_clear_throw_emits_error_not_done(web_game, monkeypatch):
    """负向：stream __done__ 须在 clear 成功后入队——clear 抛不得先推 done。"""
    db, state = web_game.db, web_game.state
    runtime = web_game
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.capture_month_open_snapshot(state)
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "evt-1",
        "title": "饷银",
        "context": "是否发帑",
        "options": [{"label": "发", "hint": "发内帑"}],
    }])

    def _submit_hitl(choices, *, write_gate, cheat_directive=""):
        with write_gate:
            # 回 summoning 常态，使成功支 clear_orphan 真触发
            state.turn_phase = TurnPhase.SUMMONING.value
            db.save_state(state)
            return "邸报：测。"

    runtime.session.submit_hitl_choices = _submit_hitl
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    import ming_sim.month_open_snapshot as mos

    def _boom_orphan(_db, _state):
        raise RuntimeError("stream clear boom")

    monkeypatch.setattr(mos, "clear_orphan_month_open_snapshot", _boom_orphan)

    serialized = asyncio.run(_drain_resolve_sse([{"label": "发"}]))
    events = _parse_sse(serialized)
    assert events, serialized
    assert [name for name, _ in events] == ["error"], events
