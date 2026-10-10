"""QA 包乙刀② #1343/#1378/#1379/#1388：核账遮罩生命周期（快照清理时点）。

单谓词不动：settlement_display ⇔ 当前回合快照在。
单一清理点：受理样板成功支（持 write_cm）；禁 refresh_turn 第二清理点。
验收：
  · 并发 A 成功未推月 + B 进 atomic 时 DELETE 不落 B 事务
  · clear 抛错后 inflight 归零
  · 真实入口成功回 summoning 清残留（见 test_month_open_snapshot_1234 退朝入口）
"""

from __future__ import annotations

from contextlib import contextmanager

from ming_sim.session_write_queue import ClassifiedWriteGate

import threading
from types import SimpleNamespace

import web_app
from ming_sim.models import TurnPhase




def _shell(db, state, content):
    """轻壳 WebGame：真 db/state + 真 write_gate。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        begin_turn=lambda: None,
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
    )
    runtime._write_gate = ClassifiedWriteGate()
    runtime._settlement_entry_lock = threading.Lock()
    runtime._settlement_entry_inflight = 0
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
def _blocking_gate(game):
    """与 issue/stream 同形：阻塞持 _game_write_gate。"""
    gate = web_app._game_write_gate(game)
    gate.acquire()
    try:
        yield
    finally:
        gate.release()




def test_success_clear_throw_still_ends_inflight(game, monkeypatch):
    """验收：成功支 clear 抛错仍执行 _end_settlement_entry（inflight 归零）。

    且 settled_ok 不得在 clear 前预置真——clear 抛须走失败 exit，
    禁「成功态 + 死遮罩」绕过失败收口。
    """
    db, state, content = game
    runtime = _shell(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.reign.save_game_state(state)
    db.capture_month_open_snapshot(state)

    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: True)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **_k: None)

    exit_calls = {"n": 0}
    real_exit = web_app._exit_settlement_display_on_failure

    def _spy_exit(g, *, blocking=False):
        exit_calls["n"] += 1
        return real_exit(g, blocking=blocking)

    monkeypatch.setattr(web_app, "_exit_settlement_display_on_failure", _spy_exit)

    def _boom_clear(_t):
        raise RuntimeError("clear boom")

    db.month_open_snapshots.delete = _boom_clear  # type: ignore[method-assign]

    raised = None
    try:
        with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
            pass
    except RuntimeError as exc:
        raised = exc

    assert raised is not None and "clear boom" in str(raised)
    assert web_app._settlement_entry_inflight(runtime) == 0, "clear 抛错后 inflight 须归零"
    assert exit_calls["n"] == 1, "clear 抛须走失败 exit（settled_ok 未在 clear 前预置）"


def test_failure_exit_throw_still_ends_inflight(game, monkeypatch):
    """对称：失败支 exit 抛错亦不得卡住 inflight（嵌套 finally 销账）。"""
    db, state, content = game
    runtime = _shell(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.reign.save_game_state(state)

    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: True)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **_k: None)

    def _boom_exit(*_a, **_k):
        raise RuntimeError("exit boom")

    monkeypatch.setattr(web_app, "_exit_settlement_display_on_failure", _boom_exit)

    raised = None
    try:
        with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
            raise ValueError("body fail")
    except RuntimeError as exc:
        raised = exc

    assert raised is not None and "exit boom" in str(raised)
    assert web_app._settlement_entry_inflight(runtime) == 0


def test_success_clear_throw_via_orphan_exits_display(game, monkeypatch):
    """负向：clear_orphan 抛错后 settled_ok 仍假 → 失败 exit 清常态死遮罩。

    与 boom db.clear 不同：此处只炸 orphan 包装，exit 走真 clear 可清快照。
    """
    db, state, content = game
    runtime = _shell(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.reign.save_game_state(state)
    db.capture_month_open_snapshot(state)
    assert runtime.state_payload()["turn"]["settlement_display"] is True

    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: True)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **_k: None)

    import ming_sim.month_open_snapshot as mos

    def _boom_orphan(_db, _state):
        raise RuntimeError("orphan clear boom")

    monkeypatch.setattr(mos, "clear_orphan_month_open_snapshot", _boom_orphan)

    raised = None
    try:
        with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
            pass
    except RuntimeError as exc:
        raised = exc

    assert raised is not None and "orphan clear boom" in str(raised)
    assert web_app._settlement_entry_inflight(runtime) == 0
    assert db.month_open_snapshots.get(int(state.turn)) is None
    assert runtime.state_payload()["turn"]["settlement_display"] is False
