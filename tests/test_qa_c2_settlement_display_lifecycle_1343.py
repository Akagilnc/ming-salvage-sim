"""QA 包乙刀② #1343/#1378/#1379/#1388：核账遮罩生命周期（快照清理时点）。

单谓词不动：settlement_display ⇔ 当前回合快照在。
单一清理点：受理样板成功支（持 write_cm）；禁 refresh_turn 第二清理点。
验收：
  · 并发 A 成功未推月 + B 进 atomic 时 DELETE 不落 B 事务
  · clear 抛错后 inflight 归零
  · 真实入口成功回 summoning 清残留（见 test_month_chain_1847 玩家月链）
"""

from __future__ import annotations


from ming_sim.models import TurnPhase


from tests.test_enter_settlement_period_1235 import _click_before


def test_refresh_turn_no_longer_clears_orphan(web_game):
    """F3：refresh_turn 不再是清理点——直调不得清残留（清理只在受理样板成功支）。"""
    db, state = web_game.db, web_game.state
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)

    web_game.refresh_turn()
    assert db.get_month_open_snapshot(int(state.turn)) == before
