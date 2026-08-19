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


def test_oracle_normal_phase_clears_via_startup_hook(game, capsys):
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
    logged = capsys.readouterr().out
    assert "month_open_snapshot" in logged
    assert "启动清除孤儿月初快照" in logged

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

    with pytest.raises(RuntimeError, match="stop-after-capture"):
        sess.resolve_turn(decree="诏曰测试")

    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_capture_before_mutation_on_advance_without_edict(game, monkeypatch):
    """退朝入口：advance_without_edict 在任何突变前持久化点击前四键。"""
    import ming_sim.decree as dm
    import ming_sim.audience_night as an

    db, state, content = game
    before = _click_before_metrics(state)

    def _boom(*_a, **_k):
        raise RuntimeError("stop-after-capture-advance")

    monkeypatch.setattr(an, "auto_close_open_night", _boom)

    with pytest.raises(RuntimeError, match="stop-after-capture-advance"):
        dm.advance_without_edict(state, db, content=content)

    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_settle_with_delta_expires_snapshot_inside_atomic(game):
    """月推进完成：后半段 atomic 内过期快照（与 clear_resolve_context 同窗）。"""
    import ming_sim.decree as dm

    db, state, content = game
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    report = dm.settle_with_delta(
        state, db, {},
        before_turn=turn,
        content=content,
        decree_text="d",
        narrative="n",
    )
    assert isinstance(report, str)
    assert db.get_month_open_snapshot(turn) is None
    assert state.turn == turn + 1
    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False
    assert payload["metrics"]["国库"] == state.metrics["国库"]


def test_advance_without_edict_expires_snapshot(game, monkeypatch):
    import ming_sim.decree as dm
    import ming_sim.audience_night as an

    db, state, content = game
    turn = int(state.turn)

    monkeypatch.setattr(an, "auto_close_open_night", lambda *a, **k: None)
    monkeypatch.setattr(dm, "_requires_full_settlement", lambda *_a, **_k: False)

    ok = dm.advance_without_edict(state, db, content=content)
    assert ok is True
    assert db.get_month_open_snapshot(turn) is None
    assert state.turn == turn + 1
    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is False


def test_web_issue_entry_exposes_settlement_display(game, monkeypatch):
    """真实颁布 API 入口：受理后状态口含核账态 + 快照四键。"""
    from ming_sim.decree import ResolveResult

    db, state, _content = game
    before = _click_before_metrics(state)
    runtime = _runtime(db, state)

    def _fake_resolve(**_k):
        # 生产路径在 session.resolve_turn 内 capture；此处模拟同序
        db.capture_month_open_snapshot(state)
        state.metrics["国库"] = before["国库"] + 30
        state.turn_phase = TurnPhase.AWAITING_DECISION.value
        db.save_state(state)
        return ResolveResult(
            awaiting=True,
            decisions=[{"title": "测", "context": "x", "idx": 0, "options": []}],
        )

    runtime.session.resolve_turn = _fake_resolve
    runtime.session.last_decree = "诏曰测试"
    runtime.refresh_turn = lambda: None
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_game_write_gate", _null_cm)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    result = web_app.api_issue_decree(web_app.IssueDecreeRequest())
    assert result["awaiting_decision"] is True

    payload = runtime.state_payload()
    assert payload["turn"]["settlement_display"] is True
    assert payload["metrics"]["国库"] == before["国库"]
    assert payload["budget"]["国库"]["balance"] == before["国库"]


def test_web_advance_entry_exposes_settlement_display(game, monkeypatch):
    """真实退朝 API 入口：点即入后中途核账态+快照四键；成功回 summoning 后清残留（#1343）。"""
    import threading

    db, state, _content = game
    before = _click_before_metrics(state)
    runtime = _runtime(db, state)
    runtime.directive_rows = lambda: []
    runtime.refresh_turn = lambda: None
    runtime._write_gate = threading.Lock()
    mid = {}

    def _observe_then_done(st, database, **_kw):
        # 点即入已在 entry accept 完成——推进体入口即可见核账脸与点击前四键。
        mid["snap"] = database.get_month_open_snapshot(int(st.turn))
        mid["payload"] = runtime.state_payload()
        st.metrics["国库"] = before["国库"] + 9
        database.save_state(st)
        return True

    monkeypatch.setattr(web_app, "advance_without_edict", _observe_then_done)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_serialized_web_write", _null_cm)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    result = web_app.api_advance_without_edict()
    assert mid["snap"] == before
    assert mid["payload"]["turn"]["settlement_display"] is True
    assert mid["payload"]["metrics"]["国库"] == before["国库"]
    # 成功回常态（summoning）：生命周期缝清残留，拟诏不再被核账门误挡。
    assert result["state"]["turn"]["settlement_display"] is False
    assert db.get_month_open_snapshot(int(state.turn)) is None


def test_recovery_path_keeps_settlement_display(game, monkeypatch):
    """改造回归：settling 恢复路径上核账展示态仍在；完成后态清。"""
    import ming_sim.decree as dm
    from tests.test_advance_paths_atomic import _recovery_session

    db, state, content = game
    before = _click_before_metrics(state)
    turn = int(state.turn)
    db.capture_month_open_snapshot(state)

    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert clear_orphan_month_open_snapshot(db, state) is False

    payload = _runtime(db, state).state_payload()
    assert payload["turn"]["settlement_display"] is True
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == before[k]

    dm.persist_resolve_context(
        db, turn, {"metric_delta": {}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    sess = _recovery_session(db, state, content, monkeypatch)
    result = sess.resolve_turn()
    assert result.awaiting is False
    assert state.turn == turn + 1
    assert db.get_month_open_snapshot(turn) is None
    done = _runtime(db, state).state_payload()
    assert done["turn"]["settlement_display"] is False
