"""#1891 三饷由皇帝批，不自动置已准——资格事实与配置面。

覆盖面（本票授权的最小纵切，且只留不经真实入口就无法表达的契约）：
- 到点不自行置结局：账上零终局行，事件进 petition-due 名单。
- 首次到点应呈请是名单上的权限事实。已留中后再呈、世界段消息供料，由真实过月链证明。
- 配置面：结局闭集齐备。交接绑定走真实过月链，不在本文件用回显键复证。

本文件只钉不经真实入口就无法表达的契约。交接绑定、案头物化、答复落账、结局置定、
跨月读端与持久恢复，全部在 tests/test_levy_petition_month_chain_1891.py 走真实
过月链端到端证明——不在此重复内部 helper 证明。
"""

from __future__ import annotations

import ming_sim.issues as issues
from ming_sim.content import GameContent
from ming_sim.issues import (
    FISCAL_LEVY_RESCRIPT_SOURCE, list_fiscal_levy_petitions_due,
)
from ming_sim.month_chain import _LEVY_PETITION_PREFIX


def _prepare_due(db, state, content, year=1631, period=1):
    issues.bind_content(content)
    state.year = year
    state.period = period
    db.save_state(state)


# ---------------------------------------------------------------- 交接面


def test_petition_due_lists_liao_rise_at_historical_timepoint(game):
    """到点请饷进 petition-due 名单，首次到点的呈请义务是名单上的权限事实。"""
    db, state, content = game
    _prepare_due(db, state, content)

    due = list_fiscal_levy_petitions_due(state, db)

    assert [item["event_id"] for item in due] == ["liao_levy_rise_1631"]
    assert due[0]["terminal_reason_labels"] == ["已准", "已驳"]
    # 首次到点：应呈请（权限事实），不是大臣自决的再呈；不带旧疏。
    assert due[0]["presentation_due"] is True
    assert due[0]["re_presentation"] is False
    assert "prior_petition" not in due[0]


def test_petition_due_is_empty_before_the_gate_and_after_verdict(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)
    assert list_fiscal_levy_petitions_due(state, db) == []

    _prepare_due(db, state, content)
    assert [i["event_id"] for i in list_fiscal_levy_petitions_due(state, db)] == ["liao_levy_rise_1631"]

    # 一事件一终局裁断：已裁过的不再回名单。
    db.mark_event_triggered(
        state, "liao_levy_rise_1631", source=FISCAL_LEVY_RESCRIPT_SOURCE, terminal_reason="已准",
    )
    assert list_fiscal_levy_petitions_due(state, db) == []


def test_petition_due_skips_event_already_awaiting_verdict_on_desk(game):
    """#1891：已呈上批红页待裁的，本月不重触发为首次事件。"""
    db, state, content = game
    _prepare_due(db, state, content)
    db.save_pending_decisions(int(state.turn), [{
        "event_id": f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",
        "title": "辽饷升至一分二厘",
        "context": "军费窟窿",
        "options": [{"label": "准行加派", "hint": ""}],
    }])

    assert list_fiscal_levy_petitions_due(state, db) == []


def test_content_declares_closed_label_sets_for_levy_events():
    """配置面：每个饷率事件都声明了结局闭集，否则请旨无闭集可归一。"""
    content = GameContent.load()
    levy = [
        ev for ev in content.events
        if getattr(ev, "category", "") == "fiscal_levy"
    ]
    assert levy, "内容里应至少有一个饷率事件"
    for ev in levy:
        assert getattr(ev, "terminal_reason_labels", None), (
            f"饷率事件 {ev.id} 缺 terminal_reason_labels 白名单"
        )
