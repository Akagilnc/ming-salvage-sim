"""#1234 T1 — 月初快照 + 核账展示态（路③等价状态）。

接缝（票面八条 / 判词收敛包）：
1. 颁布 / 退朝入口受理由 test_enter_settlement_period_1235 承接
2. awaiting_decision：钱粮仍为月初值；pending 批红照常下发
3. 独立保存/重开合同由 test_month_call_recovery_1846 承接
4. 断线后结算继续、重连自洽（改造既有恢复路径为回归）
5. 月推进完成 → 态清、活值回归；跨月快照不串（回合绑定）
6. 故障注入 oracle 两路：必须驱动真实启动位函数
7. 顶栏与户部余额同缝读快照（state_payload 内 metrics + budget.balance）
8. 载体 = 当前回合未过期快照存在 ⇔ 核账态（无第二 flag/相位）
"""

from __future__ import annotations

from tests.test_enter_settlement_period_1235 import _click_before as _click_before_metrics


from types import SimpleNamespace

import pytest

import web_app
from ming_sim.models import FRONT_HALF_DONE_PHASES, TurnPhase
from ming_sim.month_open_snapshot import (
    MONTH_OPEN_KEYS,
    clear_orphan_month_open_snapshot,
)


def test_capture_is_idempotent_and_turn_bound(game):
    db, state, _content = game
    before = _click_before_metrics(state)

    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 99
    db.save_state(state)
    db.capture_month_open_snapshot(state)

    snap = db.get_month_open_snapshot(int(state.turn))
    assert snap == before
    assert db.get_month_open_snapshot(int(state.turn) + 1) is None


def test_state_payload_overlays_snapshot_when_present(web_game):
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)

    state.metrics["国库"] = before["国库"] + 50
    state.metrics["内库"] = before["内库"] - 7
    state.metrics["民心"] = max(0, before["民心"] - 3)
    state.metrics["皇威"] = before["皇威"] + 2
    db.save_state(state)

    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is True
    for key in MONTH_OPEN_KEYS:
        assert payload["metrics"][key] == before[key]
    assert payload["budget"]["国库"]["balance"] == before["国库"]
    assert payload["budget"]["内库"]["balance"] == before["内库"]


def test_state_payload_live_when_no_snapshot(web_game):
    db, state = web_game.db, web_game.state
    live = _click_before_metrics(state)
    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    for key in MONTH_OPEN_KEYS:
        assert payload["metrics"][key] == live[key]


def test_awaiting_decision_keeps_month_open_money_and_pending(web_game):
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    state.metrics["国库"] = before["国库"] + 80
    db.save_state(state)

    db.save_pending_decisions(int(state.turn), [{
        "event_id": "evt-x",
        "title": "饷银",
        "context": "是否发帑",
        "options": [{"label": "发"}],
    }])

    payload = web_game.state_payload()

    assert payload["turn"]["settlement_display"] is True
    assert payload["metrics"]["国库"] == before["国库"]
    assert payload["budget"]["国库"]["balance"] == before["国库"]
    assert payload["pending_decisions"]
    assert payload["pending_decisions"][0]["title"] == "饷银"


def test_clear_on_month_complete_returns_live_values(web_game):
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 40
    db.save_state(state)

    db.clear_month_open_snapshot(turn)
    state.turn = turn + 1
    db.save_state(state)

    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == before["国库"] + 40
    assert db.get_month_open_snapshot(turn) is None


def test_cross_month_snapshot_does_not_bleed(web_game):
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.turn = turn + 1
    state.metrics["国库"] = before["国库"] + 5
    db.save_state(state)

    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == before["国库"] + 5


def test_oracle_normal_phase_clears_via_startup_hook(web_game):
    """故障注入常态路：相位常态 + 快照在 → 启动位清后无核账态，盘面为点击前值。"""
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 123
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    assert state.turn_phase not in FRONT_HALF_DONE_PHASES

    cleared = clear_orphan_month_open_snapshot(db, state)
    assert cleared is True
    assert db.get_month_open_snapshot(int(state.turn)) is None

    # ADR 0008：前半段未提交窗口引擎零持久态——崩溃回滚后活盘=点击前。
    for k, v in before.items():
        state.metrics[k] = v
    db.save_state(state)

    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == before[k]


def test_oracle_settling_phase_keeps_display_for_recovery(web_game):
    """故障注入 settling 路：启动位后核账态仍在，交既有恢复通道。"""
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 50
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    cleared = clear_orphan_month_open_snapshot(db, state)
    assert cleared is False
    assert db.get_month_open_snapshot(int(state.turn)) == before

    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is True
    assert payload["metrics"]["国库"] == before["国库"]


def test_capture_before_mutation_on_resolve_turn_entry(game, monkeypatch):
    """颁布入口：resolve_turn 在任何突变前持久化点击前四键。"""
    from tests.month_chain_helpers import make_light_session
    import ming_sim.audience_night as an

    db, state, content = game
    before = _click_before_metrics(state)

    sess = make_light_session(db, state, content)
    sess.llm_config = SimpleNamespace(channel="cli", api_key="x")

    def _boom(*_a, **_k):
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(an, "auto_close_open_night", _boom)

    db.add_directive(
        state, None, "减赋", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "tax-relief",
        },
    )

    with pytest.raises(RuntimeError):
        sess.resolve_turn(decree="诏曰测试")

    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_capture_before_mutation_on_advance_without_edict(game, monkeypatch):
    """退朝入口：session.advance_without_decree → resolve_turn 在任何突变前持久化点击前四键。"""
    from tests.month_chain_helpers import make_light_session
    import ming_sim.audience_night as an

    db, state, content = game
    before = _click_before_metrics(state)

    sess = make_light_session(db, state, content)

    def _boom(*_a, **_k):
        raise RuntimeError("stop-after-capture-advance")

    monkeypatch.setattr(an, "auto_close_open_night", _boom)

    with pytest.raises(RuntimeError):
        sess.advance_without_decree()

    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_player_month_advance_expires_snapshot(web_game, monkeypatch):
    """邸报完成后的真实月推进清除本月快照。"""
    from tests.test_due_review_621 import _settle_empty_month

    db, state, content = web_game.db, web_game.state, web_game.session.content
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    _settle_empty_month(db, state, content, monkeypatch)
    assert db.get_month_open_snapshot(turn) is None
    assert state.turn == turn + 1
    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == state.metrics["国库"]


def test_web_advance_entry_awaiting_keeps_phase_and_decisions(web_game, monkeypatch):
    """真实退朝 API：awaiting 分支不下 end_turn/refresh，留待裁面与 decisions（#1702 C2）。

    外部可见 + durable：响应 awaiting_decision/decisions 原样下发、turn 不推进、
    持久 phase 仍 awaiting。保留真实 end_turn/refresh；误调即改变相位与核账脸。
    """
    from ming_sim.decree import ResolveResult

    db, state = web_game.db, web_game.state
    turn_before = int(state.turn)
    runtime = web_game
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
        db.save_state(state)
        return ResolveResult(awaiting=True, decisions=list(decisions))

    runtime.session.advance_without_decree = _advance_awaiting
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

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
    assert db.get_month_open_snapshot(turn_before) is not None
