from __future__ import annotations
from tests.test_enter_settlement_period_1235 import _click_before as _click_before_metrics
from types import SimpleNamespace
import pytest
import web_app
from fastapi.testclient import TestClient
from tests.sse_helpers import parse_sse_event_pairs
from ming_sim.models import TurnPhase
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














def test_player_month_advance_expires_snapshot(web_game, monkeypatch):
    """邸报完成后的真实月推进清除本月快照。"""
    from tests.test_due_review_621 import _settle_empty_month

    db, state, content = web_game.db, web_game.state, web_game.session.content
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    _settle_empty_month(db, state, content, monkeypatch)
    assert db.month_open_snapshots.get(turn) is None
    assert state.turn == turn + 1
    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == state.metrics["国库"]


def test_web_advance_entry_awaiting_keeps_phase_and_decisions(web_game, monkeypatch):
    """真实退朝 API：awaiting 分支不下 end_turn/refresh，留待裁面与 decisions（#1702 C2）。

    外部可见 + durable：decisions 终态原样下发、turn 不推进、
    持久 phase 仍 awaiting。保留真实 end_turn/refresh；误调即改变相位与核账脸。
    """

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

    from tests.month_chain_helpers import canned_full_settlement
    import json
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", lambda session, *, officers, backlog, answer=None: json.dumps({
        "actor_name": officers[-1]["name"], "items": decisions, "revisions": [],
    }))

    response = TestClient(web_app.app).post("/api/decree/advance_without_edict/stream")
    assert response.status_code == 200
    kind, result = parse_sse_event_pairs(response.text)[-1]
    assert kind == "decisions"
    payload = TestClient(web_app.app).get("/api/game/state").json()

    reloaded = db.load_state()
    assert reloaded.turn == turn_before
    assert reloaded.turn_phase == TurnPhase.AWAITING_DECISION.value
    assert result["decisions"] == runtime.session.pending_decisions()
    assert [(row["title"], row["context"], row["options"]) for row in result["decisions"]] == [(row["title"], row["context"], row["options"]) for row in decisions]
    assert payload["turn"]["turn"] == turn_before
    assert state.turn == turn_before
    # durable 红证：误调 end_turn 会把相位打回 summoning 并清核账脸。
    assert state.turn_phase == TurnPhase.AWAITING_DECISION.value
    assert payload["turn"]["phase"] == TurnPhase.AWAITING_DECISION.value
    assert payload["turn"]["settlement_display"] is True
    assert db.month_open_snapshots.get(turn_before) is not None


def test_cross_month_snapshot_does_not_bleed(web_game):
    db, state = web_game.db, web_game.state
    before = _click_before_metrics(state)
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.turn = turn + 1
    state.metrics["国库"] = before["国库"] + 5
    db.reign.save_game_state(state)

    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == before["国库"] + 5


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

    db.issues.add_directive(state.turn, state.year, state.period, None, '减赋', source='player', status='draft', dossier_payload={'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'tax-relief'})

    with pytest.raises(RuntimeError, match="stop-after-capture"):
        sess.resolve_turn(decree="诏曰测试")

    assert db.month_open_snapshots.get(int(state.turn)) == before
