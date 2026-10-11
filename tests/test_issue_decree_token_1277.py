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

    from tests.month_chain_helpers import canned_full_settlement
    canned_full_settlement(monkeypatch)
    from tests.test_month_chain_1843 import _stage_edict, _forbid_extractor
    _forbid_extractor(monkeypatch)
    minister = next(iter(runtime.content.characters.values())).name
    affair = db.affairs.open(name="边饷", origin="旨意", year=state.year, period=state.period, turn=state.turn)
    _stage_edict(db, state, minister, "核边饷", "核边饷", 0, affair.id)

    ev1, first = asyncio.run(_issue_stream_terminal(_body(start)))
    assert ev1 == "done", first
    assert isinstance(first.get("report"), str), first
    assert int(state.turn) == start + 1

    ev2, detail = asyncio.run(_issue_stream_terminal(_body(start)))
    assert ev2 == "error", detail
    assert int(detail.get("status_code") or 0) == 409, detail
    assert int(detail["turn"]) == start + 1
    assert int(state.turn) == start + 1  # 未再推进
