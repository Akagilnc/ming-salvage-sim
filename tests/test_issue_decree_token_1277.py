"""#1277 — issue/stream 可选 expected_turn 防双发吃月（同 #1351 口径）。

接缝：
1. IssueDecreeRequest 可选 expected_turn（缺省=兼容现状）
2. 获锁后、resolve_turn 前：game.state.turn 不匹配 → 人话 409 + 当前 turn
3. 同令牌连发两次 → 第二次 SSE error status_code=409，月份只进一格
"""

from __future__ import annotations


import asyncio

import pytest

import web_app
from ming_sim.decree import ResolveResult
from ming_sim.models import TurnPhase


def _body(expected_turn: int | None, *, cheat: str = ""):
    return web_app.IssueDecreeRequest(cheat=cheat, expected_turn=expected_turn)


async def _issue_stream_terminal(body: web_app.IssueDecreeRequest) -> tuple[str, dict]:
    from tests.test_chat_stream_failpaths_393 import _parse_sse
    response = await web_app.api_issue_decree_stream(body)
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    serialized = "".join(chunks)
    events = _parse_sse(serialized)
    assert events, serialized
    event, data = events[-1]
    return event, data if isinstance(data, dict) else {"message": data}


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_double_issue_same_token_second_is_409_turn_plus_one(web_game, monkeypatch):
    """同 expected_turn 连发两次：第二次 SSE 409，月份只进一格；resolve 不二次执行。"""
    db, state = web_game.db, web_game.state
    assert state.turn_phase == TurnPhase.SUMMONING.value
    start = int(state.turn)
    runtime = web_game

    def _fake_resolve(**_k):
        # 模拟 resolve_turn 成功推进一格（与生产同向副作用）。
        state.turn = start + 1
        state.turn_phase = TurnPhase.SUMMONING.value
        db.save_state(state)
        runtime.session.last_decree = "诏曰测试"
        return ResolveResult(awaiting=False, report="邸报测")

    runtime.session.resolve_turn = _fake_resolve

    ev1, first = asyncio.run(_issue_stream_terminal(_body(start)))
    assert ev1 == "done", first
    assert isinstance(first.get("report"), str), first
    assert int(state.turn) == start + 1

    ev2, detail = asyncio.run(_issue_stream_terminal(_body(start)))
    assert ev2 == "error", detail
    assert int(detail.get("status_code") or 0) == 409, detail
    assert int(detail["turn"]) == start + 1
    assert int(state.turn) == start + 1  # 未再推进
