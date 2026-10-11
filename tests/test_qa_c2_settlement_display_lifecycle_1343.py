"""QA 包乙刀② #1343/#1378/#1379/#1388：核账遮罩生命周期（快照清理时点）。

单谓词不动：settlement_display ⇔ 当前回合快照在。
单一清理点：受理样板成功支（持 write_cm）；禁 refresh_turn 第二清理点。
验收：
  · 并发 A 成功未推月 + B 进 atomic 时 DELETE 不落 B 事务
  · clear 抛错后 inflight 归零
  · 真实入口成功回 summoning 清残留（见 test_month_open_snapshot_1234 退朝入口）
"""

from __future__ import annotations

from ming_sim.session_write_queue import ClassifiedWriteGate

import threading
from types import SimpleNamespace

import web_app
from ming_sim.models import TurnPhase
from ming_sim.month_open_snapshot import MONTH_OPEN_KEYS


def _click_before(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}


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


def test_refresh_turn_no_longer_clears_orphan(game):
    """F3：refresh_turn 不再是清理点——直调不得清残留（清理只在受理样板成功支）。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)

    runtime = _shell(db, state, content)
    # 绑定真实方法（轻壳无实例绑定）
    web_app.WebGame.refresh_turn(runtime)
    assert db.get_month_open_snapshot(int(state.turn)) == before
