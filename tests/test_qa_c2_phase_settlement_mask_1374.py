from __future__ import annotations
import asyncio
import json
from tests.month_chain_helpers import canned_full_settlement, empty_rescript_response
import web_app
from ming_sim.models import TurnPhase
from tests.test_chat_stream_failpaths_393 import _parse_sse
"""QA 包乙刀① #1374：resolve_decisions/stream 接入 _settlement_period_entry。

接缝：
1. worker 与 issue/stream/advance 同走受理样板（begin→accept→await→close→gate）
2. phase2 在办期间状态口 settlement_display 仍真（快照在）
3. decided 先写后跑时序不动；不在此刀改 session.submit_decisions 写序
"""











async def _drain_resolve_sse(choices):
    response = await web_app.api_resolve_decisions_stream(
        web_app.ResolveDecisionsRequest(choices=choices),
    )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    return "".join(chunks)




def test_resolve_stream_entry_failure_exits_display_when_not_front_half(web_game, monkeypatch):
    """异常路径走受理样板 finally：非常态前半段时清展示态。"""
    db, state = web_game.db, web_game.state
    runtime = web_game
    # 非 awaiting：accept 会新建快照；submit 拒 → 失败 exit 须清。
    # gate 须为真锁：exit 路径 gate.acquire，禁 null cm 替身。
    state.turn_phase = TurnPhase.SUMMONING.value
    db.reign.save_game_state(state)

    def _boom(*_a, **_k):
        raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")

    runtime.session.submit_hitl_choices = _boom
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    serialized = asyncio.run(_drain_resolve_sse([{"label": "发"}]))
    events = _parse_sse(serialized)
    assert events and events[-1][0] == "error", events
    assert db.month_open_snapshots.get(int(state.turn)) is None
    assert runtime.state_payload()["turn"]["settlement_display"] is False


def test_resolve_stream_clear_throw_emits_error_not_done(web_game, monkeypatch):
    """负向：stream __done__ 须在 clear 成功后入队——clear 抛不得先推 done。"""
    db, state = web_game.db, web_game.state
    runtime = web_game
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", lambda session, *, officers, backlog, answer=None: json.dumps({
        "actor_name": officers[-1]["name"], "items": [{"title": "饷银", "context": "是否发帑", "options": [{"label": "发"}]}], "revisions": [],
    }) if answer is None else empty_rescript_response(session, officers=officers, backlog=backlog, answer=answer))
    waiting = runtime.session.advance_without_decree()
    assert waiting.awaiting

    import ming_sim.month_open_snapshot as mos

    def _boom_orphan(_db, _state):
        raise RuntimeError("stream clear boom")

    monkeypatch.setattr(mos, "clear_orphan_month_open_snapshot", _boom_orphan)

    serialized = asyncio.run(_drain_resolve_sse([{"decision_key": waiting.decisions[0]["decision_key"], "label": "发"}]))
    events = _parse_sse(serialized)
    assert events, serialized
    assert events[-1][0] == "error", events
    assert {name for name, _ in events} <= {"gazette", "error"}, events
