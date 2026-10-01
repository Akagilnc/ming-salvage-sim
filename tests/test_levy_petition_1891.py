"""#1891 饷率事件的配置面：每个事件都声明结局闭集。

到点呈请、待裁不重触发、裁后离名单、留中再呈，由
tests/test_levy_petition_month_chain_1891.py 的真实过月链证明。
"""

from __future__ import annotations

from ming_sim.content import GameContent


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
