"""事件亲裁选择→事件：只认显式结构化 event_id 对照权威候选快照。

不从自由题名补绑身份（#1834 F30 / ADR 0142 / 锚定宪法）。
"""

from ming_sim.settlement_payload import bind_decisions_to_candidate_events


_SNAPSHOT = {"candidate_events": [{"id": "mao_wenlong", "title": "毛文龙裁断"}]}


def test_valid_echoed_event_id_is_trusted_unchanged():
    """回显 id 确属本回合候选 → 采信（决策标题可与候选标题不同也不影响）。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "是否罢毛帅", "event_id": "mao_wenlong"}], _SNAPSHOT)
    assert out[0]["event_id"] == "mao_wenlong"


def test_missing_event_id_stays_unbound_without_title_fallback():
    """缺 id：不从题名补身份，保持未绑定。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "毛文龙裁断", "options": []}], _SNAPSHOT)
    assert "event_id" not in out[0]


def test_offsnapshot_echoed_event_id_is_unbound():
    """回显 id 不在候选快照 → 解绑；不得靠题名重绑。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "毛文龙裁断", "event_id": "wrong_event"}], _SNAPSHOT)
    assert "event_id" not in out[0]


def test_offsnapshot_id_with_no_title_match_is_unbound():
    """回显 id 不在快照 → 解绑，不把非候选 id 当 triggered 落库。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "某无关抉择", "event_id": "freeform_x"}], _SNAPSHOT)
    assert "event_id" not in out[0]


def test_no_snapshot_returns_decisions_unchanged():
    """无快照（payload 非 dict / 无 candidate_events）→ 决策原样返回，不臆测。"""
    assert bind_decisions_to_candidate_events(
        [{"title": "t", "event_id": "x"}], None)[0]["event_id"] == "x"
    assert "event_id" not in bind_decisions_to_candidate_events(
        [{"title": "t"}], {"other": 1})[0]
