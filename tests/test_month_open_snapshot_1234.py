"""#1234 T1 — 月初快照 + 核账展示态（路③等价状态）。

接缝（票面八条 / 判词收敛包）：
1. 颁布 / 退朝真实入口：受理后状态口立即含核账展示态 + 快照四键
2. awaiting_decision：钱粮仍为月初值；pending 批红照常下发
3. 全新连接（模拟刷新）同一核账态 + 同一快照
4. 断线后结算继续、重连自洽（改造既有恢复路径为回归）
5. 月推进完成 → 态清、活值回归；跨月快照不串（回合绑定）
6. 故障注入 oracle 两路：必须驱动真实启动位函数
7. 顶栏与户部余额同缝读快照（state_payload 内 metrics + budget.balance）
8. 载体 = 当前回合未过期快照存在 ⇔ 核账态（无第二 flag/相位）
"""

from __future__ import annotations
import pytest


from ming_sim.session_write_queue import get_session_write_queue

from contextlib import contextmanager
from types import SimpleNamespace


import web_app
from ming_sim.models import TurnPhase, FRONT_HALF_DONE_PHASES


def _runtime(db, state, *, pending_decisions=None) -> web_app.WebGame:
    """轻壳 WebGame：只挂 db/state/session，走真实 state_payload / budget_payload。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=SimpleNamespace(characters={}),
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: list(pending_decisions or []),
        victory=lambda: {"status": "ongoing", "summary": ""},
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime




@contextmanager
def _null_cm(*_a, **_k):
    yield None


@pytest.mark.parametrize("phase", [TurnPhase.SUMMONING.value, TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value])
def test_player_month_advance_expires_snapshot(game, monkeypatch, phase):
    from tests.test_due_review_621 import _settle_empty_month
    db, state, _content = game
    turn = int(state.turn)
    before = {k: int(state.metrics[k]) for k in ("国库", "内库", "民心", "皇威")}
    db.capture_month_open_snapshot(state)
    live_balance = before["国库"] + 123
    state.metrics["国库"] = live_balance
    state.turn_phase = phase
    db.reign.save_game_state(state)
    if phase == TurnPhase.AWAITING_DECISION.value:
        db.issues.save_pending_decisions(turn, [{"event_id": "awaiting-test", "title": "待裁", "options": [{"label": "准"}]}])
    pending = db.issues.list_pending_decisions(turn)
    path = db.path
    db.close()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    reopened = web_app.WebGame(fresh=False, db_path=path)
    try:
        assert reopened._runtime_write_queue().wait_idle(timeout_s=5)
        reloaded = reopened.db.load_state()
        assert reloaded.metrics["国库"] == live_balance
        assert reloaded.turn == turn and reloaded.turn_phase == phase
        recovering = phase in FRONT_HALF_DONE_PHASES
        assert reopened.db.month_open_snapshots.get(turn) == (before if recovering else None)
        payload = reopened.state_payload()
        assert payload["turn"]["settlement_display"] is recovering
        assert payload["metrics"]["国库"] == (before["国库"] if recovering else live_balance)
        assert reopened.db.issues.list_pending_decisions(turn) == pending
        if phase == TurnPhase.AWAITING_DECISION.value:
            assert payload["pending_decisions"] == reopened.session.pending_decisions()
        if not recovering:
            _settle_empty_month(reopened.db, reopened.state, reopened.content, monkeypatch)
            assert reopened.db.month_open_snapshots.get(turn) is None
            assert reopened.state.turn == turn + 1
            assert reopened.state_payload()["metrics"]["国库"] == reopened.db.load_state().metrics["国库"]
    finally:
        reopened.session.close()


def test_web_advance_entry_awaiting_keeps_phase_and_decisions(game, monkeypatch):
    """真实退朝 API：awaiting 分支不下 end_turn/refresh，留待裁面与 decisions（#1702 C2）。

    外部可见 + durable：响应 awaiting_decision/decisions 原样下发、turn 不推进、
    持久 phase 仍 awaiting。end_turn 桩镜像生产（只置 SUMMONING 并 save）——
    若入口误调 end_turn，相位/核账脸断言红；不得以 mock 调用序单独当契约。
    """
    from ming_sim.decree import ResolveResult

    db, state, _content = game
    turn_before = int(state.turn)
    runtime = _runtime(db, state)
    runtime.directive_rows = lambda: []
    runtime._write_gate = get_session_write_queue(runtime).write_gate
    decisions = [
        {
            "event_id": "evt-await-c2",
            "title": "辽饷批红",
            "context": "是否准发",
            "options": [{"label": "准"}],
        }
    ]

    def _advance_awaiting(**_kw):
        # entry accept 已 capture；桩内保持快照，落生产 awaiting 相位。
        state.turn_phase = TurnPhase.AWAITING_DECISION.value
        db.reign.save_game_state(state)
        return ResolveResult(awaiting=True, decisions=list(decisions))

    def _end_turn():
        # 镜像 session.end_turn durable 副作用（只置 SUMMONING 并 save，不推进 turn）。
        state.turn_phase = TurnPhase.SUMMONING.value
        db.reign.save_game_state(state)

    runtime.session.advance_without_decree = _advance_awaiting
    runtime.session.end_turn = _end_turn
    runtime.refresh_turn = lambda: None
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_serialized_web_write", _null_cm)

    result = web_app.api_advance_without_edict()

    reloaded = db.load_state()
    assert reloaded.turn == turn_before
    assert reloaded.turn_phase == TurnPhase.AWAITING_DECISION.value
    assert result["awaiting_decision"] is True
    assert result["decisions"] == decisions
    assert result["state"]["turn"]["turn"] == turn_before
    assert state.turn == turn_before
    # durable 红证：误调 end_turn 会把相位打回 summoning 并清核账脸。
    assert state.turn_phase == TurnPhase.AWAITING_DECISION.value
    assert result["state"]["turn"]["phase"] == TurnPhase.AWAITING_DECISION.value
    assert result["state"]["turn"]["settlement_display"] is True
    assert db.month_open_snapshots.get(turn_before) is not None


def test_cross_month_snapshot_does_not_bleed(game):
    db, state, _content = game
    before = {k: int(state.metrics[k]) for k in ("国库", "内库", "民心", "皇威")}
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.turn = turn + 1
    state.metrics['国库'] = before['国库'] + 5
    db.reign.save_game_state(state)
    payload = _runtime(db, state).state_payload()
    assert payload['turn']['settlement_display'] is False
    assert payload['metrics']['国库'] == before['国库'] + 5


@pytest.mark.parametrize("method", ["resolve_turn", "advance_without_decree"])
def test_capture_before_mutation_on_resolve_turn_entry(game, monkeypatch, method):
    from tests.month_chain_helpers import make_light_session
    import ming_sim.audience_night as an

    db, state, content = game
    before = {k: int(state.metrics[k]) for k in ("国库", "内库", "民心", "皇威")}
    session = make_light_session(db, state, content)
    fault = RuntimeError("close fault")
    def fail(*_a, **_k):
        raise fault
    monkeypatch.setattr(an, "auto_close_open_night", fail)
    with pytest.raises(RuntimeError) as exc:
        getattr(session, method)()
    assert exc.value is fault
    assert db.month_open_snapshots.get(int(state.turn)) == before
