"""#389 / #1897：事件亲裁选择→事件的绑定以权威候选快照的显式 id 为真源。

回显 id 只有确属本回合候选才采信；缺 id / off-snapshot id 解绑。
呈现标题不得补造或重绑 event_id（#1897 K2 / ADR0142）。
"""

from ming_sim.settlement_payload import bind_decisions_to_candidate_events


_SNAPSHOT = {"candidate_events": [{"id": "mao_wenlong", "title": "毛文龙裁断"}]}


def test_missing_event_id_stays_unbound_without_title_guess():
    """缺 id：不得按标题猜绑；保持无 event_id。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "毛文龙裁断", "options": []}], _SNAPSHOT)
    assert "event_id" not in out[0]


def test_valid_echoed_event_id_is_trusted_unchanged():
    """回显 id 确属本回合候选 → 采信（决策标题可与候选标题不同也不影响）。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "是否罢毛帅", "event_id": "mao_wenlong"}], _SNAPSHOT)
    assert out[0]["event_id"] == "mao_wenlong"


def test_offsnapshot_echoed_event_id_is_unbound():
    """回显 id 不在候选快照 → 解绑；不得按同标题重绑。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "毛文龙裁断", "event_id": "wrong_event"}], _SNAPSHOT)
    assert "event_id" not in out[0]


def test_offsnapshot_id_with_unrelated_title_is_unbound():
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
