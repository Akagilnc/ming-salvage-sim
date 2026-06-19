"""#195：历史事件链终态后的级联作废。"""

import pytest

from ming_sim import issues
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import Event


def _hist_event(eid, gate=None):
    return Event(
        id=eid,
        title=f"测试事件 {eid}",
        kind="测试",
        summary="x",
        urgency=50,
        severity=50,
        credibility=50,
        interests=[],
        audiences=[],
        trigger_year=1,
        trigger_month=1,
        open_window=True,
        trigger_gate=gate or {},
    )


class _TempEvents:
    def __init__(self, content, *events):
        self.content = content
        self.events = events
        self.previous = {}

    def __enter__(self):
        for ev in self.events:
            self.content.events.append(ev)
            self.previous[ev.id] = self.content.event_by_id.get(ev.id)
            self.content.event_by_id[ev.id] = ev
        return self.events

    def __exit__(self, exc_type, exc, tb):
        for ev in self.events:
            if ev in self.content.events:
                self.content.events.remove(ev)
            old = self.previous.get(ev.id)
            if old is None:
                self.content.event_by_id.pop(ev.id, None)
            else:
                self.content.event_by_id[ev.id] = old


def _terminal_state(db, event_id):
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    return row["terminal_state"], row["terminal_reason"]


def test_positive_dependency_invalidates_when_upstream_expires(game):
    db, state, content = game
    issues.bind_content(content)
    upstream = _hist_event("__chain_upstream_expired__")
    upstream.open_window = False
    upstream.trigger_year = 1629
    upstream.trigger_end_year = 1629
    upstream.trigger_end_month = 2
    downstream = _hist_event("__chain_downstream_positive__", {
        "event.__chain_upstream_expired__.terminal_state": "==triggered",
        "event.__chain_upstream_expired__.terminal_reason": "==胜利",
    })
    with _TempEvents(content, upstream, downstream):
        state.year = 1629
        state.period = 3

        terminalized = issues.apply_event_terminal_states(state, db)

        assert any(item["id"] == upstream.id and item["terminal_state"] == "expired" for item in terminalized)
        assert _terminal_state(db, downstream.id)[0] == "obsolete"


def test_positive_outcome_dependency_waits_for_frozen_outcome_label(game):
    db, state, content = game
    issues.bind_content(content)
    upstream = _hist_event("__chain_upstream_no_outcome_yet__")
    downstream = _hist_event("__chain_downstream_waits_outcome__", {
        "event.__chain_upstream_no_outcome_yet__.terminal_state": "==triggered",
        "event.__chain_upstream_no_outcome_yet__.terminal_reason": "==目标结局",
    })
    with _TempEvents(content, upstream, downstream):
        db.mark_event_triggered(state, upstream.id)

        terminalized = issues.apply_event_cascading_invalidations(state, db)

        assert all(item["id"] != downstream.id for item in terminalized)
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            (downstream.id,),
        ).fetchone() is None


def test_negative_dependency_is_satisfied_by_upstream_expiry_not_invalidated(game):
    db, state, content = game
    issues.bind_content(content)
    upstream = _hist_event("__chain_upstream_expired_for_negative__")
    upstream.open_window = False
    upstream.trigger_year = 1629
    upstream.trigger_end_year = 1629
    upstream.trigger_end_month = 2
    downstream = _hist_event("__chain_downstream_negative__", {
        "event.__chain_upstream_expired_for_negative__.terminal_state": "!=triggered",
    })
    with _TempEvents(content, upstream, downstream):
        state.year = 1629
        state.period = 3

        issues.apply_event_terminal_states(state, db)

        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            (downstream.id,),
        ).fetchone() is None
        assert any(candidate.id == downstream.id for candidate in issues.gather_candidate_events(state, db))


def test_negative_dependency_invalidates_when_upstream_fired_forbidden_outcome(game):
    db, state, content = game
    issues.bind_content(content)
    upstream = _hist_event("__chain_upstream_bad_outcome__")
    downstream = _hist_event("__chain_downstream_forbids_bad__", {
        "event.__chain_upstream_bad_outcome__.terminal_reason": "!=坏结局",
    })
    with _TempEvents(content, upstream, downstream):
        db.mark_event_triggered(state, upstream.id, terminal_reason="坏结局")

        terminalized = issues.apply_event_cascading_invalidations(state, db)

        assert any(item["id"] == downstream.id and item["terminal_state"] == "obsolete" for item in terminalized)
        assert _terminal_state(db, downstream.id) == ("obsolete", "上游事件 __chain_upstream_bad_outcome__ 已发禁用结局：坏结局")


def test_negative_dependency_is_satisfied_by_upstream_avoidance_not_invalidated(game):
    db, state, content = game
    issues.bind_content(content)
    upstream = _hist_event("__chain_upstream_avoided_for_negative__")
    downstream = _hist_event("__chain_downstream_negative_after_avoid__", {
        "event.__chain_upstream_avoided_for_negative__.terminal_state": "!=triggered",
    })
    with _TempEvents(content, upstream, downstream):
        db.mark_event_avoided(state, upstream.id, reason="测试避过")

        terminalized = issues.apply_event_cascading_invalidations(state, db)

        assert all(item["id"] != downstream.id for item in terminalized)
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            (downstream.id,),
        ).fetchone() is None
        assert any(candidate.id == downstream.id for candidate in issues.gather_candidate_events(state, db))


def test_soft_gate_failure_does_not_invalidate_chain_candidate(game):
    db, state, content = game
    issues.bind_content(content)
    upstream = _hist_event("__chain_upstream_good__")
    downstream = _hist_event("__chain_downstream_soft_gate__", {
        "event.__chain_upstream_good__.terminal_state": "==triggered",
        "event.__chain_upstream_good__.terminal_reason": "==好结局",
        "region.beizhili.controlled_by": "==houjin",
    })
    with _TempEvents(content, upstream, downstream):
        db.mark_event_triggered(state, upstream.id, terminal_reason="好结局")
        db.conn.execute("UPDATE regions SET controlled_by='ming' WHERE id='beizhili'")

        terminalized = issues.apply_event_cascading_invalidations(state, db)

        assert all(item["id"] != downstream.id for item in terminalized)
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            (downstream.id,),
        ).fetchone() is None
        assert all(candidate.id != downstream.id for candidate in issues.gather_candidate_events(state, db))


def test_transitive_cascade_invalidates_downstream_closure(game):
    db, state, content = game
    issues.bind_content(content)
    a = _hist_event("__chain_a__")
    b = _hist_event("__chain_b__", {"event.__chain_a__.terminal_state": "==triggered"})
    c = _hist_event("__chain_c__", {"event.__chain_b__.terminal_state": "==triggered"})
    with _TempEvents(content, a, b, c):
        db.mark_event_expired(state, a.id)

        terminalized = issues.apply_event_cascading_invalidations(state, db)

        assert [item["id"] for item in terminalized] == [b.id, c.id]
        assert _terminal_state(db, b.id)[0] == "obsolete"
        assert _terminal_state(db, c.id)[0] == "obsolete"


def test_event_dependency_cycle_fails_loud(game):
    db, state, content = game
    issues.bind_content(content)
    a = _hist_event("__chain_cycle_a__", {"event.__chain_cycle_b__.terminal_state": "==triggered"})
    b = _hist_event("__chain_cycle_b__", {"event.__chain_cycle_a__.terminal_state": "==triggered"})
    with _TempEvents(content, a, b):
        with pytest.raises(SettlementAbort, match="事件链依赖存在环"):
            issues.apply_event_cascading_invalidations(state, db)
