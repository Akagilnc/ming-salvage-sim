"""#1274 QA A-新3：409/超时 UX 族（#1301/#1306/#1312/#1319(a)/#1322）。

刀口锁状态码、结构化 detail、相位分叉与 resolve 锁前预检；
ADR 0036/0006 机制零动。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim import audience_night as an
from ming_sim.session_write_queue import ClassifiedWriteGate
from ming_sim.models import FRONT_HALF_DONE_PHASES, TurnPhase


# ── #1301 玩家面 409 去裸 night_id ──────────────────────────────────────────


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


def test_directive_payload_authority_not_notes_alias(web_game):
    """#1319(a)：真实状态口中 notes 备注不得投影成 authority。"""
    did = web_game.db.add_directive(
        web_game.state, None, "发帑辽东", source="manual", actor="袁崇焕",
        notes="家赀约十万两", status="draft",
    )
    payload = next(d for d in web_game.state_payload()["directives"] if d["id"] == did)
    assert payload["notes"] == "家赀约十万两"
    assert payload["authority"] == ""


# ── #1322 resolve stream 相位预检在抢锁前 ───────────────────────────────────


async def _consume_resolve_sse() -> list[tuple[str, object]]:
    """Drain the whole SSE; return [(event, payload), ...] in order."""
    from tests.test_chat_stream_failpaths_393 import _parse_sse
    response = await web_app.api_resolve_decisions_stream(
        web_app.ResolveDecisionsRequest(choices=[{"label": "发帑"}])
    )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    return _parse_sse("".join(chunks))


def test_resolve_decisions_stream_phase_precheck_before_lock(web_game, monkeypatch):
    """#1322：非 awaiting 相位在抢锁前快速失败；持锁者不被卡住；submit 不进。"""
    gate = web_game._write_gate
    gate.acquire()  # 模拟结算 worker 持锁；若预检在锁后，本测会阻塞至超时
    game = web_game
    game.state.turn_phase = TurnPhase.SETTLING.value
    actions = []
    monkeypatch.setattr(game.session, "submit_hitl_choices", lambda *a, **k: actions.append("submit"))
    monkeypatch.setattr(game.session, "end_turn", lambda: actions.append("end_turn"))
    monkeypatch.setattr(game, "refresh_turn", lambda: actions.append("refresh"))
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
    assert actions == []


def test_resolve_decisions_stream_awaiting_still_submits_under_lock(web_game, monkeypatch):
    """#1322：awaiting 相位仍经 submit_hitl 在 write_gate 内提交（权威复查保留）。"""
    game = web_game
    gate = game._write_gate
    game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    submitted = {"ok": False}

    def _submit_hitl(choices, *, write_gate, cheat_directive=""):
        with write_gate:
            assert gate.locked(), "submit must run while write gate held"
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
