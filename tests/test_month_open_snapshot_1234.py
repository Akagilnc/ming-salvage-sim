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

from ming_sim.session_write_queue import get_session_write_queue

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.models import FRONT_HALF_DONE_PHASES, TurnPhase
from ming_sim.month_open_snapshot import (
    MONTH_OPEN_KEYS,
    clear_orphan_month_open_snapshot,
)


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


def _click_before_metrics(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}


@contextmanager
def _null_cm(*_a, **_k):
    yield None


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


def test_state_payload_overlays_snapshot_when_present(game):
    db, state, _content = game
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)

    state.metrics["国库"] = before["国库"] + 50
    state.metrics["内库"] = before["内库"] - 7
    state.metrics["民心"] = max(0, before["民心"] - 3)
    state.metrics["皇威"] = before["皇威"] + 2
    db.save_state(state)

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is True
    for key in MONTH_OPEN_KEYS:
        assert payload["metrics"][key] == before[key]
    assert payload["budget"]["国库"]["balance"] == before["国库"]
    assert payload["budget"]["内库"]["balance"] == before["内库"]


def test_state_payload_live_when_no_snapshot(game):
    db, state, _content = game
    live = _click_before_metrics(state)
    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    for key in MONTH_OPEN_KEYS:
        assert payload["metrics"][key] == live[key]


def test_awaiting_decision_keeps_month_open_money_and_pending(game):
    db, state, _content = game
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
    pending = db.list_pending_decisions(int(state.turn))

    payload = _runtime(db, state, pending_decisions=pending).state_payload()

    assert payload["turn"]["settlement_display"] is True
    assert payload["metrics"]["国库"] == before["国库"]
    assert payload["budget"]["国库"]["balance"] == before["国库"]
    assert payload["pending_decisions"]
    assert payload["pending_decisions"][0]["title"] == "饷银"


def test_fresh_connection_same_face(game):
    """同进程刷新 = 不经启动位；快照仍在 → 同一张脸。"""
    db, state, _content = game
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 11
    db.save_state(state)

    face_a = _runtime(db, state).state_payload()
    face_b = _runtime(db, state).state_payload()
    assert face_a["turn"]["settlement_display"] is True
    assert face_b["turn"]["settlement_display"] is True
    assert face_a["metrics"]["国库"] == face_b["metrics"]["国库"] == before["国库"]


def test_clear_on_month_complete_returns_live_values(game):
    db, state, _content = game
    before = _click_before_metrics(state)
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 40
    db.save_state(state)

    db.clear_month_open_snapshot(turn)
    state.turn = turn + 1
    db.save_state(state)

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == before["国库"] + 40
    assert db.get_month_open_snapshot(turn) is None


def test_cross_month_snapshot_does_not_bleed(game):
    db, state, _content = game
    before = _click_before_metrics(state)
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.turn = turn + 1
    state.metrics["国库"] = before["国库"] + 5
    db.save_state(state)

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == before["国库"] + 5


def test_oracle_normal_phase_clears_via_startup_hook(game):
    """故障注入常态路：相位常态 + 快照在 → 启动位清后无核账态，盘面为点击前值。"""
    db, state, _content = game
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

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == before[k]


def test_oracle_settling_phase_keeps_display_for_recovery(game):
    """故障注入 settling 路：启动位后核账态仍在，交既有恢复通道。"""
    db, state, _content = game
    before = _click_before_metrics(state)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] = before["国库"] + 50
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    cleared = clear_orphan_month_open_snapshot(db, state)
    assert cleared is False
    assert db.get_month_open_snapshot(int(state.turn)) == before

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is True
    assert payload["metrics"]["国库"] == before["国库"]


def test_capture_before_mutation_on_resolve_turn_entry(game, monkeypatch):
    """颁布入口：resolve_turn 在任何突变前持久化点击前四键。"""
    from ming_sim.session import GameSession
    import ming_sim.audience_night as an

    db, state, content = game
    before = _click_before_metrics(state)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = SimpleNamespace(channel="cli", api_key="x")
    sess.agno_db = None
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.last_decree = ""
    sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._beat_generator = None
    sess._scene_registry = None
    sess.auto_save = lambda *_a, **_k: None

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
    from ming_sim.session import GameSession
    import ming_sim.audience_night as an

    db, state, content = game
    before = _click_before_metrics(state)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    sess.agno_db = None
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.last_decree = ""
    sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._beat_generator = None
    sess._scene_registry = None
    sess.auto_save = lambda *_a, **_k: None

    def _boom(*_a, **_k):
        raise RuntimeError("stop-after-capture-advance")

    monkeypatch.setattr(an, "auto_close_open_night", _boom)

    with pytest.raises(RuntimeError):
        sess.advance_without_decree()

    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_player_month_advance_expires_snapshot(game, monkeypatch):
    """邸报完成后的真实月推进清除本月快照。"""
    from tests.test_due_review_621 import _settle_empty_month

    db, state, content = game
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    _settle_empty_month(db, state, content, monkeypatch)
    assert db.get_month_open_snapshot(turn) is None
    assert state.turn == turn + 1
    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == state.metrics["国库"]
