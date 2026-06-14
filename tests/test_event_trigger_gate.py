"""#12（M1 P0）：历史锚定事件结构化前提门。

`trigger_gate` + `_gate_passed`（能查 character/faction/army/region/metric 真实字段）此前只接
seed 情势，历史 `events` 分支只过纯日历窗口 `_event_window_open` → 前提已不成立的历史事件按
年月误触发（毛文龙已安抚/效顺仍被弹出的机制半）。把门接进历史分支：带 gate 的历史事件须达标
才进候选；无 gate（空 dict）= 纯日历锚定，行为不变。
"""
from ming_sim import issues
from ming_sim.models import Event


def _hist_event(eid, gate):
    return Event(
        id=eid, title="测试门控历史事件", kind="situation",
        summary="x", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[],
        trigger_year=1, trigger_month=0,  # 极早历史锚点 → 日历窗口必开
        trigger_gate=gate,
    )


def test_gated_historical_event_excluded_when_unsatisfied(game):
    db, state, content = game
    issues.bind_content(content)  # 防他测漂移 _content：确保 _ctx() 指向本 fixture 盘面
    ev = _hist_event("__test_gated_hist__", {"民心": "<=5"})
    content.events.append(ev)
    try:
        state.metrics["民心"] = 60  # gate 不达标
        cands = issues.gather_candidate_events(state, db)
        assert all(c.id != "__test_gated_hist__" for c in cands), \
            "前提门不达标的历史事件不应进候选（#12 机制半）"
    finally:
        content.events.remove(ev)


def test_gated_historical_event_included_when_satisfied(game):
    db, state, content = game
    issues.bind_content(content)  # 防他测漂移 _content：确保 _ctx() 指向本 fixture 盘面
    ev = _hist_event("__test_gated_hist2__", {"民心": "<=5"})
    content.events.append(ev)
    try:
        state.metrics["民心"] = 3  # gate 达标
        cands = issues.gather_candidate_events(state, db)
        assert any(c.id == "__test_gated_hist2__" for c in cands), \
            "前提门达标的历史事件应进候选"
    finally:
        content.events.remove(ev)


def test_ungated_historical_event_unchanged(game):
    db, state, content = game
    issues.bind_content(content)  # 防他测漂移 _content：确保 _ctx() 指向本 fixture 盘面
    ev = _hist_event("__test_ungated_hist__", {})  # 无 gate = 纯日历锚定
    content.events.append(ev)
    try:
        state.metrics["民心"] = 60
        cands = issues.gather_candidate_events(state, db)
        assert any(c.id == "__test_ungated_hist__" for c in cands), \
            "无前提门的历史事件应保持纯日历窗口行为不变"
    finally:
        content.events.remove(ev)
