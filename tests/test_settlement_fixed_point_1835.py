"""结局判定落在 typed outcome 上。"""

from __future__ import annotations


def test_victory_status_is_set_on_typed_outcome(game):
    """结局判定上浮为 typed 附加结果，且 frozen 结果不被就地改写。

    旧实现给 frozen dataclass 赋属性会在真结局（退位/自尽）时抛
    FrozenInstanceError——常规月（ongoing）走不到那条分支，故须专门钉。
    """
    from ming_sim.settlement import SettlementContext, settle_delta

    db, state, content = game
    outcome = settle_delta(
        state, db, {"emperor_fate": "abdicate"}, SettlementContext(content=content),
    )
    assert outcome.victory_status is not None
    assert outcome.victory_status["status"] == "emperor_abdicate"


def test_ongoing_outcome_carries_no_victory_status(game):
    """ongoing 不入 victory_status（与旧报告同口径：只有非 ongoing 才带）。"""
    from ming_sim.settlement import SettlementContext, settle_delta

    db, state, content = game
    outcome = settle_delta(state, db, {}, SettlementContext(content=content))
    assert outcome.victory_status is None
