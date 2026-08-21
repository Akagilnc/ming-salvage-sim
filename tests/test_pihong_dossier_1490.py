"""#1490：批红待裁缺 dossier_id 被写成 decided 后无法重交。

两面钉：
1. 接收端：缺字段载荷 → 明确报错且 decision 仍 pending；随后带齐字段重交 → 成功落 decided。
   走真实 HTTP/API 入口（resolve_decisions/stream），不 mock 掉 submit_decisions 被测缝。
2. 生成端：dossier 类 decision 的 options/choices 载荷含 dossier_id / dossier_decision。
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from ming_sim.models import TurnPhase
from tests.dossier_test_helpers import rejected_verdict


def _runtime(db, state, content):
    """轻壳 WebGame：真实 GameSession.submit_decisions 缝，其余 state 口哑掉。"""
    sess = session_mod.GameSession.__new__(session_mod.GameSession)
    sess.db = db
    sess.state = state
    sess.last_decree = "诏曰测试"
    sess.last_report = ""
    sess.agno_db = None
    sess.llm_config = None
    sess.content = content
    sess.registry = None
    sess.previous_summary = ""

    runtime = object.__new__(web_app.WebGame)
    runtime.session = sess
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    runtime.refresh_turn = lambda: None
    runtime._write_gate = threading.Lock()
    # state_payload 读 session 字段
    runtime.session.pending_count = lambda: 0
    runtime.session.pending_decisions = lambda: db.list_pending_decisions(int(state.turn))
    runtime.session.victory = lambda: {"status": "ongoing", "summary": ""}
    runtime.session.current_phase = lambda: TurnPhase(state.turn_phase)
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


def _parse_sse_events(serialized: str) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    cur_event = "message"
    data_lines: list[str] = []
    for line in serialized.splitlines():
        if line.startswith("event:"):
            cur_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
        elif line == "" and data_lines:
            raw = "\n".join(data_lines)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            events.append((cur_event, payload))
            data_lines = []
            cur_event = "message"
    if data_lines:
        raw = "\n".join(data_lines)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        events.append((cur_event, payload))
    return events


def _plant_dossier_awaiting(db, state, content):
    """种下与 QA 同形：dossier 批红待裁 + resolve_context（含 candidate_events，触发 bind）。"""
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="密查陕西驿卒",
        target_kind="issue",
        target_id="river-works",
    )
    options = [
        {
            "label": "强颁",
            "hint": "以中旨强行颁出",
            "dossier_id": dossier_id,
            "dossier_decision": "force_promulgated",
        },
        {
            "label": "收回",
            "hint": "收回此道准旨",
            "dossier_id": dossier_id,
            "dossier_decision": "withdrawn",
        },
        {
            "label": "留中",
            "hint": "留待下月重判",
            "dossier_id": dossier_id,
            "dossier_decision": "hold",
        },
    ]
    db.save_pending_decisions(state.turn, [{
        "event_id": f"dossier:{dossier_id}",
        "title": "批红待裁",
        "context": "密查陕西驿卒",
        "rejection_reason": "科臣封驳",
        "opposition": "东林",
        "options": options,
    }])
    # candidate_events 列表存在 → bind 会处理 event_id；dossier: 不得被解绑。
    db.save_resolve_context(
        state.turn,
        "诏曰密查",
        "待续邸报",
        {"candidate_events": [{"id": "ev_border", "title": "边警"}]},
        secret_orders=[],
        relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    return dossier_id, options


def test_missing_dossier_fields_stay_pending_then_full_retry_decides(
    game, monkeypatch,
):
    """失败形（#1490 QA）：缺 dossier_id 的批红载荷 → 报错且仍 pending；
    随后带齐字段重交 → 成功落 decided。走 resolve_decisions/stream 真入口。"""
    db, state, content = game
    dossier_id, options = _plant_dossier_awaiting(db, state, content)
    runtime = _runtime(db, state, content)

    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        # 成功路径：模拟 phase2 清 pending（与真 phase2 同形，便于断言）
        _db.clear_pending_decisions(int(_state.turn))
        return "邸报：批红已落。"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    # ① 缺字段（与 QA m02-first-issue-pihong-choices 同形）
    incomplete = {"label": "强颁", "hint": "", "note": "准。先济关宁边饷。"}
    serialized = asyncio.run(_drain_resolve_sse([incomplete]))
    events = _parse_sse_events(serialized)
    kinds = [k for k, _ in events]
    assert "error" in kinds, f"缺字段须 SSE error，got {kinds}: {serialized}"
    assert "done" not in kinds
    err_payloads = [p for k, p in events if k == "error"]
    err_text = json.dumps(err_payloads, ensure_ascii=False)
    assert (
        "批红" in err_text
        or "dossier" in err_text.lower()
        or "非法" in err_text
        or "选项" in err_text
    ), err_text

    row = db.list_pending_decisions(state.turn)[0]
    assert row["status"] == "pending", (
        f"非法载荷绝不可落 decided，got status={row['status']!r} choice={row['choice']!r}"
    )
    assert row["choice"] is None
    assert phase2_calls == [], "校验失败不得进入 phase2"

    # 复位 awaiting（error 路径不应改 phase；双保险）
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    runtime.session.state = state

    # ② 带齐字段重交 → 成功
    full = {
        "label": "强颁",
        "hint": "以中旨强行颁出",
        "note": "准。先济关宁边饷。",
        "dossier_id": dossier_id,
        "dossier_decision": "force_promulgated",
    }
    serialized2 = asyncio.run(_drain_resolve_sse([full]))
    events2 = _parse_sse_events(serialized2)
    kinds2 = [k for k, _ in events2]
    assert "done" in kinds2, f"带齐字段须成功 done，got {kinds2}: {serialized2}"
    assert "error" not in kinds2
    assert len(phase2_calls) == 1
    decided_row = phase2_calls[0][0]
    assert decided_row["status"] == "decided"
    choice = decided_row["choice"] or {}
    assert choice.get("dossier_id") == dossier_id
    assert choice.get("dossier_decision") == "force_promulgated"


def test_rescript_decision_options_carry_dossier_capability_fields(game, monkeypatch):
    """生成端正常路径：dossier 类 decision 的 options 含 dossier_id / dossier_decision。"""
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="特旨清核河工",
        target_kind="issue",
        target_id="river-works",
        payload={"mode": "ordinary"},
    )

    def provider(_dossiers, _state):
        return [rejected_verdict(dossier_id)]

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda _simulator, _state, _db, _decree_text, _previous, **kwargs: (
            "本月邸报。", kwargs["simulator_payload"],
        ),
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "清核河工",
        content=content, promulgation_verdict_provider=provider,
    )

    assert result.awaiting is True
    dossier_rows = [
        d for d in result.decisions
        if str(d.get("event_id") or "") == f"dossier:{dossier_id}"
    ]
    assert len(dossier_rows) == 1, result.decisions
    options = dossier_rows[0]["options"]
    assert options, "批红 options 不得为空"
    for opt in options:
        assert opt.get("dossier_id") == dossier_id, opt
        assert opt.get("dossier_decision") in {
            "force_promulgated", "withdrawn", "hold",
        }, opt
        # 前端 isPendingDecision 要求 hint 为 string；生成端必须带上
        assert isinstance(opt.get("hint"), str), opt

    # 落库后再读，字段不得丢
    stored = db.list_pending_decisions(state.turn)
    stored_dossier = [
        d for d in stored
        if str(d.get("event_id") or "") == f"dossier:{dossier_id}"
    ]
    assert stored_dossier
    for opt in stored_dossier[0]["options"]:
        assert opt.get("dossier_id") == dossier_id
        assert opt.get("dossier_decision") in {
            "force_promulgated", "withdrawn", "hold",
        }


def test_bind_preserves_dossier_event_id():
    """#1490 接收端病灶：bind 不得把 dossier: 前缀 event_id 当 off-snapshot 解绑。"""
    from ming_sim.settlement_payload import bind_decisions_to_candidate_events

    decisions = [{
        "event_id": "dossier:8",
        "title": "批红待裁",
        "options": [{
            "label": "强颁",
            "dossier_id": 8,
            "dossier_decision": "force_promulgated",
        }],
    }]
    payload = {"candidate_events": [{"id": "ev1", "title": "边警"}]}
    out = bind_decisions_to_candidate_events(decisions, payload)
    assert out[0]["event_id"] == "dossier:8"
