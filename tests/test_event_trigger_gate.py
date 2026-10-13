from tests.conftest import stub_month_translate
import ming_sim.settlement.preflight as settlement_preflight
from ming_sim.entities.issue.tracker import apply_issue_tracker_output
from ming_sim.applier import Provenance
import json
from contextlib import contextmanager
import pytest
from ming_sim import issues
import ming_sim.entities.issue.event_terminal as event_terminal
from ming_sim.models import Event
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section, view
from ming_sim.entities.issue.store import IssueStore
"""#12（M1 P0）：历史锚定事件结构化前提门。

`trigger_gate` + `_gate_passed`（能查 character/faction/army/region/metric 真实字段）此前只接
seed 情势，历史 `events` 分支只过纯日历窗口 `_event_window_open` → 前提已不成立的历史事件按
年月误触发（毛文龙已安抚/效顺仍被弹出的机制半）。把门接进历史分支：带 gate 的历史事件须达标
才进候选；无 gate（空 dict）= 纯日历锚定，行为不变。
"""




def _promulgated_dossier(db, state, decree_text):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text=decree_text,
        target_kind="army", target_id="guanning",
    )
    db.dossiers.record_dossier_decision(dossier_id, "promulgated")
    db.dossiers.transition(dossier_id, "executing")
    return f"dossier:{dossier_id}"


def _hist_event(eid, gate):
    return Event(
        id=eid, title="测试门控历史事件", kind="situation",
        summary="x", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[],
        trigger_year=1, trigger_month=0,  # 极早历史锚点 → 日历窗口必开
        trigger_gate=gate,
    )


@contextmanager
def _restore_yuan_as_guanning_commander(db, content):
    """起复并任命袁崇焕掌关宁——mao_wenlong gate 前置（seed 关宁已非袁统帅）。

    同步 DB armies.commander 与 content 绑定对象；退出时还原 content 与 DB 行
    （#1426：finally 只还 content 会泄漏 active 袁崇焕 + 关宁 commander）。
    """
    yuan = content.characters.get("袁崇焕")
    army = content.armies.get("guanning")
    prev_yuan_status = yuan.status if yuan is not None else None
    prev_commander = army.commander if army is not None else None
    db_yuan = db.conn.execute(
        "SELECT status FROM characters WHERE name=?", ("袁崇焕",),
    ).fetchone()
    db_army = db.conn.execute(
        "SELECT commander FROM armies WHERE id=?", ("guanning",),
    ).fetchone()
    prev_db_yuan_status = db_yuan["status"] if db_yuan is not None else None
    prev_db_commander = db_army["commander"] if db_army is not None else None
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning"))
    db.conn.commit()
    if yuan is not None:
        yuan.status = "active"
    if army is not None:
        army.commander = "袁崇焕"
    try:
        yield
    finally:
        if yuan is not None:
            yuan.status = prev_yuan_status
        if army is not None:
            army.commander = prev_commander
        if prev_db_yuan_status is not None:
            db.conn.execute(
                "UPDATE characters SET status=? WHERE name=?",
                (prev_db_yuan_status, "袁崇焕"),
            )
        if prev_db_commander is not None:
            db.conn.execute(
                "UPDATE armies SET commander=? WHERE id=?",
                (prev_db_commander, "guanning"),
            )
        db.conn.commit()


@pytest.mark.parametrize("gate, support, calendar, trigger, open_window, included", [
    ({"民心": "<=5"}, 3, None, (1, 0), False, True),
    (None, 60, None, (1, 0), False, True),
    ({}, 60, None, (1, 0), False, True),
    ({"民心": "<=5"}, 60, None, (1, 0), False, False),
    ({}, None, (1627, 10), (1629, 6), True, False),
])
def test_gated_historical_event_included_when_satisfied(
    game, gate, support, calendar, trigger, open_window, included,
):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_gated_hist2__", gate)
    ev.trigger_year, ev.trigger_month = trigger
    ev.open_window = open_window
    content.events.append(ev)
    try:
        if support is not None:
            state.metrics["民心"] = support
        if calendar is not None:
            state.year, state.period = calendar
        cands = issues.gather_candidate_events(state, db)
        assert any(c.id == ev.id for c in cands) is included
    finally:
        content.events.remove(ev)


def test_historical_event_expires_after_latest_window_when_gate_unsatisfied(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_expiring_hist__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 60

        cands = issues.gather_candidate_events(state, db)

        assert all(c.id != "__test_expiring_hist__" for c in cands)
        assert db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_hist__",),
        ).fetchone() is None

        terminalized = event_terminal.apply_event_terminal_states(state, db)

        assert {
            "id": "__test_expiring_hist__",
            "title": "测试门控历史事件",
            "terminal_state": "expired",
        } in terminalized
        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_hist__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_state"] == "expired"

        state.metrics["民心"] = 3
        later_cands = issues.gather_candidate_events(state, db)
        assert all(c.id != "__test_expiring_hist__" for c in later_cands)
    finally:
        content.events.remove(ev)


def test_historical_event_gate_can_read_event_triggered_record(game):
    """#192：核心事实进 event_triggers 后，下游硬门可用 event.<id>.triggered 查询。"""
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_after_huabei__", {"event.huabei_plague.triggered": "==1"})
    content.events.append(ev)
    try:
        assert all(c.id != "__test_after_huabei__" for c in issues.gather_candidate_events(state, db))

        db.mark_event_triggered(state, "huabei_plague")

        assert any(c.id == "__test_after_huabei__" for c in issues.gather_candidate_events(state, db))
    finally:
        content.events.remove(ev)


def test_historical_event_latest_month_is_still_inside_window(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_latest_month_hist__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 2
        state.metrics["民心"] = 3

        cands = issues.gather_candidate_events(state, db)

        assert any(c.id == "__test_latest_month_hist__" for c in cands)
        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_latest_month_hist__",),
        ).fetchone()
        assert row is None
    finally:
        content.events.remove(ev)


def test_historical_event_triggered_gate_ignores_obsolete_terminal(game):
    """ship-pre CMR：obsolete 终态只用于去重，不应打开 event.<id>.triggered 下游门。"""
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_after_obsolete_mao__", {"event.mao_wenlong.triggered": "==1"})
    content.events.append(ev)
    try:
        db.mark_event_obsolete(state, "mao_wenlong", reason="测试：人物核心主体已死")

        assert all(c.id != "__test_after_obsolete_mao__" for c in issues.gather_candidate_events(state, db))
    finally:
        content.events.remove(ev)


def test_open_window_historical_event_never_expires(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_open_window_hist__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    ev.open_window = True
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 3

        cands = issues.gather_candidate_events(state, db)

        assert any(c.id == "__test_open_window_hist__" for c in cands)
        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_open_window_hist__",),
        ).fetchone()
        assert row is None
    finally:
        content.events.remove(ev)


def test_seed_event_expires_after_latest_window_when_gate_unsatisfied(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_expiring_seed__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    content.seed_events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 60

        cands = issues.gather_candidate_events(state, db)

        assert all(c.id != "__test_expiring_seed__" for c in cands)
        assert db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_seed__",),
        ).fetchone() is None

        event_terminal.apply_event_terminal_states(state, db)

        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_seed__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_state"] == "expired"
    finally:
        content.seed_events.remove(ev)


def test_auto_trigger_seed_event_expires_after_latest_window_when_gate_unsatisfied(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_expiring_auto_seed__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    ev.auto_trigger = True
    content.seed_events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 60

        triggered = issues.auto_trigger_seed_issues(state, db)

        assert triggered == []
        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_auto_seed__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_state"] == "expired"
        assert issues.auto_trigger_seed_issues(state, db) == []
        assert db.conn.execute(
            "SELECT COUNT(*) FROM event_triggers WHERE event_id=?",
            ("__test_expiring_auto_seed__",),
        ).fetchone()[0] == 1
    finally:
        content.seed_events.remove(ev)


def test_gather_candidate_events_filters_expired_auto_trigger_seed_without_writing(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_expiring_auto_seed_candidate__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    ev.auto_trigger = True
    content.seed_events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 3

        cands = issues.gather_candidate_events(state, db)

        assert all(c.id != "__test_expiring_auto_seed_candidate__" for c in cands)
        assert db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_auto_seed_candidate__",),
        ).fetchone() is None

        event_terminal.apply_event_terminal_states(state, db)

        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            ("__test_expiring_auto_seed_candidate__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_state"] == "expired"
    finally:
        content.seed_events.remove(ev)


def test_event_pool_apply_uses_pushed_candidate_snapshot_not_fresh_recompute(game):
    """#345：落库端按已推给裁判/玩家的候选快照验收，避免触发口径与推送口径分叉。"""
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_pushed_snapshot_event__", {"民心": "<=5"})
    ev.event_type = "situation"
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        state.metrics["民心"] = 3
        assert ev.id in {candidate.id for candidate in issues.gather_candidate_events(state, db)}

        state.metrics["民心"] = 60
        out = apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": ev.id}]},
            content=content,
            candidate_event_ids_at_input={ev.id},
            candidate_event_ids_authoritative=True,
        source=Provenance.system_simulation)

        assert "rejected" not in out.new_issues[0]
        assert db.conn.execute(
            "SELECT 1 FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
        assert db.issues.has_event_terminal_state(ev.id, "triggered")
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_apply_event_terminal_states_does_not_commit_existing_transaction(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_expiring_inside_outer_txn__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 60
        db.conn.execute("BEGIN")

        terminalized = event_terminal.apply_event_terminal_states(state, db)

        assert any(item["id"] == "__test_expiring_inside_outer_txn__" for item in terminalized)
        assert db.conn.in_transaction
        db.conn.rollback()
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            ("__test_expiring_inside_outer_txn__",),
        ).fetchone() is None
    finally:
        if db.conn.in_transaction:
            db.conn.rollback()
        content.events.remove(ev)


@pytest.mark.parametrize("condition", [60, True])
def test_gate_passed_tolerates_nonstring_cond(game, condition):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_nonstring_gate__", {"民心": condition})
    content.events.append(ev)
    try:
        assert ev.id not in {c.id for c in issues.gather_candidate_events(state, db)}
    finally:
        content.events.remove(ev)


# ── #12(b)：trigger_gate key/cond fail-loud（ADR 0012 残留 4b，Q3 裁断=fail-loud）──


@pytest.mark.parametrize("event_input", [
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'民生': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'regon.x.unrest': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'region.x': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'event.huabei_plague.status': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'region..unrest': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'region.x.': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'region.shaanxi|.unrest': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'class.@nanzhili.satisfaction': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'class.@n1|@n2.satisfaction': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'class.士绅@.satisfaction': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': 6, 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': 6, 'open_window': 'false', 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'event_type': 'situation', 'trigger_class': 'strategic_foreign'},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': 6, 'trigger_end_year': 1629, 'trigger_end_month': 5, 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': 13, 'trigger_end_year': 1629, 'trigger_end_month': 7, 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': -1, 'trigger_end_year': 1629, 'trigger_end_month': 7, 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': 6, 'trigger_end_year': 1629, 'trigger_end_month': 13, 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'interests': [], 'audiences': [], 'trigger_year': 1629, 'trigger_month': 6, 'trigger_end_year': 1629, 'trigger_end_month': -1, 'trigger_gate': {'民心': '<=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'民心': 'abc'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'民心': '>> 5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'民心': '!=5'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'民心': '!=-3'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'region.a|b.controlled_by': '==ming'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'class.士绅.satisfaction': '==ming'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'民心': '==ming'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'region.huguang.unrest': '==ming'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'power.houjin.leverage': '==ming'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'character.毛文龙.personal_skills': '==ming'}},
    {'id': 'e', 'title': 't', 'kind': 'k', 'summary': 's', 'urgency': 1, 'severity': 1, 'credibility': 1, 'trigger_gate': {'character.毛文龙.loyalty': '==active'}},
    {'id': 'bad_person_core_subjects', 'title': '坏人物核心事件', 'kind': 'situation', 'summary': 'x', 'urgency': 50, 'severity': 50, 'credibility': 50, 'interests': [], 'audiences': [], 'person_core_subjects': ''},
])
def test_load_event_fail_loud_on_bad_gate_key(monkeypatch, event_input):
    import ming_sim.content as content_mod
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: [event_input])
    with pytest.raises(SystemExit):
        content_mod.load_event_content("events.json")


@pytest.mark.parametrize("gate", [
    {"region.huguang.grane_security": ">=1"}, {"region.huguang.controled_by": "==ming"},
    {"region.huguang.controlled_by": ">=1"}, {"character.毛文龙.loyalty;DROP": ">=1"},
    {"character.毛文龙.loyalty": "==active"}, {"character.毛文龙.loyality": ">=1"},
    {"character.毛文龙.locaiton": "==liaodong"},
])
def test_typo_field_gate_raises_clear_not_operationalerror(game, gate):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_bad_runtime_gate__", gate)
    content.events.append(ev)
    try:
        with pytest.raises(ValueError):
            issues.gather_candidate_events(state, db)
    finally:
        content.events.remove(ev)


def test_character_numeric_gate_supports_comparison(read_game):
    """character.<name>.<field> 数值字段可参与 trigger_gate 比较（#201）。"""
    from ming_sim.issues import _gate_passed
    db, state, content = read_game

    row = db.conn.execute("SELECT loyalty FROM characters WHERE name = ?", ("毛文龙",)).fetchone()
    assert row is not None, "测试盘面应有毛文龙"

    assert _gate_passed({"character.毛文龙.loyalty": f">={int(row['loyalty'])}"}, state.metrics, db)
    assert not _gate_passed({"character.毛文龙.loyalty": f">{int(row['loyalty'])}"}, state.metrics, db)


@pytest.mark.parametrize("period, event_id, writes", [
    (6, "mao_wenlong", [
        ("UPDATE characters SET loyalty=? WHERE name=?", (70, "毛文龙")),
    ]),
    (6, "mao_wenlong", [
        ("UPDATE characters SET loyalty=?, status=?, location=? WHERE name=?", (44, "active", "dongjiang_area", "毛文龙")),
        ("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕")),
        ("UPDATE armies SET commander=? WHERE id=?", ("孙承宗", "guanning")),
    ]),
    (12, "yuan_xialing", [
        ("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕")),
        ("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning")),
        ("UPDATE characters SET status=?, status_reason=? WHERE name=?", ("dead", "袁崇焕双岛斩帅", "毛文龙")),
    ]),
])
def test_mao_wenlong_event_excluded_after_appeasement(game, period, event_id, writes):
    db, state, content = game
    issues.bind_content(content)
    state.year, state.period = 1629, period
    for query, parameters in writes:
        db.conn.execute(query, parameters)
    cands = issues.gather_candidate_events(state, db)
    assert all(ev.id != event_id for ev in cands)


def test_mao_wenlong_event_remains_candidate_while_player_departure_is_in_transit(game):
    """#667：行止只启程；抵达前 location gate 仍读取原地点。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute(
        "UPDATE characters SET loyalty=?, status=?, location=?, transit_to='' WHERE name=?",
        (44, "active", "dongjiang_area", "毛文龙"),
    )
    content.characters["毛文龙"].loyalty = 44
    content.characters["毛文龙"].status = "active"
    content.characters["毛文龙"].location = "dongjiang_area"
    content.characters["毛文龙"].transit_to = ""

    with _restore_yuan_as_guanning_commander(db, content):
        assert any(ev.id == "mao_wenlong" for ev in issues.gather_candidate_events(state, db))

        applied = _land(
            db,
            state,
            {"人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "行止", "transit_to": "shaanxi", "reason": "启程赴陕西剿抚"}]},
            content=content,
        )

        assert view(applied, "applied_person_changes")
        row = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?",
            ("毛文龙",),
        ).fetchone()
        assert dict(row) == {"location": "dongjiang_area", "transit_to": "shaanxi"}
        assert any(ev.id == "mao_wenlong" for ev in issues.gather_candidate_events(state, db))


def test_mao_wenlong_event_trigger_lands_character_status(game):
    """#203：未安抚时袁斩毛文龙触发后，毛文龙退场事实必须落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (44, "毛文龙"))

    with _restore_yuan_as_guanning_commander(db, content):
        cands = issues.gather_candidate_events(state, db)
        assert any(ev.id == "mao_wenlong" for ev in cands)
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)).fetchone()[0]

        out = apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
            content=content,
        source=Provenance.system_simulation)

        assert "rejected" not in out.new_issues[0]
        assert db.characters.get_character_status("毛文龙")[0] == "dead"
        assert content.characters["毛文龙"].status == "dead"
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs + 1


def test_ordinary_jinzhou_preparedness_delta_is_not_rejected_as_songshan_outcome(game):
    """ship-pre CMR：普通锦州战备整饬不等于松锦决战战果。"""
    db, state, content = game
    issues.bind_content(content)
    before = db.conn.execute(
        "SELECT training FROM armies WHERE id = ?", ("guanning",)
    ).fetchone()["training"]
    origin_ref = _promulgated_dossier(db, state, "整饬锦州战备")

    out = _land(
        db,
        state,
        {"army_delta": {"guanning": {"origin_ref": origin_ref, "training": 5, "reason": "奉旨整饬锦州战备"}}},
        content=content,
    )

    assert db.conn.execute(
        "SELECT training FROM armies WHERE id = ?", ("guanning",)
    ).fetchone()["training"] == before + 5
    assert view(out, "army_changes")


def test_strategic_foreign_event_rejects_trigger_without_world_state_delta(game):
    """#189 CMR：战略/外敌战事不能只记事件触发而无主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = _land(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}]},
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('jisi_lubian', "triggered")


def test_direct_issue_tracker_rejects_strategic_event_without_world_state_delta(game):
    """ship-pre R5：低层 issue applier 也不能绕过战略战事主账门。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}]},
        content=content,
    source=Provenance.system_simulation)

    assert out.new_issues == []
    assert out.rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('jisi_lubian', "triggered")


def test_ordinary_army_station_delta_with_strategic_place_anchor_is_not_rejected(game):
    """ship-pre CMR：普通调防只含战略地名，不得被误当成未触发战役战果。"""
    db, state, content = game
    issues.bind_content(content)
    origin_ref = _promulgated_dossier(db, state, "移镇锦州前屯")

    out = _land(
        db,
        state,
        {
            "army_delta": {
                "guanning": {"origin_ref": origin_ref, "驻扎地": "锦州前屯", "reason": "奉旨移镇锦州前屯"}
            }
        },
        content=content,
    )

    assert db.conn.execute(
        "SELECT station FROM armies WHERE id = ?", ("guanning",)
    ).fetchone()["station"] == "锦州前屯"
    assert view(out, "army_changes")


def test_lindan_xiqian_does_not_capture_untriggered_beizhili_border_policy_delta(game):
    """PR R1：普通北直隶边防政策不能被林丹汗西迁锚点误当成孤儿战果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1632
    state.period = 4
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (30, "beizhili"))

    out = _land(
        db,
        state,
        {
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发", "military_pressure": -3,
                    "reason": "修筑蒙古边墙，北直隶军压下降",
                }
            }
        },
        content=content,
    )

    assert not db.issues.has_event_terminal_state('lindan_xiqian', "triggered")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 27
    assert view(out, "region_changes")


@pytest.mark.parametrize("reason", [
    "修筑洛阳城防，河南军压下降",
    "赈济开封灾民，河南军压下降",
])
def test_henan_place_policy_delta_does_not_capture_untriggered_fall_events(game, reason):
    """PR R2：普通河南治理不能因洛阳/开封地名被误当成孤儿城陷战果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1642
    state.period = 9
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (30, "henan"))

    out = _land(
        db,
        state,
        {
            "region_delta": {
                "henan": {
                    "origin_ref": "盘面自发", "military_pressure": -4,
                    "reason": reason,
                }
            }
        },
        content=content,
    )

    assert not db.issues.has_event_terminal_state('luoyang_fallen', "triggered")
    assert not db.issues.has_event_terminal_state('kaifeng_siege', "triggered")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("henan",)
    ).fetchone()["military_pressure"] == 26
    assert view(out, "region_changes")


def test_unrelated_region_delta_does_not_satisfy_strategic_event_result_gate(game):
    """#189 CMR R2：同信封无关地区变化不能冒充该战略战事的主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "shaanxi"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"shaanxi": {"origin_ref": "盘面自发", "unrest": 1}},
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('jisi_lubian', "triggered")
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("shaanxi",)
    ).fetchone()["unrest"] == 79


def test_target_region_delta_without_event_anchor_does_not_satisfy_strategic_event_result_gate(game):
    """#189 CMR R5：目标地区上的普通变化也不能冒充该战事结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "beizhili"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "unrest": 1, "reason": "ordinary beizhili unrest unrelated to battle"}},
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('jisi_lubian', "triggered")
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["unrest"] == 79
    assert view(out, "region_changes")


def test_unrelated_person_delta_does_not_satisfy_strategic_event_result_gate(game):
    """#189 CMR R4：无关人物变化不能冒充战略战事主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "病重卒于任上"}],
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('jisi_lubian', "triggered")
    assert db.characters.get_character_status("孙传庭")[0] == "dead"
    assert view(out, "applied_person_changes")


def test_rejected_strategic_foreign_event_preserves_unrelated_region_delta(game):
    """#189 CMR R2：战略事件被拒时，只跳过其战果，不能吞掉本月无关地区变化。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "shaanxi"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"shaanxi": {"origin_ref": "盘面自发", "unrest": 1}},
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("shaanxi",)
    ).fetchone()["unrest"] == 79


def test_rejected_strategic_event_preserves_unanchored_target_region_delta(game):
    """#189 CMR R5：战略事件拒收时，目标地区上的无关普通变化仍须落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "beizhili"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "unrest": 1, "reason": "ordinary beizhili unrest unrelated to battle"}},
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["unrest"] == 79
    assert view(out, "region_changes")


def test_rejected_strategic_event_preserves_unrelated_person_delta(game):
    """#189 CMR R4：战略事件重复/拒收时，不能吞掉同信封无关人物变化。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "病重卒于任上"}],
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert db.characters.get_character_status("孙传庭")[0] == "dead"
    assert view(out, "applied_person_changes")


def test_rejected_strategic_event_does_not_land_substitute_commander_person_delta(game):
    """#189 CMR R3：替补将也是战事软判结果；重复/拒收事件不得单独杀人。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 8
    db.mark_event_triggered(state, "songshan_battle")
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "songshan_battle"}],
            "人物变更": [
                {"origin_ref": "盘面自发", "affair_declaration": {"attach": "new"}},
                {"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "松锦替补战死"},
            ],
        },
        content=content,
        ordered_deltas={
            "army_delta": [], "region_delta": [], "power_updates": [],
            "new_armies": [],
        },
        ordered_effect_event_ids={"人物变更": ["", "songshan_battle"]},
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert db.characters.get_character_status("孙传庭")[0] == "active"
    refused_people = section(out, "applied_person_changes").rejected
    assert len(refused_people) == 1
    assert all(
        not (isinstance(rejection.item, dict) and "_effect_event_id" in rejection.item)
        for rejection in out.shape_rejections
    )
    assert refused_people[0].category == "event_rejected"


def test_mao_wenlong_event_trigger_respects_outer_transaction_rollback(game):
    """event trigger 写入不得提前提交；外层 atomic_and_reload 回滚后 DB 与内存同源恢复。"""
    from ming_sim.decree import atomic_and_reload

    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))
    content.characters["毛文龙"].status = "active"

    with _restore_yuan_as_guanning_commander(db, content):
        db.conn.commit()
        before_logs = db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0]

        with pytest.raises(RuntimeError, match="force-rollback"):
            with atomic_and_reload(db, state, content=content):
                out = apply_issue_tracker_output(
                    db,
                    state,
                    {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
                    content=content,
                    source=Provenance.system_simulation,
                )
                assert "rejected" not in out.new_issues[0]
                raise RuntimeError("force-rollback")

        assert db.characters.get_character_status("毛文龙")[0] == "active"
        assert content.characters["毛文龙"].status == "active"
        assert not db.issues.has_event_terminal_state('mao_wenlong', "triggered")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs






def test_event_pool_situation_insert_respects_outer_transaction_rollback(game):
    """post-merge CMR R2：situation 事件立项也不得由 insert_issue 提前提交外层事务。"""
    db, state, content = game
    issues.bind_content(content)
    state.metrics["民心"] = 50
    db.conn.commit()
    ev = Event(
        id="__test_situation_txn__",
        title="测试·situation 事务",
        kind="朝议",
        summary="只用于验证 situation event_pool 事务边界。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        trigger_gate={"民心": ">=0"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        db.conn.execute("BEGIN")
        out = apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": ev.id}]},
            content=content,
        source=Provenance.system_simulation)
        assert "rejected" not in out.new_issues[0]
        db.conn.rollback()

        row = db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone()
        assert row is None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_mao_wenlong_event_pool_rechecks_gate_before_effect(game):
    """#203 CMR：落库端也必须重验 trigger_gate，不能信任 LLM 伪造的候选 id。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (70, "毛文龙"))
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)).fetchone()[0]

    out = apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
        content=content,
    source=Provenance.system_simulation)

    assert out.new_issues == []
    assert out.rejected[0].category == "issue"
    assert db.characters.get_character_status("毛文龙")[0] == "active"
    assert content.characters["毛文龙"].status == "active"
    assert not db.issues.has_event_terminal_state('mao_wenlong', "triggered")
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
    ).fetchone()[0] == before_logs


def test_person_core_event_obsoletes_when_named_subject_is_dead(game):
    """#191：人物核心事件的点名主体永久死亡时，应 durable 作废并退出候选池。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 12
    db.set_character_status(state, "袁崇焕", "dead", reason="测试：提前身故")

    cands = issues.gather_candidate_events(state, db)

    assert all(ev.id != "yuan_xialing" for ev in cands)
    event_terminal.apply_event_terminal_states(state, db)
    row = db.conn.execute(
        "SELECT terminal_state, source FROM event_triggers WHERE event_id=?",
        ("yuan_xialing",),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == "obsolete"
    assert row["source"] == "person_core_dead"

    cands_again = issues.gather_candidate_events(state, db)
    assert all(ev.id != "yuan_xialing" for ev in cands_again)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=?",
        ("yuan_xialing",),
    ).fetchone()[0] == 1


def test_yuan_xialing_event_excluded_after_jisi_border_contained_outcome(game):
    """ADR0014：己巳挡于边墙结局不应打开袁下狱链。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 12
    db.mark_event_triggered(state, "jisi_lubian", terminal_reason="挡于边墙")
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning"))
    db.conn.execute(
        "UPDATE characters SET status=?, status_reason=? WHERE name=?",
        ("dead", "袁崇焕双岛斩帅", "毛文龙"),
    )

    assert all(ev.id != "yuan_xialing" for ev in issues.gather_candidate_events(state, db))


def test_luoyang_fallen_not_obsoleted_when_fu_wang_is_dead(game):
    """#191 CMR：洛阳陷落是城市/流寇压力事件，福王已死不应让事件进入人物核心作废终态。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 1
    db.conn.execute("UPDATE regions SET controlled_by=?, unrest=? WHERE id=?", ("ming", 80, "henan"))
    db.conn.execute("UPDATE powers SET military_strength=? WHERE id=?", (20, "bandits"))
    db.conn.execute("UPDATE powers SET military_strength=? WHERE id=?", (70, "bandit_li_zicheng"))
    db.set_character_status(state, "朱常洵", "dead", reason="测试：此前身故")

    cands = issues.gather_candidate_events(state, db)

    assert any(ev.id == "luoyang_fallen" for ev in cands)
    assert db.conn.execute(
        "SELECT event_id FROM event_triggers WHERE event_id=?",
        ("luoyang_fallen",),
    ).fetchone() is None


def test_li_chenghai_event_opens_after_li_zicheng_historical_debut(game):
    """#191 CMR：李自成入河南不能被默认 offstage 卡死；历史登场后人物核心门应可达。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1634
    state.period = 1
    db.conn.execute("UPDATE powers SET military_strength=? WHERE id=?", (50, "bandit_li_zicheng"))

    debuted = db.apply_historical_debuts(state)
    cands = issues.gather_candidate_events(state, db)

    assert any(item["name"] == "李自成" for item in debuted)
    assert db.characters.get_character_status("李自成")[0] == "active"
    assert any(ev.id == "li_chenghai" for ev in cands)


def test_zhangxianzhong_event_opens_after_historical_debut_and_surrender_path(game):
    """#191 CMR R3：张献忠不能被 offstage+debut 0 卡死；招抚态落库后再反门应可达。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1

    debuted = db.apply_historical_debuts(state)

    assert any(item["name"] == "张献忠" for item in debuted)
    assert db.characters.get_character_status("张献忠")[0] == "active"

    state.year = 1639
    state.period = 5
    db.conn.execute(
        "UPDATE characters SET power_id=?, location=? WHERE name=?",
        ("ming", "huguang", "张献忠"),
    )
    db.conn.execute("UPDATE regions SET unrest=? WHERE id=?", (55, "huguang"))

    assert any(ev.id == "zhangxianzhong_zaifan" for ev in issues.gather_candidate_events(state, db))






def test_strategic_foreign_classification_requires_outcome_targets(content, monkeypatch):
    """PR R3：trigger_class 是内容真源，消费者 target map 漏项必须启动期 fail-loud。"""
    targets = dict(settlement_preflight._STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS)
    targets.pop("luoyang_fallen")
    monkeypatch.setattr(settlement_preflight, "_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS", targets)

    with pytest.raises(SystemExit):
        issues.bind_content(content)


def test_issue_194_dead_named_general_does_not_obsolete_strategic_foreign_event(game):
    """#194：战略/外敌事件点名将是席位/软判对象，不因该将死亡作废。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 8
    db.set_character_status(state, "祖大寿", "dead", reason="测试：大凌河前已阵亡")

    terminalized = event_terminal.apply_event_terminal_states(state, db)
    cands = issues.gather_candidate_events(state, db)

    assert all(item["id"] != "dalingghe" for item in terminalized)
    assert any(ev.id == "dalingghe" for ev in cands)
    row = db.conn.execute(
        "SELECT terminal_state FROM event_triggers WHERE event_id=?",
        ("dalingghe",),
    ).fetchone()
    assert row is None


def test_huabei_plague_auto_triggers_with_deterministic_core_effect(game):
    """#192：华北大疫是天灾核心事实，到点硬触发并落库，不等 LLM 候选记得写。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7
    before = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()

    triggered = issues.auto_trigger_seed_issues(state, db)

    assert any(item["id"] == "huabei_plague" for item in triggered)
    assert db.issues.has_event_terminal_state('huabei_plague', "triggered")
    assert all(ev.id != "huabei_plague" for ev in issues.gather_candidate_events(state, db))
    after = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()
    assert after["population"] == before["population"] - 400000  # #648：新档人口单位=人（ADR 0088），content -40万
    assert after["unrest"] == before["unrest"] + 6


def test_historical_auto_trigger_core_effect_is_applied_once(game, monkeypatch):
    """确定性核心事实与坏后果拒收均遵循事件的硬幂等门。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7
    event = next(ev for ev in content.events if ev.id == "huabei_plague")
    monkeypatch.setattr(event, "effect_on_trigger", {
        **event.effect_on_trigger, "metrics": {"not_a_metric": 1},
    })

    first = issues.auto_trigger_seed_issues(state, db)
    after_first = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()
    second = issues.auto_trigger_seed_issues(state, db)
    after_second = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()

    assert any(item["id"] == "huabei_plague" for item in first)
    assert all(item["id"] != "huabei_plague" for item in second)
    assert dict(after_second) == dict(after_first)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=?",
        ("huabei_plague",),
    ).fetchone()[0] == 1
    reports = db.conn.execute(
        "SELECT item_json, category, turn FROM rejection_reports WHERE section='event_trigger'"
    ).fetchall()
    assert len(reports) == 1
    assert json.loads(reports[0]["item_json"]) == {
        "event_id": event.id, "effect": {"field": "not_a_metric", "raw_value": 1},
    }
    assert reports[0]["category"] == "invalid_enum"
    assert reports[0]["turn"] == state.turn


def test_historical_auto_trigger_event_expires_after_latest_window(game):
    """#188：历史 auto_trigger 也须尊重最晚窗口，过期后不能硬触发。"""
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_expiring_historical_auto__", {"民心": "<=5"})
    ev.trigger_year = 1629
    ev.trigger_month = 1
    ev.trigger_end_year = 1629
    ev.trigger_end_month = 2
    ev.auto_trigger = True
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 3

        triggered = issues.auto_trigger_seed_issues(state, db)

        assert all(item["id"] != "__test_expiring_historical_auto__" for item in triggered)
        assert db.issues.event_terminal_state("__test_expiring_historical_auto__") == "expired"
        assert IssueStore(db.conn).by_origin(("event_pool", "__test_expiring_historical_auto__")) is None
    finally:
        content.events.remove(ev)


def test_huabei_plague_keeps_soft_degree_axis_as_situation_issue(game):
    """#192：天灾核心事实硬落后，蔓延/赈疫程度轴仍留 active issue 给软判推进。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7

    triggered = issues.auto_trigger_seed_issues(state, db)

    item = next(entry for entry in triggered if entry["id"] == "huabei_plague")
    assert item["issue_id"] > 0
    issue = db.conn.execute(
        "SELECT status, kind, origin_kind, origin_ref FROM issues WHERE id=?",
        (item["issue_id"],),
    ).fetchone()
    assert dict(issue) == {
        "status": "active",
        "kind": "situation",
        "origin_kind": "event_pool",
        "origin_ref": "huabei_plague",
    }


def test_historical_situation_auto_trigger_rolls_back_soft_issue_when_core_effect_fails(game, monkeypatch):
    """CMR：核心事实落库失败时，不能留下已建软 issue 但未标 trigger 的半状态。"""
    import pytest

    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7

    def boom(*args, **kwargs):
        raise RuntimeError("boom after issue insert")

    import ming_sim.entities.issue.effects as issue_effects

    monkeypatch.setattr(issue_effects, "_apply_issue_entities", boom)

    with pytest.raises(RuntimeError):
        issues.auto_trigger_seed_issues(state, db)

    assert db.conn.execute(
        "SELECT 1 FROM issues WHERE origin_kind=? AND origin_ref=?",
        ("event_pool", "huabei_plague"),
    ).fetchone() is None
    assert not db.issues.has_event_terminal_state('huabei_plague', "triggered")


def test_historical_situation_auto_trigger_backfills_core_effect_for_existing_soft_issue(game):
    """CMR：旧存档已有同源 soft issue 经 schema migration 后，仍须补落核心事实。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7
    existing_issue_id = db.insert_issue(
        state,
        kind="situation",
        title="旧存档残留：华北大疫起",
        origin_kind="event_pool",
        origin_ref="huabei_plague",
        bar_value=40,
    )
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("huabei_plague",),
    ).fetchone() is None

    db.init_schema()
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("huabei_plague",),
    ).fetchone() is None

    before = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()

    triggered = issues.auto_trigger_seed_issues(state, db)

    item = next(entry for entry in triggered if entry["id"] == "huabei_plague")
    assert item["issue_id"] == existing_issue_id
    assert db.issues.has_event_terminal_state('huabei_plague', "triggered")
    after = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()
    assert after["population"] == before["population"] - 400000  # #648：新档人口单位=人（ADR 0088），content -40万
    assert after["unrest"] == before["unrest"] + 6


def test_jingshi_plague_auto_triggers_and_weakens_capital_garrison(game):
    """#192：京师大疫核心事实直接削京营，不靠 LLM 记得为甲申链写状态。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1643
    state.period = 3
    before = db.conn.execute(
        "SELECT manpower, morale FROM armies WHERE id=?",
        ("jingying",),
    ).fetchone()

    triggered = issues.auto_trigger_seed_issues(state, db)

    assert any(item["id"] == "jingshi_plague" for item in triggered)
    assert db.issues.has_event_terminal_state('jingshi_plague', "triggered")
    assert all(ev.id != "jingshi_plague" for ev in issues.gather_candidate_events(state, db))
    after = db.conn.execute(
        "SELECT manpower, morale FROM armies WHERE id=?",
        ("jingying",),
    ).fetchone()
    assert after["manpower"] == before["manpower"] - 51000
    assert after["morale"] == before["morale"] - 16


def test_mao_wenlong_event_pool_uses_candidate_snapshot_before_advances(game):
    """post-merge CMR：同一 payload 的 advances 不能先打开 event_pool gate 再立刻触发。"""
    db, state, content = game
    issues.bind_content(content)
    state.metrics["民心"] = 20
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·候选池快照推进",
        origin_kind="decree",
        bar_value=40,
        stage_text="尚未触发",
        effect_on_resolve={"metrics": {"民心": 1}},
    )
    ev = Event(
        id="__test_candidate_snapshot__",
        title="测试·候选池快照",
        kind="朝议",
        summary="只用于验证候选池快照。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="node",
        trigger_gate={"民心": "<=10"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert all(c.id != ev.id for c in issues.gather_candidate_events(state, db))

        out = apply_issue_tracker_output(
            db,
            state,
            {
                "advances": [{"issue_id": issue_id, "delta_bar": 1, "metric_delta": {"民心": -15}}],
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
            },
            content=content,
        source=Provenance.system_simulation)

        assert state.metrics["民心"] == 5
        assert out.new_issues == []
        assert out.rejected[0].category == "issue"
        assert not db.issues.has_event_terminal_state(ev.id, "triggered")
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_uses_candidate_snapshot_before_top_level_metric_delta(game):
    """post-merge CMR R3：顶层 metric_delta 不能先打开 event_pool gate 再触发。"""
    db, state, content = game
    issues.bind_content(content)
    state.metrics["民心"] = 20
    ev = Event(
        id="__test_top_level_metric_snapshot__",
        title="测试·顶层数值快照",
        kind="朝议",
        summary="只用于验证顶层 metric_delta 前的候选池快照。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="node",
        trigger_gate={"民心": "<=10"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert all(c.id != ev.id for c in issues.gather_candidate_events(state, db))

        out = _land(
            db,
            state,
            {
                "metric_delta": {"民心": -15},
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
            },
            content=content,
        )

        assert state.metrics["民心"] == 5
        assert section(out, "issue_summary").rejected
        assert section(out, "issue_summary").rejected[0].category == "issue"
        assert not db.issues.has_event_terminal_state(ev.id, "triggered")
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_rechecks_after_advances_close_gate(game):
    """post-merge CMR R4：同一 payload 的 advances 关掉 gate 后，不得沿用旧候选触发事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.metrics["民心"] = 20
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·推进关闭候选",
        origin_kind="decree",
        bar_value=40,
        stage_text="尚未触发",
        effect_on_resolve={"metrics": {"民心": 1}},
    )
    ev = Event(
        id="__test_advances_close_gate__",
        title="测试·推进关闭候选",
        kind="朝议",
        summary="只用于验证 advances 后重验候选池。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="node",
        trigger_gate={"民心": ">=10"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert any(c.id == ev.id for c in issues.gather_candidate_events(state, db))

        out = apply_issue_tracker_output(
            db,
            state,
            {
                "advances": [{"issue_id": issue_id, "delta_bar": 1, "metric_delta": {"民心": -15}}],
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
            },
            content=content,
        source=Provenance.system_simulation)

        assert state.metrics["民心"] == 5
        assert out.new_issues == []
        assert out.rejected[0].category == "issue"
        assert not db.issues.has_event_terminal_state(ev.id, "triggered")
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_rechecks_after_prior_event_effect_closes_gate(game):
    """post-merge CMR R5：同一 payload 前一事件效果关门后，后一事件不得沿用旧候选。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))
    first = Event(
        id="__test_prior_event_closes_gate__",
        title="测试·前置人物变更",
        kind="朝议",
        summary="先改变人物状态。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="node",
        trigger_gate={"民心": ">=0"},
        effect_on_trigger={
            "人物变更": [
                {"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "测试撤任"}
            ]
        },
    )
    second = Event(
        id="__test_later_event_requires_yuan_active__",
        title="测试·后置袁门",
        kind="朝议",
        summary="袁崇焕仍在任时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.status": "== active"},
    )
    content.seed_events.extend([first, second])
    content.event_by_id[first.id] = first
    content.event_by_id[second.id] = second
    try:
        cands = issues.gather_candidate_events(state, db)
        assert {first.id, second.id}.issubset({c.id for c in cands})

        out = apply_issue_tracker_output(
            db,
            state,
            {
                "new_issues": [
                    {"origin_kind": "event_pool", "id": first.id},
                    {"origin_kind": "event_pool", "id": second.id},
                ]
            },
            content=content,
        source=Provenance.system_simulation)

        assert "rejected" not in out.new_issues[0]
        assert db.characters.get_character_status("袁崇焕")[0] == "dismissed"
        assert len(out.new_issues) == 1
        assert out.rejected[0].category == "issue"
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (second.id,),
        ).fetchone() is None
    finally:
        content.seed_events.remove(first)
        content.seed_events.remove(second)
        content.event_by_id.pop(first.id, None)
        content.event_by_id.pop(second.id, None)


def test_issue_tracker_decree_new_issue_respects_outer_transaction_rollback(game):
    """post-merge CMR R5：decree 新立 issue 也不得由 insert_issue 提前提交外层事务。"""
    db, state, _content = game
    origin_ref = _promulgated_dossier(db, state, "测试 decree 新立事务")
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = apply_issue_tracker_output(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin_ref,
                    "kind": "situation",
                    "title": "测试·decree 新立事务",
                    "bar_value": 25,
                    "stage_text": "立项中",
                    "effect_on_resolve": {"metrics": {"民心": 1}},
                }
            ]
        },
    source=Provenance.system_simulation)
    assert "rejected" not in out.new_issues[0]
    issue_id = out.new_issues[0]["issue_id"]
    db.conn.rollback()

    assert db.conn.execute("SELECT id FROM issues WHERE id=?", (issue_id,)).fetchone() is None


def test_issue_tracker_advance_effects_respect_outer_transaction_rollback(game):
    """post-merge CMR R5：advance 触发的终结经济效果不得提前提交外层事务。"""
    db, state, _content = game
    reason = "测试推进经济事务R5"
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·推进终结效果事务",
        origin_kind="decree",
        bar_value=95,
        stage_text="将成",
        effect_on_resolve={"economy": [{"account": "国库", "delta": -1, "category": "测试", "reason": reason}]},
    )
    before_advances = db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0]
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = apply_issue_tracker_output(
        db,
        state,
        {"advances": [{"issue_id": issue_id, "delta_bar": 10, "stage_text": "办成"}]},
    source=Provenance.system_simulation)
    assert out.advances[0]["status"] == "resolved"
    db.conn.rollback()

    row = db.conn.execute("SELECT bar_value, stage_text, status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert dict(row) == {"bar_value": 95, "stage_text": "将成", "status": "active"}
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0] == before_advances
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0


def test_issue_tracker_close_effects_respect_outer_transaction_rollback(game):
    """post-merge CMR R5：close 终结效果的经济/建筑/派系/遗产写入必须跟外层事务回滚。"""
    db, state, _content = game
    reason = "测试结案复合效果事务R5"
    building_id = db.add_building(
        state,
        region_id="beizhili",
        name="测试事务仓",
        category="财政",
        condition=70,
        origin="test",
    )
    faction_before = db.conn.execute(
        "SELECT satisfaction, leverage_offset FROM factions WHERE name='阉党'"
    ).fetchone()
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·结案复合事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="结案前",
        effect_on_resolve={
            "economy": [{"account": "国库", "delta": -1, "category": "测试", "reason": reason}],
            "buildings": [{"action": "modify", "building_id": building_id, "condition": -7}],
            "factions": {"阉党": {"satisfaction": -1, "leverage": 1}},
            "legacy": {"name": "测试遗产R5", "duration": "1年", "modifiers": {"国库": 1}},
        },
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    source=Provenance.system_simulation)
    assert out.closes[0]["reason"] == "resolved"
    db.conn.rollback()

    issue_row = db.conn.execute("SELECT status, bar_value FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert dict(issue_row) == {"status": "active", "bar_value": 40}
    building_row = db.conn.execute("SELECT condition FROM buildings WHERE id=?", (building_id,)).fetchone()
    assert int(building_row["condition"]) == 70
    faction_after = db.conn.execute(
        "SELECT satisfaction, leverage_offset FROM factions WHERE name='阉党'"
    ).fetchone()
    assert dict(faction_after) == dict(faction_before)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM legacies WHERE name='测试遗产R5'"
    ).fetchone()[0] == 0


def test_issue_tracker_close_entity_effects_respect_outer_transaction_rollback(game):
    """post-merge CMR R5：close 终结实体后果建军也必须跟外层事务回滚。"""
    db, state, _content = game
    army_id = "__test_close_entity_txn_army__"
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="测试·结案实体事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="结案前",
        effect_on_resolve={
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": army_id,
                    "name": "测试事务营",
                    "manpower": 1200,
                    "owner_power": "ming",
                    "pay_source_region": "shaanxi",
                    "province_pay_share": 1.0,
                    "central_pay_share": 0.0,
                    "reason": "测试建军事务",
                }
            ]
        },
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    source=Provenance.system_simulation)
    assert out.closes[0]["reason"] == "resolved"
    db.conn.rollback()

    issue_row = db.conn.execute("SELECT status, bar_value FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert dict(issue_row) == {"status": "active", "bar_value": 40}
    assert db.conn.execute("SELECT id FROM armies WHERE id=?", (army_id,)).fetchone() is None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=?",
        (army_id,),
    ).fetchone()[0] == 0


def test_issue_tracker_close_legacy_expiry_respects_outer_transaction_rollback(game):
    """post-merge CMR R6：终结效果读 legacy_modifiers 时过期清理不得提前提交外层事务。"""
    db, state, _content = game
    reason = "测试遗产过期事务R6"
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·遗产过期事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="结案前",
        effect_on_resolve={
            "economy": [{"account": "国库", "delta": -1, "category": "测试", "reason": reason}]
        },
    )
    legacy_id = db.insert_legacy(
        state,
        name="测试过期遗产R6",
        modifiers={"国库": 1},
        duration_months=0,
        source_issue_id=issue_id,
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    source=Provenance.system_simulation)
    assert out.closes[0]["reason"] == "resolved"
    db.conn.rollback()

    issue_row = db.conn.execute("SELECT status, bar_value FROM issues WHERE id=?", (issue_id,)).fetchone()
    legacy_row = db.conn.execute("SELECT status FROM legacies WHERE id=?", (legacy_id,)).fetchone()
    assert dict(issue_row) == {"status": "active", "bar_value": 40}
    assert legacy_row["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0




def test_apply_score_extraction_top_level_economy_respects_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 economy_moves 不得自行提交外层事务。"""
    db, state, content = game
    reason = "测试顶层经济事务R7"
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = _land(
        db,
        state,
        {"economy_moves": [{"origin_ref": "盘面自发", "account": "国库", "delta": -1, "category": "测试", "reason": reason}]},
        content=content,
    )
    assert view(out, "economy_moves")[0]["reason"] == reason
    db.conn.rollback()

    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0


def test_apply_score_extraction_fiscal_changes_respect_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 fiscal_changes 不得由 fiscal_config helper 提前提交。"""
    db, state, content = game
    key, before = next(iter(db.fiscal_config.values().items()))
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = _land(
        db,
        state,
        {"fiscal_changes": [{"origin_ref": "盘面自发", "key": key, "delta": 1, "reason": "测试顶层财政事务R7"}]},
        content=content,
    )
    assert view(out, "fiscal_changes")[0]["key"] == key
    db.conn.rollback()

    assert db.fiscal_config.values()[key] == before


def test_apply_score_extraction_class_delta_respects_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 class_delta 不得由 classes helper 提前提交。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT name, region_id, satisfaction FROM classes ORDER BY region_id, name LIMIT 1"
    ).fetchone()
    assert row is not None
    class_key = str(row["name"])
    if str(row["region_id"] or ""):
        class_key = f"{class_key}@{row['region_id']}"
    before = int(row["satisfaction"])
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = _land(
        db,
        state,
        {"class_delta": {class_key: {"satisfaction": -1}}},
        content=content,
    )
    assert {k: v for k, v in out.social_class.applied}[class_key]["satisfaction"] == -1
    db.conn.rollback()

    if row["region_id"] is None:
        after_row = db.conn.execute(
            "SELECT satisfaction FROM classes WHERE name=? AND region_id IS NULL",
            (row["name"],),
        ).fetchone()
    else:
        after_row = db.conn.execute(
            "SELECT satisfaction FROM classes WHERE name=? AND region_id=?",
            (row["name"], row["region_id"]),
        ).fetchone()
    assert after_row is not None
    after = after_row["satisfaction"]
    assert int(after) == before


def test_apply_score_extraction_top_level_entity_deltas_respect_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 region/army/power/faction/new_armies 共享外层事务。"""
    db, state, content = game
    region = db.conn.execute(
        "SELECT id, unrest FROM regions WHERE unrest < 100 ORDER BY id LIMIT 1"
    ).fetchone()
    army = db.conn.execute(
        "SELECT id, manpower FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    power = db.conn.execute(
        "SELECT id, leverage FROM powers WHERE id!='ming' AND leverage < 100 ORDER BY id LIMIT 1"
    ).fetchone()
    faction = db.conn.execute(
        "SELECT name, satisfaction FROM factions WHERE satisfaction > 0 ORDER BY name LIMIT 1"
    ).fetchone()
    assert region is not None and army is not None and power is not None and faction is not None
    new_army_id = "__test_top_level_entity_txn_army__"
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = _land(
        db,
        state,
        {
            "region_delta": {region["id"]: {"origin_ref": "盘面自发", "unrest": 1, "reason": "测试顶层地区事务R7"}},
            "army_delta": {army["id"]: {"origin_ref": "盘面自发", "manpower": 1, "reason": "测试顶层军队事务R7"}},
            "power_updates": {power["id"]: {"origin_ref": "盘面自发", "leverage": 1, "reason": "测试顶层势力事务R7"}},
            "faction_delta": {faction["name"]: {"satisfaction": -1}},
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": new_army_id,
                    "name": "测试顶层事务营",
                    "owner_power": "ming",
                    "manpower": 100,
                    "pay_source_region": "shaanxi",
                    "province_pay_share": 1.0,
                    "central_pay_share": 0.0,
                    "reason": "测试顶层建军事务R7",
                }
            ],
        },
        content=content,
    )
    assert view(out, "region_changes")
    assert view(out, "army_changes")
    assert view(out, "power_changes")
    assert {k: v for k, v in out.faction.applied}
    assert any(
        isinstance(item, dict) and item.get("id") == new_army_id
        for item in view(out, "army_changes")
    )
    db.conn.rollback()

    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id=?",
        (region["id"],),
    ).fetchone()["unrest"] == region["unrest"]
    assert db.conn.execute(
        "SELECT manpower FROM armies WHERE id=?",
        (army["id"],),
    ).fetchone()["manpower"] == army["manpower"]
    assert db.conn.execute(
        "SELECT leverage FROM powers WHERE id=?",
        (power["id"],),
    ).fetchone()["leverage"] == power["leverage"]
    assert db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?",
        (faction["name"],),
    ).fetchone()["satisfaction"] == faction["satisfaction"]
    assert db.conn.execute("SELECT id FROM armies WHERE id=?", (new_army_id,)).fetchone() is None


def test_apply_score_extraction_fiscal_create_and_remove_respect_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 fiscal_creates/removes 不得由财政 helper 提前提交。"""
    db, state, content = game
    remove_key = next(iter(db.fiscal_config.values()))
    created_key = "__test_fiscal_txn_r7_base"
    created_rate_key = "__test_fiscal_txn_r7_rate"
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = _land(
        db,
        state,
        {
            "fiscal_removes": [{"origin_ref": "盘面自发", "key": remove_key, "reason": "测试顶层财政裁撤事务R7"}],
            "fiscal_creates": [
                {
                    "origin_ref": "盘面自发", "key": created_key,
                    "account": "国库",
                    "direction": "income",
                    "display": "测试顶层财政",
                    "init_value": 1,
                    "reason": "测试顶层财政新立事务R7",
                }
            ],
        },
        content=content,
    )
    assert view(out, "fiscal_removes")[0]["key"] == f"{db._stem_of(remove_key)}_base"
    assert view(out, "fiscal_creates")[0]["key"] == created_key
    db.conn.rollback()

    assert remove_key in db.fiscal_config.values()
    assert db.conn.execute(
        "SELECT key FROM fiscal_config WHERE key IN (?, ?)",
        (created_key, created_rate_key),
    ).fetchall() == []
















def test_apply_score_extraction_appointment_rolls_back_with_outer_transaction(game):
    """外层事务回滚时，任命的 DB 与内存身份均回到旧值。"""
    import pytest

    from ming_sim.applier import atomic

    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "内阁首辅", "内阁", "韩爌"),
    )
    db.conn.commit()
    content.characters["韩爌"].status = "active"
    content.characters["韩爌"].power_id = "ming"
    content.characters["韩爌"].office = "内阁首辅"
    content.characters["韩爌"].office_type = "内阁"

    with pytest.raises(RuntimeError):
        with atomic(db):
            _land(
                db,
                state,
                {"人物变更": [{"origin_ref": "盘面自发", "name": "韩爌", "动作": "任命", "office": "兵部尚书"}]},
                content=content,
            )
            assert content.characters["韩爌"].office == "兵部尚书"
            raise RuntimeError("rollback appointment probe")

    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?",
        ("韩爌",),
    ).fetchone()["office"] == "内阁首辅"
    assert content.characters["韩爌"].office == "内阁首辅"














def test_issue_tracker_cancel_cost_respects_outer_transaction_rollback(game):
    """post-merge CMR R5：cancel applied_cost 的经济效果不得提前提交外层事务。"""
    db, state, _content = game
    reason = "测试撤办经济事务R5"
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="测试·撤办成本事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="撤办前",
        cancellable="decree",
        effect_on_resolve={"metrics": {"民心": 1}},
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = apply_issue_tracker_output(
        db,
        state,
        {
            "cancels": [
                {
                    "issue_id": issue_id,
                    "narrative": "撤办",
                    "applied_cost": {
                        "economy": [{"account": "国库", "delta": -1, "category": "测试", "reason": reason}]
                    },
                }
            ]
        },
    source=Provenance.system_simulation)
    assert "rejected" not in out.cancels[0]
    db.conn.rollback()

    row = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0


def test_mao_wenlong_event_pool_rechecks_after_same_turn_loyalty_assessment(game):
    """post-merge CMR：同回合人物评定应先影响 event_pool 前提门。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (60, "active", "毛文龙"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "评定", "loyalty": 10, "reason": "同回合安抚见效"}],
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('mao_wenlong', "triggered")
    assert db.characters.get_character_status("毛文龙")[0] == "active"
    assert db.conn.execute("SELECT loyalty FROM characters WHERE name=?", ("毛文龙",)).fetchone()["loyalty"] == 70


def test_mao_wenlong_event_pool_rechecks_after_same_turn_yuan_dismissal(game):
    """post-merge CMR R2：同回合袁崇焕退场应阻断袁斩毛文龙事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))

    out = _land(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "同回合罢离督师"}],
        },
        content=content,
    )

    assert section(out, "issue_summary").rejected
    assert section(out, "issue_summary").rejected[0].category == "issue"
    assert not db.issues.has_event_terminal_state('mao_wenlong', "triggered")
    assert db.characters.get_character_status("毛文龙")[0] == "active"
    assert db.characters.get_character_status("袁崇焕")[0] == "dismissed"




def test_mao_wenlong_event_obsolete_when_core_subject_already_dead(game):
    """#191：毛文龙已永久死亡时，斩毛人物核心事件应作废而非只当回合空判。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute(
        "UPDATE characters SET loyalty = ?, status = ? WHERE name = ?",
        (44, "dead", "毛文龙"),
    )

    cands = issues.gather_candidate_events(state, db)
    assert all(ev.id != "mao_wenlong" for ev in cands)

    event_terminal.apply_event_terminal_states(state, db)

    out = apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
        content=content,
    source=Provenance.system_simulation)

    assert out.new_issues == []
    assert out.rejected[0].category == "issue"
    assert db.characters.get_character_status("毛文龙")[0] == "dead"
    row = db.conn.execute(
        "SELECT terminal_state, source FROM event_triggers WHERE event_id=?",
        ("mao_wenlong",),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == "obsolete"
    assert row["source"] == "person_core_dead"


def test_mao_wenlong_event_excluded_when_yuan_unavailable(game):
    """#187 ship-pre：袁崇焕不在 active 位时，不应发生袁崇焕斩毛文龙。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6

    for yuan_status in ("dismissed", "imprisoned", "exiled", "retired", "offstage", "dead"):
        db.conn.execute(
            "UPDATE characters SET loyalty = ?, status = ? WHERE name = ?",
            (44, "active", "毛文龙"),
        )
        db.conn.execute(
            "UPDATE characters SET status = ? WHERE name = ?",
            (yuan_status, "袁崇焕"),
        )
        before_logs = db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0]

        cands = issues.gather_candidate_events(state, db)
        assert all(ev.id != "mao_wenlong" for ev in cands), yuan_status

        out = apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
            content=content,
        source=Provenance.system_simulation)

        assert out.new_issues == []
        assert out.rejected[0].category == "issue"
        assert db.characters.get_character_status("毛文龙")[0] == "active"
        assert content.characters["毛文龙"].status == "active"
        assert not db.issues.has_event_terminal_state('mao_wenlong', "triggered")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs


def test_mao_wenlong_event_pool_duplicate_emit_is_idempotent(game):
    """#203 CMR：同一轮重复 emit 已触发事件时，第二条应拒收留痕而不是 abort。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (44, "毛文龙"))

    with _restore_yuan_as_guanning_commander(db, content):
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)).fetchone()[0]

        out = apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [
                {"origin_kind": "event_pool", "id": "mao_wenlong"},
                {"origin_kind": "event_pool", "id": "mao_wenlong"},
            ]},
            content=content,
        source=Provenance.system_simulation)

        assert "rejected" not in out.new_issues[0]
        assert len(out.new_issues) == 1
        assert out.rejected[0].category == "issue"
        assert db.characters.get_character_status("毛文龙")[0] == "dead"
        assert content.characters["毛文龙"].status == "dead"
        assert db.issues.has_event_terminal_state('mao_wenlong', "triggered")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs + 1

def test_huangtaiji_chengdi_lands_only_when_model_picks_it(game, monkeypatch):
    """#1893/#192：称帝不选不落、选中一次落定——两向都走真实接缝。

    旧断链有两处，且都在本用例须穿过的接缝上：月初 ``GameSession.begin_turn``
    按日期自动改名（不选也发生），以及模型选中后局势/改名不随既有写口落账。
    故此处不另造旁路断言：先走 begin_turn（历史故障所在入口），再走
    ``dispatch_month_segment``（模型挑选所在入口），在外部可见结果上双向钉死。
    """
    from ming_sim.month_translate import dispatch_month_segment
    from ming_sim.decree import prepare_resolve_front_half
    from ming_sim.session import GameSession
    import ming_sim.session as session_mod

    db, state, content = game
    issues.bind_content(content)
    state.year, state.period = 1636, 4
    db.reign.save_game_state(state)

    def _power_name():
        return db.conn.execute(
            "SELECT name, aliases, status FROM powers WHERE id='houjin'",
        ).fetchone()

    assert _power_name()["name"] == "后金", "本用例以未选中的后金为起点，起点已变则本用例空转"

    # 不选：经真实 begin_turn 入口，日期到了也不改名、不发终态，候选仍在池里可挑。
    # 用 __new__ 跳过重型 __init__（agno/registry/LLM），只装 begin_turn 需要的协作者。
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl", lambda *a, **k: None)
    monkeypatch.setattr(GameSession, "auto_save", lambda self, tag: None)
    sess = GameSession.__new__(GameSession)
    sess.db, sess.content, sess.llm_config, sess.agno_db = db, content, None, None
    sess.begin_turn()
    state = sess.state
    prepare_resolve_front_half(state, db, decree_text="", content=content)

    assert _power_name()["name"] == "后金"
    assert db.issues.event_terminal_state("huangtaiji_chengdi") is None
    assert db.issues.by_origin(('event_pool', 'huangtaiji_chengdi')) is None
    assert "huangtaiji_chengdi" in {
        ev.id for ev in issues.gather_candidate_events(state, db)
    }
    assert all(
        item["id"] != "huangtaiji_chengdi"
        for item in issues.auto_trigger_seed_issues(state, db)
    )

    # 选：经真实 dispatch_month_segment 入口落一次终态、局势与改国号。
    declaration = {"effects": {"new_issues": [{
        "origin_kind": "event_pool", "id": "huangtaiji_chengdi",
        "title": "皇太极称帝改国号大清",
    }]}}
    stub_month_translate(monkeypatch, lambda request, config: declaration)
    result = dispatch_month_segment(db, state, segment="皇太极称帝")
    outcome = result.effects.applied[0]
    assert outcome.issue.new_issues
    assert not section(outcome, "issue_summary").rejected
    assert db.issues.event_terminal_state("huangtaiji_chengdi") == "triggered"
    row = _power_name()
    assert row["name"] == "大清"
    assert "后金" in row["aliases"] and "大清" in row["aliases"]
    # #192：承不承认伪号/联蒙抗清仍是要软判推进的局势，不是即时结清的硬事件。
    issue = db.conn.execute(
        "SELECT status, kind, origin_kind, origin_ref FROM issues WHERE origin_ref=?",
        ("huangtaiji_chengdi",),
    ).fetchone()
    assert dict(issue) == {
        "status": "active",
        "kind": "situation",
        "origin_kind": "event_pool",
        "origin_ref": "huangtaiji_chengdi",
    }

    # 读档续跑不重发：终态已在候选硬门里排掉。
    issues.auto_trigger_seed_issues(state, db)
    assert "huangtaiji_chengdi" not in {
        ev.id for ev in issues.gather_candidate_events(state, db)
    }
    again = dispatch_month_segment(db, state, segment="再说称帝")
    again_outcome = again.effects.applied[0]
    assert section(again_outcome, "issue_summary").rejected or not again_outcome.issue.new_issues
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
        ("huangtaiji_chengdi",),
    ).fetchone()[0] == 1


@pytest.mark.parametrize('event_id,setup', [('korea_envoy', lambda db: db.conn.execute("UPDATE powers SET leverage=80 WHERE id='houjin'")), ('houjin_split', lambda db: db.conn.execute("UPDATE powers SET cohesion=50 WHERE id='houjin'")), ('jiangnan_gentry_revolt', lambda db: db.conn.executemany("UPDATE classes SET satisfaction=20 WHERE name='士绅' AND region_id=?", [('nanzhili',), ('zhejiang',), ('fujian',)]))])
def test_person_events_are_model_candidates_not_engine_hard_fired(game, event_id, setup):
    """#1892 J2：有人拍板者的人物事件迁出 auto_trigger——引擎不硬发，只作候选交模型选。

    门槛达标时若仍被引擎硬发，等于代码替人物（朝鲜仁祖／后金贝勒／江南士绅）拍板。
    """
    db, state, content = game
    issues.bind_content(content)
    state.year = 1628
    state.period = 6
    db.reign.save_game_state(state)
    setup(db)
    db.conn.commit()
    triggered = issues.auto_trigger_seed_issues(state, db)
    assert all((item['id'] != event_id for item in triggered))
    assert db.issues.event_terminal_state(event_id) is None
    assert db.conn.execute("SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=? LIMIT 1", (event_id,)).fetchone() is None
    assert event_id in {ev.id for ev in issues.gather_candidate_events(state, db)}

def _land(db, state, extracted, *, content=None, ordered_deltas=None,
          ordered_effect_event_ids=None):
    """直调落账缝：旧总入口已退役，测试走 settle_delta。"""
    return settle_delta(
        state, db, extracted, SettlementContext(content=content),
        ordered_deltas=ordered_deltas,
        ordered_effect_event_ids=ordered_effect_event_ids,
    )


def test_character_numeric_gate_supports_aggregation(game):
    """character.<name>|<name>.<field>.<agg> 与其它 gate 表同样支持聚合。"""
    from ming_sim.issues import _gate_passed
    db, state, _content = game

    db.conn.execute("UPDATE characters SET loyalty=? WHERE name=?", (40, "毛文龙"))
    db.conn.execute("UPDATE characters SET loyalty=? WHERE name=?", (80, "袁崇焕"))
    db.conn.commit()

    assert _gate_passed({"character.毛文龙|袁崇焕.loyalty.avg": ">=60"}, state.metrics, db)
    assert not _gate_passed({"character.毛文龙|袁崇焕.loyalty.min": ">=60"}, state.metrics, db)


def test_army_numeric_gate_preserves_fractional_arrears_tail(game):
    """#302 cmr：并轨后 armies.arrears 可为小数尾差，trigger_gate 不得 int 截断成 0。"""
    from ming_sim.issues import _gate_passed
    db, state, _content = game

    army_id = db.conn.execute("SELECT id FROM armies ORDER BY id LIMIT 1").fetchone()["id"]
    db.conn.execute('UPDATE armies SET province_pay_arrears=0, central_pay_arrears=? WHERE id=?', (0.5, army_id))
    db.conn.commit()

    assert not _gate_passed({f"army.{army_id}.arrears": "<=0"}, state.metrics, db)
    assert _gate_passed({f"army.{army_id}.arrears": ">0"}, state.metrics, db)


def test_character_text_gate_supports_equality(game):
    """character.<name>.<field> 文本字段可参与 trigger_gate 相等/不等比较（#201）。"""
    from ming_sim.issues import _gate_passed
    db, state, content = game

    db.conn.execute("UPDATE characters SET location = ? WHERE name = ?", ("liaodong", "毛文龙"))

    assert _gate_passed({"character.毛文龙.location": "==liaodong"}, state.metrics, db)
    assert _gate_passed({"character.毛文龙.location": "!=capital"}, state.metrics, db)
    assert not _gate_passed({"character.毛文龙.location": "==capital"}, state.metrics, db)


def test_apply_score_extraction_metric_delta_restores_runtime_via_outer_reload(game):
    """整事务回滚后内存由最外层 atomic_and_reload 同源重载，不靠 settle 全批快照。"""
    from ming_sim.decree import atomic_and_reload

    db, state, content = game
    state.metrics["民心"] = 50
    db.conn.execute("UPDATE metrics SET value=? WHERE key=?", (50, "民心"))
    db.conn.commit()

    with pytest.raises(RuntimeError, match="force-rollback"):
        with atomic_and_reload(db, state, content=content):
            out = _land(
                db,
                state,
                {"metric_delta": {"民心": -7}},
                content=content,
            )
            assert dict(out.metric.applied)["民心"] == -7
            assert state.metrics["民心"] == 43
            raise RuntimeError("force-rollback")

    assert state.metrics["民心"] == 50


def test_auto_trigger_historical_events_use_preloaded_terminal_refs(game, monkeypatch):
    """PR review：历史 auto_trigger 去重应批量读 event_triggers，避免每事件查 terminal_state。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7

    def _unexpected_per_event_probe(*_args, **_kwargs):
        raise AssertionError("auto_trigger historical loop must not call event_terminal_state per event")

    monkeypatch.setattr(type(db.issues), "event_terminal_state", _unexpected_per_event_probe)

    triggered = issues.auto_trigger_seed_issues(state, db)

    assert any(item["id"] == "huabei_plague" for item in triggered)


def test_apply_score_extraction_person_changes_respect_outer_transaction_rollback(game):
    """顶层人物变更不得自行提交外层事务（真实 settle_delta 入口，非 helper 自持生命周期）。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "毛文龙"))
    db.conn.commit()
    before_logs = db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?",
        ("毛文龙",),
    ).fetchone()[0]

    db.conn.execute("BEGIN")
    out = _land(
        db,
        state,
        {
            "人物变更": [
                {
                    "origin_ref": "盘面自发",
                    "name": "毛文龙",
                    "动作": "处置",
                    "status": "dismissed",
                    "reason": "测试外层人物回滚",
                }
            ]
        },
        content=content,
    )
    assert view(out, "applied_person_changes")
    assert db.characters.get_character_status("毛文龙")[0] == "dismissed"
    db.conn.rollback()

    assert db.characters.get_character_status("毛文龙")[0] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?",
        ("毛文龙",),
    ).fetchone()[0] == before_logs


def test_event_pool_current_candidate_recheck_cached_until_state_changes(game, monkeypatch):
    """online R2 Gemini：同一批无状态变化的 event_pool 项不应重复重算候选池。"""
    db, state, content = game
    issues.bind_content(content)
    ev1 = Event(
        id="__test_cached_current_candidate_1__",
        title="测试·候选缓存一",
        kind="朝议",
        summary="x",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
    )
    ev2 = Event(
        id="__test_cached_current_candidate_2__",
        title="测试·候选缓存二",
        kind="朝议",
        summary="x",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
    )
    content.seed_events.extend([ev1, ev2])
    content.event_by_id[ev1.id] = ev1
    content.event_by_id[ev2.id] = ev2
    calls = 0

    def fake_gather_candidate_events(_state, _db):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(issues, "gather_candidate_events", fake_gather_candidate_events)
    try:
        out = apply_issue_tracker_output(
            db,
            state,
            {
                "new_issues": [
                    {"origin_kind": "event_pool", "id": ev1.id},
                    {"origin_kind": "event_pool", "id": ev2.id},
                ],
            },
            content=content,
            candidate_event_ids_at_input={ev1.id, ev2.id},
        source=Provenance.system_simulation)
    finally:
        content.seed_events.remove(ev1)
        content.seed_events.remove(ev2)
        content.event_by_id.pop(ev1.id, None)
        content.event_by_id.pop(ev2.id, None)

    assert out.new_issues == []
    assert len(out.rejected) == 2
    assert calls == 1
