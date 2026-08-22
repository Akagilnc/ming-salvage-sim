"""#12（M1 P0）：历史锚定事件结构化前提门。

`trigger_gate` + `_gate_passed`（能查 character/faction/army/region/metric 真实字段）此前只接
seed 情势，历史 `events` 分支只过纯日历窗口 `_event_window_open` → 前提已不成立的历史事件按
年月误触发（毛文龙已安抚/效顺仍被弹出的机制半）。把门接进历史分支：带 gate 的历史事件须达标
才进候选；无 gate（空 dict）= 纯日历锚定，行为不变。
"""
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from ming_sim import issues
from ming_sim.models import Event


def _promulgated_dossier(db, state, decree_text):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text=decree_text,
        target_kind="army", target_id="guanning",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")
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

        terminalized = issues.apply_event_terminal_states(state, db)

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


def test_open_window_historical_event_still_waits_for_earliest_time(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_open_window_future_hist__", {})
    ev.trigger_year = 1629
    ev.trigger_month = 6
    ev.open_window = True
    content.events.append(ev)
    try:
        state.year = 1627
        state.period = 10

        cands = issues.gather_candidate_events(state, db)

        assert all(c.id != "__test_open_window_future_hist__" for c in cands)
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

        issues.apply_event_terminal_states(state, db)

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

        issues.apply_event_terminal_states(state, db)

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
        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": ev.id}]},
            content=content,
            candidate_event_ids_at_input={ev.id},
            candidate_event_ids_authoritative=True,
        )

        assert out["new_issues"][0]["rejected"] is False
        assert db.conn.execute(
            "SELECT 1 FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
        assert db.has_event_triggered(ev.id)
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

        terminalized = issues.apply_event_terminal_states(state, db)

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


def test_gate_passed_tolerates_none(read_game):
    # PR#107 R1（gemini medium）：trigger_gate=None（content JSON 显式 null）传进 _gate_passed
    # 不应 None.items() AttributeError 崩候选收集；None 视同空门、恒过。
    db, state, content = read_game
    from ming_sim.issues import _gate_passed
    assert _gate_passed(None, state.metrics, db) is True


def test_gate_passed_tolerates_nonstring_cond(read_game):
    # PR#107 R2（gemini high）：条件值写成非字符串（{"民心":60} 而非 ">=60"）不应 cond.strip()
    # AttributeError 崩候选收集；str() 强转后不匹配操作符正则 → 门不达标（安全降级、不崩）。
    db, state, content = read_game
    from ming_sim.issues import _gate_passed
    assert _gate_passed({"民心": 60}, state.metrics, db) is False
    assert _gate_passed({"民心": True}, state.metrics, db) is False


def test_historical_event_none_gate_no_crash(game):
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_none_gate__", {})
    ev.trigger_gate = None  # 模拟 content JSON 显式 null
    content.events.append(ev)
    try:
        cands = issues.gather_candidate_events(state, db)  # 不应 AttributeError
        assert any(c.id == "__test_none_gate__" for c in cands), "None 门视同空门、恒过进候选"
    finally:
        content.events.remove(ev)


# ── #12(b)：trigger_gate key/cond fail-loud（ADR 0012 残留 4b，Q3 裁断=fail-loud）──

def test_gate_key_form_error_accepts_valid_forms():
    """存量 6 形态 + 文本字段 key 全合法（不误拒）。"""
    from ming_sim.content import gate_key_form_error
    for k in ("民心", "皇威", "国库", "内库",
              "power.houjin.leverage", "region.huguang.grain_security",
              "region.shaanxi|shanxi|henan.unrest.min",
              "class.士绅@nanzhili|zhejiang|fujian.satisfaction.max",
              "event.huabei_plague.triggered",
              "region.x.controlled_by"):
        assert gate_key_form_error(k) == "", (k, gate_key_form_error(k))


def test_gate_key_form_error_rejects_typo_metric_table_structure():
    """typo'd metric / 未知表 / 结构不完整 → 非空错误说明（fail-loud 素材）。"""
    from ming_sim.content import gate_key_form_error
    assert "未知 metric" in gate_key_form_error("民生")        # 民心 typo
    assert "未知表" in gate_key_form_error("regon.x.unrest")   # region typo
    assert gate_key_form_error("region.x")                      # 2 段，结构不完整
    assert gate_key_form_error("event.huabei_plague.status")     # event 仅支持 triggered


def test_gate_cond_form_error_numeric_and_text():
    """数值比较 + 文本相等都合法（load/runtime 调和，残留 4b②）；垃圾非法。"""
    from ming_sim.content import gate_cond_form_error
    # 数值比较（无 !=）+ 文本相等（==/!=）；数值 != 见 test_gate_cond_numeric_neq_rejected_*
    for c in ("<=240", ">=34", "==5", "==ming", "!=houjin"):
        assert gate_cond_form_error(c) == "", (c, gate_cond_form_error(c))
    assert gate_cond_form_error("abc")
    assert gate_cond_form_error(">> 5")


def test_load_event_fail_loud_on_bad_gate_key(monkeypatch):
    """load 时 trigger_gate key typo → SystemExit fail-loud（不再静默当条件不满足）。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "trigger_gate": {"民生": "<=5"}}]  # 民心 typo
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match="未知 metric"):
        content_mod.load_event_content("x.json")


def test_load_event_rejects_default_terminal_reason_outside_labels(monkeypatch):
    """default_terminal_reason 必须来自 terminal_reason_labels 白名单。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "interests": [], "audiences": [],
            "open_window": True,
            "terminal_reason_labels": ["已准"],
            "default_terminal_reason": "已驳"}]
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match="default_terminal_reason"):
        content_mod.load_event_content("x.json")


def test_load_event_requires_latest_or_open_window(monkeypatch):
    """历史锚定事件必须显式声明最晚时点或 open_window，漏填不许隐式永不过期。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "interests": [], "audiences": [],
            "trigger_year": 1629, "trigger_month": 6,
            "trigger_gate": {"民心": "<=5"}}]
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match="trigger_end_year|open_window"):
        content_mod.load_event_content("x.json")


def test_load_event_rejects_non_boolean_open_window(monkeypatch):
    """open_window 必须是 JSON boolean，不能让字符串 'false' 被 bool() 误作 True。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "interests": [], "audiences": [],
            "trigger_year": 1629, "trigger_month": 6,
            "open_window": "false",
            "trigger_gate": {"民心": "<=5"}}]
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match="open_window"):
        content_mod.load_event_content("x.json")


def test_load_event_rejects_strategic_foreign_situation(monkeypatch):
    """战略/外敌分类只允许 node/ending，不能被 situation 静默吞掉。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "interests": [], "audiences": [],
            "event_type": "situation",
            "trigger_class": "strategic_foreign"}]
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match=r"strategic_foreign.*situation|node/ending"):
        content_mod.load_event_content("x.json")


def test_load_event_rejects_latest_before_earliest(monkeypatch):
    """最晚时点不能早于最早时点，否则该事件永远无法合法开窗。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "interests": [], "audiences": [],
            "trigger_year": 1629, "trigger_month": 6,
            "trigger_end_year": 1629, "trigger_end_month": 5,
            "trigger_gate": {"民心": "<=5"}}]
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match="最晚|早于|窗口"):
        content_mod.load_event_content("x.json")


@pytest.mark.parametrize("field,value", [
    ("trigger_month", 13),
    ("trigger_month", -1),
    ("trigger_end_month", 13),
    ("trigger_end_month", -1),
])
def test_load_event_rejects_month_out_of_range(monkeypatch, field, value):
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "interests": [], "audiences": [],
            "trigger_year": 1629, "trigger_month": 6,
            "trigger_end_year": 1629, "trigger_end_month": 7,
            "trigger_gate": {"民心": "<=5"}}]
    bad[0][field] = value
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit, match=f"{field}.*0.*12"):
        content_mod.load_event_content("x.json")


def test_typo_field_gate_raises_clear_not_operationalerror(read_game):
    """gate 引用 typo'd 字段（DB 无此列）→ 求值期 SELECT 抛 OperationalError，被 fail-loud
    成清晰 ValueError（含 key + 'DB 无此列'），不留 cryptic 崩（#12 Q3）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = read_game
    with pytest.raises(ValueError, match="字段无效|DB 无此列"):
        _gate_passed({"region.huguang.grane_security": ">=1"}, state.metrics, db)  # grain_security typo


def test_gate_cond_numeric_neq_rejected_text_neq_ok():
    """cmr r1（Claude+codex concur）：'!=5' 数值 not-equal load 不许（runtime 数值分支无 !=、
    永远 False）；'!=houjin' 文本相等仍合法（与 runtime 两分支精确对齐）。"""
    from ming_sim.content import gate_cond_form_error
    assert gate_cond_form_error("!=5")        # 数值 != → 拒
    assert gate_cond_form_error("!=-3")       # 数值 != → 拒
    assert gate_cond_form_error("!=houjin") == ""   # 文本 != → 放行
    assert gate_cond_form_error("==ming") == ""
    assert gate_cond_form_error("==5") == ""        # 数值 == → 放行


def test_gate_key_rejects_empty_segments():
    """cmr r1（codex）：空 id / 空字段 / | 列表空成员 → fail-loud 素材（非静默/SQL 崩）。"""
    from ming_sim.content import gate_key_form_error
    assert gate_key_form_error("region..unrest")        # 空 id
    assert gate_key_form_error("region.x.")             # 空字段
    assert gate_key_form_error("region.shaanxi|.unrest")  # | 含空成员
    assert gate_key_form_error("region.shaanxi.unrest") == ""  # 正常仍放行


def test_typo_field_text_gate_raises_clear(read_game):
    """cmr r1（Claude）：文本相等 gate 引用 typo'd 字段 → text-branch（_eval_gate_key_str）的
    OperationalError 也被 fail-loud 成清晰 ValueError（覆盖文本分支 wrap）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = read_game
    with pytest.raises(ValueError, match="字段无效|DB 无此列"):
        _gate_passed({"region.huguang.controled_by": "==ming"}, state.metrics, db)  # controlled_by typo


def test_gate_key_rejects_empty_class_name():
    """cmr r2（Claude+codex concur）：class.<名>@<region> 的类名为空（@ 前）→ fail-loud
    （| 守不到单 @ 子形）。存量 class.士绅@... 正常仍放行。"""
    from ming_sim.content import gate_key_form_error
    assert gate_key_form_error("class.@nanzhili.satisfaction")          # 空类名
    assert gate_key_form_error("class.@n1|@n2.satisfaction")            # | 多成员均空类名
    assert gate_key_form_error("class.士绅@nanzhili.satisfaction") == ""  # 正常


def test_text_cond_requires_text_capable_key():
    """cmr r2（codex）：文本相等 cond 须配单 id region/army/power 三段 key；多 id/聚合/class/
    bare-metric 配文本 cond → fail-loud（runtime _eval_gate_key_str 不支持、否则静默永不达标）。"""
    from ming_sim.content import gate_text_key_form_error, gate_cond_is_text
    assert gate_cond_is_text("==ming") and not gate_cond_is_text("==5")
    assert gate_text_key_form_error("region.huguang.controlled_by") == ""   # 合法
    assert gate_text_key_form_error("region.a|b.controlled_by")              # 多 id 拒
    assert gate_text_key_form_error("class.士绅.satisfaction")                # class 拒
    assert gate_text_key_form_error("民心")                                  # bare metric 拒


def test_load_fail_loud_on_text_cond_multi_id_key(monkeypatch):
    """load 时 文本 cond 配多 id key → SystemExit fail-loud（配对校验）。"""
    import pytest
    import ming_sim.content as content_mod
    bad = [{"id": "e", "title": "t", "kind": "k", "summary": "s",
            "urgency": 1, "severity": 1, "credibility": 1,
            "trigger_gate": {"region.a|b.controlled_by": "==ming"}}]
    monkeypatch.setattr(content_mod, "load_json_asset", lambda *a, **k: bad)
    with pytest.raises(SystemExit):
        content_mod.load_event_content("x.json")


def test_text_cond_field_must_be_text_field():
    """cmr r3（codex）：文本相等 cond 须配各表文本字段；配数值字段（如 region.x.unrest）→ fail-loud
    （runtime str(数值)!=文本 永远 False）。controlled_by 等文本字段仍放行。"""
    from ming_sim.content import gate_text_key_form_error
    assert gate_text_key_form_error("region.huguang.controlled_by") == ""   # 文本字段 OK
    assert gate_text_key_form_error("power.houjin.stance") == ""            # 文本字段 OK
    assert gate_text_key_form_error("region.huguang.unrest")               # 数值字段 → 拒
    assert gate_text_key_form_error("power.houjin.leverage")               # 数值字段 → 拒


def test_gate_key_rejects_empty_region_after_at():
    """online codex P2：class.<名>@<空> = 想写 regional 漏 region → runtime 静默回退 national，
    fail-loud 拒之。national 用无 @ 形式仍放行；存量 @region 形式不误拒。"""
    from ming_sim.content import gate_key_form_error
    assert gate_key_form_error("class.士绅@.satisfaction")          # @ 后空 region → 拒
    assert gate_key_form_error("class.士绅.satisfaction") == ""     # national（无 @）放行
    assert gate_key_form_error("class.士绅@nanzhili.satisfaction") == ""  # regional 正常放行


def test_numeric_cond_on_text_field_raises_clear(read_game):
    """#159：数值比较 cond 配文本字段（如 region.x.controlled_by >=1）→ runtime int(str) ValueError
    被 fail-loud 成清晰 ValueError（数值不可比文本字段），不静默回 None 当条件不满足（Q3）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = read_game
    # controlled_by 是文本字段（'ming'/'houjin'），对它做数值比较 → fail-loud
    with pytest.raises(ValueError, match="字段非数值|不可比文本"):
        _gate_passed({"region.huguang.controlled_by": ">=1"}, state.metrics, db)


def test_character_numeric_gate_supports_comparison(read_game):
    """character.<name>.<field> 数值字段可参与 trigger_gate 比较（#201）。"""
    from ming_sim.issues import _gate_passed
    db, state, content = read_game

    row = db.conn.execute("SELECT loyalty FROM characters WHERE name = ?", ("毛文龙",)).fetchone()
    assert row is not None, "测试盘面应有毛文龙"

    assert _gate_passed({"character.毛文龙.loyalty": f">={int(row['loyalty'])}"}, state.metrics, db)
    assert not _gate_passed({"character.毛文龙.loyalty": f">{int(row['loyalty'])}"}, state.metrics, db)


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
    db.conn.execute("UPDATE armies SET arrears=? WHERE id=?", (0.5, army_id))
    db.conn.commit()

    assert not _gate_passed({f"army.{army_id}.arrears": "<=0"}, state.metrics, db)
    assert _gate_passed({f"army.{army_id}.arrears": ">0"}, state.metrics, db)


def test_character_gate_rejects_malformed_field_before_sql(read_game):
    """trigger_gate 字段名必须先过白名单，不能把畸形字段拼进 SQL。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, _content = read_game

    with pytest.raises(ValueError, match="字段无效"):
        _gate_passed({"character.毛文龙.loyalty;DROP": ">=1"}, state.metrics, db)


def test_character_numeric_field_text_gate_raises_clear(read_game):
    """character 数值字段走文本比较时必须 fail-loud，不能 str(loyalty) 后静默 False。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, _content = read_game

    with pytest.raises(ValueError, match="字段非文本"):
        _gate_passed({"character.毛文龙.loyalty": "==active"}, state.metrics, db)


def test_character_text_gate_supports_equality(game):
    """character.<name>.<field> 文本字段可参与 trigger_gate 相等/不等比较（#201）。"""
    from ming_sim.issues import _gate_passed
    db, state, content = game

    db.conn.execute("UPDATE characters SET location = ? WHERE name = ?", ("liaodong", "毛文龙"))

    assert _gate_passed({"character.毛文龙.location": "==liaodong"}, state.metrics, db)
    assert _gate_passed({"character.毛文龙.location": "!=capital"}, state.metrics, db)
    assert not _gate_passed({"character.毛文龙.location": "==capital"}, state.metrics, db)


def test_character_typo_field_gate_raises_clear(read_game):
    """character gate 字段名 typo（DB 无此列）沿用清晰 ValueError（#201）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = read_game

    with pytest.raises(ValueError, match="字段无效|DB 无此列"):
        _gate_passed({"character.毛文龙.loyality": ">=1"}, state.metrics, db)


def test_character_text_typo_field_gate_raises_clear(read_game):
    """character 文本 gate 字段名 typo 也必须 fail-loud（#201 cmr P2）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = read_game

    with pytest.raises(ValueError, match="字段无效|DB 无此列"):
        _gate_passed({"character.毛文龙.locaiton": "==liaodong"}, state.metrics, db)


def test_character_text_gate_key_passes_content_validation():
    """load-time 文本 gate 校验接受 character 的文本字段（#201）。"""
    from ming_sim.content import gate_text_key_form_error

    assert gate_text_key_form_error("character.毛文龙.location") == ""
    assert gate_text_key_form_error("character.毛文龙.office") == ""


def test_character_text_gate_rejects_serialized_list_field():
    """character.personal_skills 是序列化列表，不适合作普通文本等值门。"""
    from ming_sim.content import gate_text_key_form_error

    assert gate_text_key_form_error("character.毛文龙.personal_skills")


def test_character_text_gate_rejects_numeric_character_field():
    """character loyalty 等数值字段不应被文本等值门放行。"""
    from ming_sim.content import gate_text_key_form_error

    assert gate_text_key_form_error("character.毛文龙.loyalty")


def test_mao_event_effect_uses_unified_person_change_key():
    """ADR 0009 后新增事件效果应写统一 人物变更，不再写旧 flat key。"""
    events_path = Path(__file__).resolve().parents[1] / "content" / "events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    mao = next(item for item in events if item["id"] == "mao_wenlong")

    effect = mao["effect_on_trigger"]
    assert "人物变更" in effect
    assert "character_status_changes" not in effect
    assert effect["人物变更"] == [
        {"name": "毛文龙", "动作": "处置", "status": "dead", "reason": "袁崇焕双岛斩帅"}
    ]


def test_auto_trigger_historical_event_to_issue_uses_outer_transaction(game, monkeypatch):
    """auto-trigger 事务体内转 issue 时不得内部 commit，回滚边界由外层 atomic 统一控制。"""
    db, state, content = game
    issues.bind_content(content)
    event_id = "__test_auto_trigger_atomic__"
    ev = _hist_event(event_id, {})
    ev.auto_trigger = True
    calls = []

    def fake_event_to_issue(db_arg, state_arg, ev_arg, *, commit=True):
        calls.append((ev_arg.id, commit))
        return 999

    monkeypatch.setattr(issues, "event_to_issue", fake_event_to_issue)
    content.events.append(ev)
    try:
        triggered = issues.auto_trigger_seed_issues(state, db)
    finally:
        content.events.remove(ev)

    assert calls == [(event_id, False)]
    assert {"id": event_id, "title": ev.title, "issue_id": 999} in triggered


def test_event_content_rejects_falsy_person_core_subjects(monkeypatch):
    """内容契约：person_core_subjects 写了就必须是字符串数组，空字符串不能吞成缺省。"""
    from ming_sim import content as content_module

    monkeypatch.setattr(
        content_module,
        "load_json_asset",
        lambda filename: [
            {
                "id": "bad_person_core_subjects",
                "title": "坏人物核心事件",
                "kind": "situation",
                "summary": "x",
                "urgency": 50,
                "severity": 50,
                "credibility": 50,
                "interests": [],
                "audiences": [],
                "person_core_subjects": "",
            }
        ],
    )

    with pytest.raises(SystemExit, match="person_core_subjects"):
        content_module.load_event_content("events.json")


def test_mao_wenlong_event_excluded_after_appeasement(game):
    """#203/#12：毛文龙 loyalty 已过阈值时，袁斩毛文龙不应再按日历进候选。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (70, "毛文龙"))

    cands = issues.gather_candidate_events(state, db)

    assert all(ev.id != "mao_wenlong" for ev in cands)


def test_mao_wenlong_event_excluded_after_player_relocates_mao(game):
    """#191：玩家用行止把毛文龙调离东江后，location gate 可查并关闭斩毛事件。"""
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

        applied = issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "行止", "location": "shaanxi", "reason": "调往陕西剿抚"}]},
            content=content,
        )

        assert applied["applied_person_changes"] == [
            {"name": "毛文龙", "动作": "行止", "location": "shaanxi", "transit_to": "",
             "origin_ref": "盘面自发"}
        ]
        assert db.conn.execute(
            "SELECT location FROM characters WHERE name=?",
            ("毛文龙",),
        ).fetchone()["location"] == "shaanxi"
        assert all(ev.id != "mao_wenlong" for ev in issues.gather_candidate_events(state, db))
        issues.apply_event_terminal_states(state, db)
        terminal = db.conn.execute(
            "SELECT terminal_state, source FROM event_triggers WHERE event_id=?",
            ("mao_wenlong",),
        ).fetchone()
        assert terminal is not None
        assert dict(terminal) == {"terminal_state": "avoided", "source": "gate_avoided"}


def test_mao_wenlong_event_excluded_after_player_reassigns_yuan(game):
    """#191 CMR：袁崇焕仍活但不掌关宁时，斩毛事件不应仅因袁 active 进候选。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute(
        "UPDATE characters SET loyalty=?, status=?, location=? WHERE name=?",
        (44, "active", "dongjiang_area", "毛文龙"),
    )
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("孙承宗", "guanning"))

    cands = issues.gather_candidate_events(state, db)

    assert all(ev.id != "mao_wenlong" for ev in cands)


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

        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
            content=content,
        )

        assert out["new_issues"][0]["rejected"] is False
        assert db.get_character_status("毛文龙")[0] == "dead"
        assert content.characters["毛文龙"].status == "dead"
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs + 1


def test_strategic_foreign_event_records_trigger_and_lands_soft_result_delta(game):
    """#189：战略/外敌战事触发后，软判结果同信封落世界主账，不转长期 issue。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    db.conn.execute(
        "UPDATE armies SET manpower = ?, morale = ? WHERE id = ?",
        (30000, 50, "jingying"),
    )

    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "controlled_by": "ming", "reason": "己巳之变软判敌逼京畿"}},
            "army_delta": {"jingying": {"origin_ref": "盘面自发", "manpower": -5000, "morale": -8, "reason": "己巳之变勤王战损"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("jisi_lubian")
    assert db.find_any_issue_by_origin("event_pool", "jisi_lubian") is None
    region = db.conn.execute(
        "SELECT military_pressure, controlled_by FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()
    army = db.conn.execute(
        "SELECT manpower, morale FROM armies WHERE id = ?", ("jingying",)
    ).fetchone()
    assert region["military_pressure"] == 55
    assert region["controlled_by"] == "ming"
    assert army["manpower"] == 25000
    assert army["morale"] == 42


def test_strategic_event_result_delta_is_all_or_nothing_on_rejected_item(game):
    """ADR0014：同一战略战事信封内一项战果拒收，整组战果都不得半落主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    db.conn.execute("UPDATE armies SET morale = ? WHERE id = ?", (50, "jingying"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}},
            "army_delta": {"jingying": {"origin_ref": "盘面自发", "不存在字段": 1, "reason": "己巳之变无效战果字段"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id = ?", ("jingying",)
    ).fetchone()["morale"] == 50
    assert any(item.get("rejected") for item in out["region_changes"])
    assert any(item.get("rejected") for item in out["army_changes"])


def test_strategic_event_missing_origin_rejects_whole_result_envelope(game):
    """ADR0014/#558：来源拒收也必须在战略战果预检中令整个信封原子失败。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = 20 WHERE id = 'beizhili'")
    db.conn.execute("UPDATE armies SET morale = 50 WHERE id = 'jingying'")

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {
                "origin_ref": "盘面自发", "military_pressure": 35,
                "reason": "己巳之变软判敌逼京畿",
            }},
            "army_delta": {"jingying": {
                "morale": -8, "reason": "己巳之变勤王战损",
            }},
        },
        content=content,
    )

    issue = out["issue_summary"]["new_issues"][0]
    assert issue["rejected"] is True
    assert "来源" in issue["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id='beizhili'"
    ).fetchone()[0] == 20
    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id='jingying'"
    ).fetchone()[0] == 50


def test_strategic_foreign_event_lands_new_army_soft_result_delta(game):
    """ship-pre CMR：战略战事软判结果可落新军主账，并驱动事件触发。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    army_id = "__test_jisi_raider_army__"

    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": army_id,
                    "name": "己巳入塞偏师",
                    "owner_power": "houjin",
                    "station": "北直隶 / 遵化",
                    "manpower": 1200,
                    "reason": "己巳之变软判后金入塞偏师成军",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("jisi_lubian")
    assert dict(db.conn.execute(
        "SELECT owner_power, manpower FROM armies WHERE id = ?", (army_id,)
    ).fetchone()) == {"owner_power": "houjin", "manpower": 1200}
    assert out["created_armies"][0].get("rejected") is not True


@pytest.mark.parametrize(
    ("army_id", "army_name", "existing_id"),
    [
        ("jingying", "己巳入塞偏师", "jingying"),
        ("__test_jisi_name_collision__", "京营", "jingying"),
    ],
)
def test_strategic_new_army_result_rejects_existing_army_collision(
    game, army_id, army_name, existing_id
):
    """CMR R10：战略新军战果不得撞既有军队 id/name 走扩编合并路径。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    before = db.conn.execute(
        "SELECT manpower, owner_power FROM armies WHERE id = ?", (existing_id,)
    ).fetchone()

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": army_id,
                    "name": army_name,
                    "owner_power": "houjin",
                    "station": "北直隶 / 遵化",
                    "manpower": 1200,
                    "reason": "己巳之变软判后金入塞偏师成军",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("jisi_lubian")
    after = db.conn.execute(
        "SELECT manpower, owner_power FROM armies WHERE id = ?", (existing_id,)
    ).fetchone()
    assert dict(after) == dict(before)
    if army_id != existing_id:
        assert db.conn.execute("SELECT 1 FROM armies WHERE id = ?", (army_id,)).fetchone() is None
    assert out["created_armies"][0]["rejected"] is True


def test_strategic_new_army_result_rejects_nonpositive_manpower(game):
    """同族自查：战略新军战果不能用 0/负兵力建出无效新军来触发事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    army_id = "__test_zero_jisi_raider_army__"

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": army_id,
                    "name": "己巳入塞空营",
                    "owner_power": "houjin",
                    "station": "北直隶 / 遵化",
                    "manpower": 0,
                    "reason": "己巳之变软判后金入塞偏师成军",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute("SELECT 1 FROM armies WHERE id = ?", (army_id,)).fetchone() is None
    assert out["created_armies"][0]["rejected"] is True


def test_strategic_event_records_outcome_label_with_world_state_delta(game):
    """ADR0014：战略战事软判须同写结局标签账，供下游链分支读取。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "入塞被遏"}


def test_strategic_event_outcome_label_normalizes_known_synonym(game):
    """ADR0014：事件结局标签允许近义归一到闭合标签集，不因措辞微差拒收。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞遭遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    row = db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone()
    assert row["terminal_reason"] == "入塞被遏"


def test_event_outcome_retry_ignores_non_landable_event_without_world_state_delta(game):
    """PR#214：只因 new_issues 幻觉静态事件 id、但无战果主账时，不应触发 retry/fail-loud。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    extracted = {
        "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
        "事件结局": {"jisi_lubian": "大胜"},
        "region_delta": {"shandong": {"origin_ref": "盘面自发", "民心": -1, "reason": " unrelated famine pressure "}},
    }

    issues.normalize_event_outcome_labels_or_error(
        extracted,
        content,
        db=db,
        state=state,
    )

    assert extracted["事件结局"] == {"jisi_lubian": "大胜"}


def test_strategic_event_delta_requires_outcome_label_without_mutation(game):
    """ADR0014：战略战果 delta 必须同写结局标签，缺标签则整组拒收且不落主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    row = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?",
        ("beizhili",),
    ).fetchone()
    original_pressure = row["military_pressure"]

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}},
        },
        content=content,
    )

    issue = out["issue_summary"]["new_issues"][0]
    assert issue["rejected"] is True
    assert issue["category"] == "missing_event_outcome"
    assert "缺事件结局标签" in issue["reason"]
    row = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?",
        ("beizhili",),
    ).fetchone()
    assert row["military_pressure"] == original_pressure
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone() is None


def test_strategic_event_outcome_label_unknown_fails_loud_without_mutation(game):
    """ADR0014：无法可靠归一的事件结局须 fail-loud，不能普通拒收后继续结算。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))

    with pytest.raises(ValueError, match="事件结局标签无法归一"):
        issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
                "事件结局": {"jisi_lubian": "大胜"},
                "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}},
            },
            content=content,
        )

    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20


def test_anchored_strategic_new_army_without_event_trigger_is_rejected(game):
    """ship-pre CMR：有战役锚点但无 event_pool 触发时，新军战果不得半落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    army_id = "__test_orphan_jisi_raider__"

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": army_id,
                    "name": "孤立入塞偏师",
                    "owner_power": "houjin",
                    "station": "北直隶 / 遵化",
                    "manpower": 1200,
                    "reason": "己巳之变软判后金入塞偏师成军",
                }
            ],
        },
        content=content,
    )

    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute("SELECT id FROM armies WHERE id = ?", (army_id,)).fetchone() is None
    assert out["created_armies"][0]["rejected"] is True
    assert out["created_armies"][0]["category"] == "event_rejected"
    assert "未触发" in out["created_armies"][0]["reason"]


def test_anchored_strategic_region_outcome_without_reason_is_rejected(game):
    """ship-pre CMR：疑似战略战果缺 reason 时，不得当普通地区 delta 半落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert out["region_changes"][0]["rejected"] is True
    assert out["region_changes"][0]["category"] == "event_rejected"


def test_ordinary_jinzhou_preparedness_delta_is_not_rejected_as_songshan_outcome(game):
    """ship-pre CMR：普通锦州战备整饬不等于松锦决战战果。"""
    db, state, content = game
    issues.bind_content(content)
    before = db.conn.execute(
        "SELECT training FROM armies WHERE id = ?", ("guanning",)
    ).fetchone()["training"]
    origin_ref = _promulgated_dossier(db, state, "整饬锦州战备")

    out = issues.apply_score_extraction(
        db,
        state,
        {"army_delta": {"guanning": {"origin_ref": origin_ref, "training": 5, "reason": "奉旨整饬锦州战备"}}},
        content=content,
    )

    assert db.conn.execute(
        "SELECT training FROM armies WHERE id = ?", ("guanning",)
    ).fetchone()["training"] == before + 5
    assert out["army_changes"][0].get("rejected") is not True


def test_strategic_foreign_event_survives_named_commander_death_with_soft_result_delta(game):
    """#189：战略战事点名将已死也不作废，由在位军镇承接软判结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 8
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("dead", "洪承畴"))
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (40, "liaodong"))
    db.conn.execute(
        "UPDATE armies SET manpower = ?, morale = ? WHERE id = ?",
        (60000, 55, "guanning"),
    )

    assert any(ev.id == "songshan_battle" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "songshan_battle"}],
            "region_delta": {"liaodong": {"origin_ref": "盘面自发", "military_pressure": 18, "reason": "松锦决战软判辽东吃紧"}},
            "army_delta": {"guanning": {"origin_ref": "盘面自发", "manpower": -12000, "morale": -12, "reason": "松锦决战关宁主力战损"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("songshan_battle")
    assert db.find_any_issue_by_origin("event_pool", "songshan_battle") is None
    region = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("liaodong",)
    ).fetchone()
    army = db.conn.execute(
        "SELECT manpower, morale FROM armies WHERE id = ?", ("guanning",)
    ).fetchone()
    assert region["military_pressure"] == 59
    assert army["manpower"] == 48000
    assert army["morale"] == 43


def test_strategic_foreign_event_rejects_trigger_without_world_state_delta(game):
    """#189 CMR：战略/外敌战事不能只记事件触发而无主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}]},
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")


def test_direct_issue_tracker_rejects_strategic_event_without_world_state_delta(game):
    """ship-pre R5：低层 issue applier 也不能绕过战略战事主账门。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}]},
        content=content,
    )

    assert out["new_issues"][0]["rejected"] is True
    assert "主账" in out["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")


def test_anchored_strategic_result_delta_without_event_trigger_is_rejected(game):
    """#189 CMR R6：有战役锚点但无 event_pool 触发时，不得只落战果主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))

    out = issues.apply_score_extraction(
        db,
        state,
        {"region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 20, "reason": "己巳之变软判敌逼京畿"}}},
        content=content,
    )

    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert out["region_changes"][0]["rejected"] is True
    assert out["region_changes"][0]["category"] == "event_rejected"
    assert "未触发" in out["region_changes"][0]["reason"]


def test_ordinary_army_station_delta_with_strategic_place_anchor_is_not_rejected(game):
    """ship-pre CMR：普通调防只含战略地名，不得被误当成未触发战役战果。"""
    db, state, content = game
    issues.bind_content(content)
    origin_ref = _promulgated_dossier(db, state, "移镇锦州前屯")

    out = issues.apply_score_extraction(
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
    assert out["army_changes"][0].get("rejected") is not True


def test_issue_194_lindan_xiqian_requires_world_state_main_ledger_delta(game):
    """#194：林丹汗西迁已归战略/外敌类，必须落势力或世界主账才算触发。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1632
    state.period = 4

    assert any(ev.id == "lindan_xiqian" for ev in issues.gather_candidate_events(state, db))
    before_mongol = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("mongol",)
    ).fetchone()["military_strength"]
    before_houjin = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"]

    out = issues.apply_score_extraction(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "lindan_xiqian"}]},
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("lindan_xiqian")

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "lindan_xiqian"}],
            "power_updates": {
                "mongol": {"origin_ref": "盘面自发", "military_strength": -8, "reason": "林丹汗西迁青海，察哈尔诸部离散"},
                "houjin": {"origin_ref": "盘面自发", "military_strength": 5, "reason": "林丹汗西迁后后金收拢蒙古右翼"},
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("lindan_xiqian")
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("mongol",)
    ).fetchone()["military_strength"] == before_mongol - 8
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"] == before_houjin + 5


def test_lindan_xiqian_does_not_capture_untriggered_beizhili_border_policy_delta(game):
    """PR R1：普通北直隶边防政策不能被林丹汗西迁锚点误当成孤儿战果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1632
    state.period = 4
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (30, "beizhili"))

    out = issues.apply_score_extraction(
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

    assert not db.has_event_triggered("lindan_xiqian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 27
    assert out["region_changes"][0].get("rejected") is not True


def test_shared_jinzhou_result_does_not_double_consume_dalingghe_and_songshan(game):
    """PR R1：大凌河与松锦同池时，泛锦州战果不能同一 delta 双落账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 8
    db.conn.execute(
        "UPDATE regions SET controlled_by = ?, military_pressure = ? WHERE id = ?",
        ("ming", 20, "liaodong"),
    )
    db.conn.execute(
        "UPDATE armies SET supply = ?, arrears = ?, morale = ? WHERE id = ?",
        (40, 45, 50, "guanning"),
    )
    db.conn.execute("UPDATE powers SET military_strength = ? WHERE id = ?", (75, "houjin"))
    cands = {ev.id for ev in issues.gather_candidate_events(state, db)}
    assert {"dalingghe", "songshan_battle"} <= cands

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {"origin_kind": "event_pool", "id": "dalingghe"},
                {"origin_kind": "event_pool", "id": "songshan_battle"},
            ],
            "region_delta": {
                "liaodong": {
                    "origin_ref": "盘面自发", "military_pressure": 8,
                    "reason": "锦州战事软判辽东军压上升",
                }
            },
        },
        content=content,
    )

    assert not db.has_event_triggered("dalingghe")
    assert db.has_event_triggered("songshan_battle")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("liaodong",)
    ).fetchone()["military_pressure"] == 28
    assert any(
        item["id"] == "dalingghe" and item.get("rejected")
        for item in out["issue_summary"]["new_issues"]
    )


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

    out = issues.apply_score_extraction(
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

    assert not db.has_event_triggered("luoyang_fallen")
    assert not db.has_event_triggered("kaifeng_siege")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("henan",)
    ).fetchone()["military_pressure"] == 26
    assert out["region_changes"][0].get("rejected") is not True


def test_henan_bandit_policy_delta_does_not_capture_untriggered_luoyang_event(game):
    """PR R3：普通李自成势力变化不能因河南+流寇泛锚点被误当成洛阳陷落战果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1642
    state.period = 9
    db.conn.execute(
        "UPDATE powers SET military_strength = ? WHERE id = ?",
        (52, "bandit_li_zicheng"),
    )

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "power_updates": {
                "bandit_li_zicheng": {
                    "origin_ref": "盘面自发", "military_strength": -3,
                    "reason": "河南流寇被围剿，声势稍挫",
                }
            }
        },
        content=content,
    )

    assert not db.has_event_triggered("luoyang_fallen")
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("bandit_li_zicheng",)
    ).fetchone()["military_strength"] == 49
    assert out["power_changes"][0].get("rejected") is not True


def test_unrelated_region_delta_does_not_satisfy_strategic_event_result_gate(game):
    """#189 CMR R2：同信封无关地区变化不能冒充该战略战事的主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "shaanxi"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"shaanxi": {"origin_ref": "盘面自发", "unrest": 1}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
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

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "unrest": 1, "reason": "ordinary beizhili unrest unrelated to battle"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["unrest"] == 79
    assert out["region_changes"][0].get("rejected") is not True


def test_unrelated_person_delta_does_not_satisfy_strategic_event_result_gate(game):
    """#189 CMR R4：无关人物变化不能冒充战略战事主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "病重卒于任上"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.get_character_status("孙传庭")[0] == "dead"
    assert out["applied_person_changes"][0].get("rejected") is not True


def test_unrelated_person_delta_with_event_anchor_does_not_satisfy_strategic_event_result_gate(game):
    """ship-pre CMR R4：无关人物即使 reason 带战役锚词，也不能冒充战略战事主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "己巳之变误写无关人物"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.get_character_status("孙传庭")[0] == "dead"
    assert out["applied_person_changes"][0].get("rejected") is not True


def test_target_person_delta_without_event_anchor_does_not_satisfy_strategic_event_result_gate(game):
    """#189 CMR R5：点名将普通人物变化不能只靠姓名冒充该战事结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "卢象升"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "卢象升", "动作": "处置", "status": "dead", "reason": "病重卒于任上"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("wuyin_lubian")
    assert db.get_character_status("卢象升")[0] == "dead"
    assert out["applied_person_changes"][0].get("rejected") is not True


def test_rejected_noncandidate_strategic_event_with_unknown_label_preserves_unrelated_delta(game):
    """PR#214：非候选事件即使带无法归一标签，也只按候选闸拒收，不应 fail-loud 吞掉无关 delta。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "shaanxi"))
    assert all(candidate.id != "jisi_lubian" for candidate in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "大胜"},
            "region_delta": {
                "beizhili": {"origin_ref": "盘面自发", "military_pressure": 20, "reason": "己巳之变重复引用战果"},
                "shaanxi": {"origin_ref": "盘面自发", "unrest": 1},
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("shaanxi",)
    ).fetchone()["unrest"] == 79


def test_rejected_strategic_foreign_event_does_not_land_battle_delta(game):
    """#189 CMR：战略事件被同信封关门拒收时，伴随战果 delta 不得半落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 20, "reason": "己巳之变重复引用战果"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert out["region_changes"][0]["rejected"] is True
    assert out["region_changes"][0]["category"] == "event_rejected"
    assert "战果不落" in out["region_changes"][0]["reason"]


def test_rejected_strategic_foreign_event_preserves_unrelated_region_delta(game):
    """#189 CMR R2：战略事件被拒时，只跳过其战果，不能吞掉本月无关地区变化。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE regions SET unrest = ? WHERE id = ?", (78, "shaanxi"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"shaanxi": {"origin_ref": "盘面自发", "unrest": 1}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
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

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "unrest": 1, "reason": "ordinary beizhili unrest unrelated to battle"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["unrest"] == 79
    assert out["region_changes"][0].get("rejected") is not True


def test_rejected_strategic_event_preserves_unrelated_person_delta(game):
    """#189 CMR R4：战略事件重复/拒收时，不能吞掉同信封无关人物变化。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "病重卒于任上"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.get_character_status("孙传庭")[0] == "dead"
    assert out["applied_person_changes"][0].get("rejected") is not True


def test_previously_triggered_strategic_event_rejects_duplicate_without_landing_delta(game):
    """#189 CMR R2：历史曾触发不等于本回合触发；重复引用不得补落新战果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.mark_event_triggered(state, "jisi_lubian")
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 10, "reason": "己巳之变重复引用战果"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20


def test_rejected_strategic_event_does_not_land_substitute_commander_person_delta(game):
    """#189 CMR R3：替补将也是战事软判结果；重复/拒收事件不得单独杀人。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 8
    db.mark_event_triggered(state, "songshan_battle")
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "孙传庭"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "songshan_battle"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置", "status": "dead", "reason": "松锦替补战死"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.get_character_status("孙传庭")[0] == "active"
    assert out["applied_person_changes"][0]["rejected"] is True
    assert "战果不落" in out["applied_person_changes"][0]["reason"]


def test_strategic_event_invalid_controlled_by_suppresses_sibling_deltas(game):
    """Codex P1：战略事件 controlled_by 脏值须整组预拒，不能靠兄弟字段触发终态。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    before = db.conn.execute(
        "SELECT controlled_by, military_pressure FROM regions WHERE id = ?",
        ("beizhili",),
    ).fetchone()

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发", "controlled_by": "not_a_real_power",
                    "military_pressure": 5,
                    "reason": "戊寅虏变软判北直隶陷落但势力 id 脏",
                }
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "controlled_by" in out["issue_summary"]["new_issues"][0]["reason"]
    assert "整组战果不落主账" in out["region_changes"][0]["reason"]
    assert not db.has_event_triggered("wuyin_lubian")
    after = db.conn.execute(
        "SELECT controlled_by, military_pressure FROM regions WHERE id = ?",
        ("beizhili",),
    ).fetchone()
    assert after["controlled_by"] == before["controlled_by"]
    assert after["military_pressure"] == before["military_pressure"]


def test_invalid_strategic_event_result_delta_does_not_mark_event_triggered(game):
    """#189 CMR R2：战果 delta 被逐项拒收时，不得只落 event_triggers 空壳。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "不存在字段": 1, "reason": "己巳之变无效战果字段"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "非法地区字段" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert out["region_changes"][0]["rejected"] is True


def test_strategic_event_cannon_clamp_noop_does_not_mark_event_triggered(game):
    """CMR R11：clamp 后 delta=0 的审计留痕不算战略战事世界状态结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    row = db.conn.execute(
        "SELECT city_level FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()
    cap = int(row["city_level"]) * 8
    db.conn.execute("UPDATE regions SET cannon = ? WHERE id = ?", (cap, "beizhili"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发", "cannon": 1,
                    "reason": "己巳之变软判京畿城防炮已满额仍报增炮",
                }
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "无真实世界状态变化" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT cannon FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["cannon"] == cap


def test_strategic_event_army_clamp_noop_does_not_mark_event_triggered(game):
    """同族自查：军队数值 clamp 后无变化也不能充当战略战事主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE armies SET manpower = ? WHERE id = ?", (0, "jingying"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "army_delta": {"jingying": {"origin_ref": "盘面自发", "manpower": -5000, "reason": "己巳之变勤王战损"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "无真实世界状态变化" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT manpower FROM armies WHERE id = ?", ("jingying",)
    ).fetchone()["manpower"] == 0


def test_strategic_event_person_travel_noop_does_not_mark_event_triggered(game):
    """CMR R12：战略人物行止若没有真实位置/在途变化，不得充当战事主账结果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    db.conn.execute(
        "UPDATE characters SET status = ?, location = ?, transit_to = ? WHERE name = ?",
        ("active", "beizhili", "", "卢象升"),
    )
    content.characters["卢象升"].status = "active"
    content.characters["卢象升"].location = "beizhili"
    content.characters["卢象升"].transit_to = ""

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": "卢象升",
                    "动作": "行止",
                    "location": "beizhili",
                    "reason": "戊寅虏变软判主帅行止",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "无真实世界状态变化" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("wuyin_lubian")
    row = db.conn.execute(
        "SELECT status, location, transit_to FROM characters WHERE name = ?",
        ("卢象升",),
    ).fetchone()
    assert dict(row) == {"status": "active", "location": "beizhili", "transit_to": ""}


@pytest.mark.parametrize("action,status", [("处置", "dismissed"), ("罢黜", "dismissed")])
def test_strategic_event_person_same_status_noop_does_not_mark_event_triggered(game, action, status):
    """CMR R13：战略人物处置/罢黜若状态未变，不得只靠改缘由消耗战事事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    db.conn.execute(
        "UPDATE characters SET status = ?, status_reason = ?, reason_code = '' WHERE name = ?",
        (status, "已先行罢黜", "卢象升"),
    )
    content.characters["卢象升"].status = status
    content.characters["卢象升"].status_reason = "已先行罢黜"
    content.characters["卢象升"].reason_code = ""
    item = {"name": "卢象升", "动作": action, "reason": "戊寅虏变软判主帅已罢黜"}
    if action == "处置":
        item["status"] = status

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [item],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "无真实世界状态变化" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("wuyin_lubian")
    row = db.conn.execute(
        "SELECT status, status_reason FROM characters WHERE name = ?",
        ("卢象升",),
    ).fetchone()
    assert dict(row) == {"status": status, "status_reason": "已先行罢黜"}


@pytest.mark.parametrize("action", ["任命", "调任"])
def test_strategic_event_person_same_office_noop_does_not_mark_event_triggered(game, action):
    """CMR R14：战略人物任命/调任若官职未变，不得消耗战事事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    office = "大名府知府"
    office_type = issues.infer_office_type_from_office(office, "", db.llm_config)
    db.conn.execute(
        "UPDATE characters SET status = ?, office = ?, office_type = ? WHERE name = ?",
        ("active", office, office_type, "卢象升"),
    )
    content.characters["卢象升"].status = "active"
    content.characters["卢象升"].office = office
    content.characters["卢象升"].office_type = office_type
    db.set_character_office("卢象升", office, office_type, commit=False)
    db.conn.execute(
        "UPDATE character_offices SET appointment_tenure = ? WHERE character_name = ?",
        ("真除", "卢象升"),
    )

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": "卢象升",
                    "动作": action,
                    "office": office,
                    "office_type": office_type,
                    "任别": "真除",
                    "reason": "戊寅虏变软判主帅仍督师",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "无真实世界状态变化" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("wuyin_lubian")
    row = db.conn.execute(
        "SELECT status, office, office_type FROM characters WHERE name = ?",
        ("卢象升",),
    ).fetchone()
    assert dict(row) == {"status": "active", "office": office, "office_type": office_type}


@pytest.mark.parametrize("action", ["任命", "调任"])
def test_strategic_event_person_tenure_change_is_material_world_state(game, action):
    """#607：同官同类仅任别改变仍是战果，不得 suppress 同信封落账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    office = "大名府知府"
    office_type = issues.infer_office_type_from_office(office, "", db.llm_config)
    db.set_character_office("卢象升", office, office_type, commit=False)
    db.conn.execute(
        "UPDATE character_offices SET appointment_tenure = ? WHERE character_name = ?",
        ("署理", "卢象升"),
    )
    before_pressure = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"]

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [{
                "origin_ref": "盘面自发",
                "name": "卢象升",
                "动作": action,
                "office": office,
                "office_type": office_type,
                "任别": "真除",
                "reason": "戊寅虏变后主帅由署理转真除",
            }],
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发",
                    "military_pressure": -1,
                    "reason": "戊寅虏变边患稍解",
                }
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("wuyin_lubian")
    assert db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name = ?",
        ("卢象升",),
    ).fetchone()["appointment_tenure"] == "真除"
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == before_pressure - 1


@pytest.mark.parametrize("action", ["任命", "调任"])
def test_strategic_event_invalid_person_tenure_rejects_whole_result_envelope(game, action):
    """#607：非法任别须逐项拒收，且战略事件同信封战果不得半落主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    office = "大名府知府"
    office_type = issues.infer_office_type_from_office(office, "", db.llm_config)
    db.set_character_office("卢象升", office, office_type, commit=False)
    before_pressure = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"]

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [{
                "name": "卢象升",
                "动作": action,
                "office": "宣大总督",
                "office_type": office_type,
                "任别": "权署",
                "reason": "戊寅虏变后调度主帅",
            }],
            "region_delta": {
                "beizhili": {"military_pressure": -1, "reason": "戊寅虏变边患稍解"}
            },
        },
        content=content,
    )

    rejected_issue = out["issue_summary"]["new_issues"][0]
    assert rejected_issue["rejected"] is True
    assert rejected_issue["category"] == "invalid_event_result_delta"
    assert "人物战果拒收" in rejected_issue["reason"]
    assert "任别非白名单" in rejected_issue["reason"]
    assert not db.has_event_triggered("wuyin_lubian")
    office_row = db.conn.execute(
        "SELECT c.office, co.appointment_tenure FROM characters c "
        "LEFT JOIN character_offices co ON co.character_name = c.name WHERE c.name = ?",
        ("卢象升",),
    ).fetchone()
    assert dict(office_row) == {"office": office, "appointment_tenure": "真除"}
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == before_pressure
    assert any(item.get("rejected") for item in out["applied_person_changes"])
    assert any(item.get("rejected") for item in out["region_changes"])


def test_strategic_event_accepts_power_update_as_material_world_state(game):
    """ADR0014：势力也是世界主账，只有有效 power_updates 的战略战果也可触发事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE powers SET military_strength = ? WHERE id = ?", (50, "houjin"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "power_updates": {
                "houjin": {"origin_ref": "盘面自发", "military_strength": -3, "reason": "己巳之变后金入塞受挫"}
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"] == 47
    assert any(
        item.get("field") == "military_strength" and item.get("delta") == -3
        for item in out["power_changes"]
    )


def test_strategic_event_power_update_requires_event_anchor(game):
    """online R3 Codex：power-only 战略战果也必须带事件 reason 锚点。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE powers SET military_strength = ? WHERE id = ?", (50, "houjin"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "power_updates": {"houjin": {"origin_ref": "盘面自发", "military_strength": -3}},
        },
        content=content,
    )

    issue = out["issue_summary"]["new_issues"][0]
    assert issue["rejected"] is True
    assert "势力战果缺 reason/原因 事件锚点" in issue["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"] == 50
    assert out["power_changes"][0]["rejected"] is True


def test_accepted_strategic_event_applies_power_updates_after_main_result(game):
    """同族自查：战略事件已有真实主账结果时，power_updates 可作为同信封附带战果落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    db.conn.execute("UPDATE powers SET military_strength = ? WHERE id = ?", (50, "houjin"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 10, "controlled_by": "ming", "reason": "己巳之变软判敌逼京畿"}},
            "power_updates": {
                "houjin": {"origin_ref": "盘面自发", "military_strength": -3, "reason": "己巳之变后金入塞受挫"}
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 30
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"] == 47
    assert any(item.get("field") == "military_strength" and item.get("delta") == -3 for item in out["power_changes"])


def test_invalid_strategic_power_update_blocks_main_result(game):
    """同族自查：同信封 power_updates 自身拒收时，地区战果也不得半落主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    db.conn.execute("UPDATE powers SET military_strength = ? WHERE id = ?", (50, "houjin"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 10, "reason": "己巳之变软判敌逼京畿"}},
            "power_updates": {
                "houjin": {"origin_ref": "盘面自发", "城防": 3, "reason": "己巳之变后金入塞受挫"}
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "势力战果拒收" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"] == 50
    assert any(item.get("rejected") and item.get("category") == "event_rejected" for item in out["region_changes"])
    assert any(item.get("rejected") and item.get("category") == "event_rejected" for item in out["power_changes"])


def test_orphan_strategic_power_update_without_event_issue_is_rejected(game):
    """同族自查：带战略事件锚点的 power_updates 没有事件立项时，也不得按普通势力变化落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute("UPDATE powers SET military_strength = ? WHERE id = ?", (50, "houjin"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "power_updates": {
                "houjin": {"origin_ref": "盘面自发", "military_strength": -3, "reason": "己巳之变后金入塞受挫"}
            },
        },
        content=content,
    )

    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_strength FROM powers WHERE id = ?", ("houjin",)
    ).fetchone()["military_strength"] == 50
    assert any(
        item.get("rejected") and item.get("category") == "event_rejected" and item.get("power_id") == "houjin"
        for item in out["power_changes"]
    )


@pytest.mark.parametrize("control_field", ["controlled_by", "归属"])
def test_jisi_border_contained_outcome_rejects_invasion_world_state(game, control_field):
    """CMR R11：己巳结局标签不得与结构化世界状态战果自相矛盾。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.conn.execute(
        "UPDATE regions SET military_pressure = ?, controlled_by = ? WHERE id = ?",
        (20, "ming", "beizhili"),
    )

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "挡于边墙"},
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发", control_field: "houjin",
                    "military_pressure": 40,
                    "reason": "己巳之变软判后金长驱直入兵临京师",
                }
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "事件结局" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    region = db.conn.execute(
        "SELECT military_pressure, controlled_by FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()
    assert dict(region) == {"military_pressure": 20, "controlled_by": "ming"}


def test_strategic_event_person_result_rejection_blocks_other_result_deltas(game):
    """ADR0014：战略战事人物战果拒收时，同信封地区战果也不得半落主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "卢象升"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 15, "reason": "戊寅虏变软判畿南受压"}},
            "人物变更": [{"origin_ref": "盘面自发", "name": "卢象升", "动作": "处置", "status": "candidate", "reason": "戊寅虏变软判战死"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("wuyin_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert db.get_character_status("卢象升")[0] == "active"
    assert any(item.get("rejected") for item in out["region_changes"])
    assert any(item.get("rejected") for item in out["applied_person_changes"])


def test_strategic_person_alias_stays_in_rejected_event_envelope(game):
    """CMR R12：战略人物别名须先归一再分流，事件拒收时不得漏成普通人物变更。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    alias = "__test_lu_zhifu__"
    content.characters["卢象升"].aliases = list(content.characters["卢象升"].aliases or []) + [alias]
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "卢象升"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "不存在字段": 1, "reason": "戊寅虏变无效战果字段"}},
            "人物变更": [{"origin_ref": "盘面自发", "name": alias, "动作": "处置", "status": "dead", "reason": "戊寅虏变软判战死"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("wuyin_lubian")
    assert db.get_character_status("卢象升")[0] == "active"
    assert any(
        item.get("rejected") and item.get("category") == "event_rejected" and item.get("name") == "卢象升"
        for item in out["applied_person_changes"]
    )


def test_rejected_strategic_person_preflight_restores_content_power_id(game):
    """CMR R8：人物战果预检干跑失败后，内存人物 power_id 也必须随 DB 回滚。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 8
    db.conn.execute("UPDATE characters SET power_id = ?, status = ? WHERE name = ?", ("ming", "active", "洪承畴"))
    content.characters["洪承畴"].power_id = "ming"
    before_db_power = db.conn.execute(
        "SELECT power_id FROM characters WHERE name = ?", ("洪承畴",)
    ).fetchone()["power_id"]
    before_content_power = content.characters["洪承畴"].power_id

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "songshan_battle"}],
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": "洪承畴",
                    "动作": "易主",
                    "方式": "被俘而降",
                    "new_power": "houjin",
                    "new_title": "降臣",
                    "反噬": {"ming": {"military_strength": -5}},
                    "reason": "松锦决战软判主帅被俘降金",
                }
            ],
            "new_armies": [
                {
                    "origin_ref": "盘面自发", "id": "__bad_songshan_army__",
                    "name": "无效松山军",
                    "owner_power": "__missing_power__",
                    "station": "松山",
                    "manpower": 1200,
                    "reason": "松锦决战软判无效新军",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("songshan_battle")
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name = ?", ("洪承畴",)
    ).fetchone()["power_id"] == before_db_power
    assert content.characters["洪承畴"].power_id == before_content_power


def test_strategic_person_backlash_rejection_blocks_event_result_envelope(game):
    """CMR R9：易主顶层成功但反噬拒收，也必须拒整组战略战果。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1641
    state.period = 8
    db.conn.execute("UPDATE characters SET power_id = ?, status = ? WHERE name = ?", ("ming", "active", "洪承畴"))
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "liaodong"))
    content.characters["洪承畴"].power_id = "ming"

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "songshan_battle"}],
            "region_delta": {"liaodong": {"origin_ref": "盘面自发", "military_pressure": 5, "reason": "松锦决战软判辽东吃紧"}},
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": "洪承畴",
                    "动作": "易主",
                    "方式": "被俘而降",
                    "new_power": "houjin",
                    "new_title": "降臣",
                    "反噬": {"__missing_power__": {"military_strength": -5}},
                    "reason": "松锦决战软判主帅被俘降金",
                }
            ],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("songshan_battle")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("liaodong",)
    ).fetchone()["military_pressure"] == 20
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name = ?", ("洪承畴",)
    ).fetchone()["power_id"] == "ming"
    assert content.characters["洪承畴"].power_id == "ming"
    assert any(item.get("rejected") for item in out["region_changes"])


def test_strategic_foreign_event_lands_soft_result_person_delta(game):
    """#189 CMR：战略战事的人死/生是软判结果，须能落人物主账。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 9
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "卢象升"))

    assert any(ev.id == "wuyin_lubian" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "卢象升", "动作": "处置", "status": "dead", "reason": "戊寅虏变软判战死"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("wuyin_lubian")
    assert db.get_character_status("卢象升")[0] == "dead"


def test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome():
    """#189：戊寅虏变不能把卢象升写成人物核心；卢死/生是战事软判结果。"""
    events_path = Path(__file__).resolve().parents[1] / "content" / "events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    wuyin = next(item for item in events if item["id"] == "wuyin_lubian")
    songshan = next(item for item in events if item["id"] == "songshan_battle")

    assert "殉国" not in wuyin["title"]
    assert "本局按盘面软判" in wuyin["summary"]
    assert "卢象升得" not in wuyin["resolve_condition"]
    assert "卢象升孤军战死" not in wuyin["fail_condition"]
    assert "卢象升生死由软判" in wuyin["precondition"]
    assert "本局按盘面软判援锦主帅" in songshan["summary"]
    assert "洪承畴率" not in songshan["summary"]
    assert "洪承畴稳" not in songshan["resolve_condition"]
    assert "洪承畴降金" not in songshan["fail_condition"]


def test_mao_wenlong_event_trigger_respects_outer_transaction_rollback(game):
    """post-merge CMR：event trigger 写入不得提前提交外层普通事务。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))

    with _restore_yuan_as_guanning_commander(db, content):
        db.conn.commit()
        before_logs = db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0]

        db.conn.execute("BEGIN")
        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
            content=content,
        )
        assert out["new_issues"][0]["rejected"] is False
        db.conn.rollback()

        assert db.get_character_status("毛文龙")[0] == "active"
        assert content.characters["毛文龙"].status == "active"
        assert not db.has_event_triggered("mao_wenlong")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs


def test_issue_tracker_rollback_restores_bound_content_when_content_omitted(game):
    """review R3：content 省略时也要 snapshot bind_content() 的人物内存。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))
    content.characters["毛文龙"].status = "active"

    with _restore_yuan_as_guanning_commander(db, content):
        db.conn.commit()

        db.conn.execute("BEGIN")
        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
        )
        assert out["new_issues"][0]["rejected"] is False
        assert content.characters["毛文龙"].status == "dead"
        db.conn.rollback()

        assert db.get_character_status("毛文龙")[0] == "active"
        assert content.characters["毛文龙"].status == "active"


def test_issue_tracker_rollback_removes_dynamic_character_attrs(game):
    """online R3 Gemini：事务中新添的人物动态属性也要随 runtime rollback 清掉。"""
    db, state, content = game
    issues.bind_content(content)
    character = content.characters["毛文龙"]
    if hasattr(character, "_test_runtime_ghost_attr"):
        delattr(character, "_test_runtime_ghost_attr")
    db.conn.commit()

    db.conn.execute("BEGIN")
    issues.apply_issue_tracker_output(db, state, {"advances": []}, content=content)
    character._test_runtime_ghost_attr = "ghost"
    db.conn.rollback()

    assert not hasattr(character, "_test_runtime_ghost_attr")


def test_apply_score_extraction_metric_delta_restores_runtime_on_outer_rollback(game):
    """post-merge CMR R9：外层事务 rollback 后，state.metrics 内存也必须回到事务前。"""
    db, state, content = game
    state.metrics["民心"] = 50
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_score_extraction(
        db,
        state,
        {"metric_delta": {"民心": -7}},
        content=content,
    )
    assert out["metric_delta"]["民心"] == -7
    assert state.metrics["民心"] == 43
    db.conn.rollback()

    assert state.metrics["民心"] == 50


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
        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": ev.id}]},
            content=content,
        )
        assert out["new_issues"][0]["rejected"] is False
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

    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
        content=content,
    )

    assert out["new_issues"][0]["rejected"] is True
    assert "候选" in out["new_issues"][0]["reason"]
    assert db.get_character_status("毛文龙")[0] == "active"
    assert content.characters["毛文龙"].status == "active"
    assert not db.has_event_triggered("mao_wenlong")
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
    issues.apply_event_terminal_states(state, db)
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


def test_yuan_xialing_event_excluded_without_jisi_triggered(game):
    """#191 CMR：袁下狱依赖己巳之变已发生，不能与上游事件同月凭其它事实一起候选。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 12
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning"))
    db.conn.execute(
        "UPDATE characters SET status=?, status_reason=? WHERE name=?",
        ("dead", "袁崇焕双岛斩帅", "毛文龙"),
    )

    cands = issues.gather_candidate_events(state, db)

    assert all(ev.id != "yuan_xialing" for ev in cands)


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


def test_yuan_xialing_event_included_after_jisi_event_issue_triggers(game):
    """#191 CMR：己巳之变真实从 event_pool 触发后，袁下狱上游终态门应可查并打开。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    assert any(ev.id == "jisi_lubian" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 35, "reason": "己巳之变软判敌逼京畿"}},
            "army_delta": {"jingying": {"origin_ref": "盘面自发", "manpower": -5000, "morale": -8, "reason": "己巳之变勤王战损"}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == "triggered"
    assert row["terminal_reason"] == "入塞被遏"

    state.year = 1629
    state.period = 12
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning"))
    db.conn.execute(
        "UPDATE characters SET status=?, status_reason=? WHERE name=?",
        ("dead", "袁崇焕双岛斩帅", "毛文龙"),
    )

    assert any(ev.id == "yuan_xialing" for ev in issues.gather_candidate_events(state, db))


def test_legacy_event_pool_issue_backfills_trigger_without_guessing_outcome(game):
    """ADR0014：旧档 event_pool issue 只能补触发记录，不能猜测己巳之变具体结局。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.save_state(state)
    db.insert_issue(
        state,
        kind="situation",
        title=content.event_by_id["jisi_lubian"].title,
        origin_kind="event_pool",
        origin_ref="jisi_lubian",
        commit=True,
    )
    assert db.conn.execute(
        "SELECT event_id FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone() is None

    db.init_schema()

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == "triggered"
    assert row["terminal_reason"] == ""
    assert row["source"] == "legacy_event_pool"

    state.year = 1629
    state.period = 12
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning"))
    db.conn.execute(
        "UPDATE characters SET status=?, status_reason=? WHERE name=?",
        ("dead", "袁崇焕双岛斩帅", "毛文龙"),
    )

    assert all(ev.id != "yuan_xialing" for ev in issues.gather_candidate_events(state, db))


def test_legacy_event_trigger_terminal_reason_can_be_filled_by_real_outcome(game):
    """旧档 backfill 只能占位；同事件后续真实结局标签到达时应补写空 terminal_reason。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 11
    db.save_state(state)
    db.insert_issue(
        state,
        kind="situation",
        title=content.event_by_id["jisi_lubian"].title,
        origin_kind="event_pool",
        origin_ref="jisi_lubian",
        commit=True,
    )
    db.init_schema()
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": ""}

    db.mark_event_triggered(state, "jisi_lubian", terminal_reason="入塞被遏")

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("jisi_lubian",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "入塞被遏"}


def test_person_write_state_restore_removes_dynamic_character_attrs(game):
    """人事写口失败回滚必须删除快照中不存在的动态属性，避免内存幽灵状态残留。"""
    db, _state, content = game
    snapshot = issues._snapshot_person_write_state(db, content)
    content.characters["毛文龙"].ghost_preflight_attr = "leak"

    issues._restore_person_write_state(db, content, snapshot, commit=False)

    assert not hasattr(content.characters["毛文龙"], "ghost_preflight_attr")


def test_legacy_person_core_static_fields_backfill_reachability(game):
    """#191 CMR R4：旧档缺新增静态人物字段时，schema 迁移应补回人物核心门底座。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET location='', transit_to='' WHERE name=?",
        ("毛文龙",),
    )
    db.conn.execute(
        "UPDATE characters SET status='offstage', debut_year=0, debut_month=0 WHERE name IN (?, ?)",
        ("李自成", "张献忠"),
    )
    db.conn.commit()

    db.init_schema()

    mao = db.conn.execute(
        "SELECT location FROM characters WHERE name=?",
        ("毛文龙",),
    ).fetchone()
    li = db.conn.execute(
        "SELECT debut_year, debut_month FROM characters WHERE name=?",
        ("李自成",),
    ).fetchone()
    zhang = db.conn.execute(
        "SELECT debut_year, debut_month FROM characters WHERE name=?",
        ("张献忠",),
    ).fetchone()
    assert mao["location"] == "dongjiang_area"
    assert (li["debut_year"], li["debut_month"]) == (1634, 1)
    assert (zhang["debut_year"], zhang["debut_month"]) == (1631, 1)

    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", ("袁崇焕", "guanning"))
    assert any(ev.id == "mao_wenlong" for ev in issues.gather_candidate_events(state, db))

    state.year = 1631
    state.period = 1
    debuted = db.apply_historical_debuts(state)
    assert any(item["name"] == "张献忠" for item in debuted)

    state.year = 1634
    state.period = 1
    db.conn.execute("UPDATE powers SET military_strength=? WHERE id=?", (50, "bandit_li_zicheng"))
    debuted = db.apply_historical_debuts(state)
    assert any(item["name"] == "李自成" for item in debuted)
    assert any(ev.id == "li_chenghai" for ev in issues.gather_candidate_events(state, db))

    state.year = 1639
    state.period = 5
    db.conn.execute(
        "UPDATE characters SET power_id=?, location=? WHERE name=?",
        ("ming", "huguang", "张献忠"),
    )
    db.conn.execute("UPDATE regions SET unrest=? WHERE id=?", (55, "huguang"))
    assert any(ev.id == "zhangxianzhong_zaifan" for ev in issues.gather_candidate_events(state, db))


def test_person_core_static_backfill_preserves_relocated_mao(game):
    """#191 CMR R4：旧档静态补丁不能覆盖玩家已落库的调离规避状态。"""
    db, _state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='' WHERE name=?",
        ("beizhili", "毛文龙"),
    )
    db.conn.commit()

    db.init_schema()

    row = db.conn.execute(
        "SELECT location FROM characters WHERE name=?",
        ("毛文龙",),
    ).fetchone()
    assert row["location"] == "beizhili"


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
    assert db.get_character_status("李自成")[0] == "active"
    assert any(ev.id == "li_chenghai" for ev in cands)


def test_zhangxianzhong_event_opens_after_historical_debut_and_surrender_path(game):
    """#191 CMR R3：张献忠不能被 offstage+debut 0 卡死；招抚态落库后再反门应可达。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1

    debuted = db.apply_historical_debuts(state)

    assert any(item["name"] == "张献忠" for item in debuted)
    assert db.get_character_status("张献忠")[0] == "active"

    state.year = 1639
    state.period = 5
    db.conn.execute(
        "UPDATE characters SET power_id=?, location=? WHERE name=?",
        ("ming", "huguang", "张献忠"),
    )
    db.conn.execute("UPDATE regions SET unrest=? WHERE id=?", (55, "huguang"))

    assert any(ev.id == "zhangxianzhong_zaifan" for ev in issues.gather_candidate_events(state, db))


def test_issue_191_person_core_events_are_explicitly_classified(content):
    """#191：人物核心类逐事件显式标注；战略/外敌点名将不误纳入。"""
    expected = {
        "mao_wenlong": (
            ["毛文龙"],
            {"character.毛文龙.status", "character.毛文龙.location", "character.袁崇焕.status", "army.guanning.commander"},
        ),
        "yuan_xialing": (
            ["袁崇焕"],
            {"character.袁崇焕.status", "army.guanning.commander", "character.毛文龙.status", "character.毛文龙.status_reason", "event.jisi_lubian.terminal_state", "event.jisi_lubian.terminal_reason"},
        ),
        "kong_youde": (
            ["孔有德"],
            {"character.孔有德.status", "character.孔有德.power_id", "character.孔有德.location", "character.毛文龙.status"},
        ),
        "li_chenghai": (
            ["李自成"],
            {"character.李自成.status", "character.李自成.power_id", "character.李自成.location", "region.shaanxi.unrest", "power.bandit_li_zicheng.military_strength"},
        ),
        "zhangxianzhong_zaifan": (
            ["张献忠"],
            {"character.张献忠.status", "character.张献忠.power_id", "character.张献忠.loyalty", "character.张献忠.location"},
        ),
    }
    for event_id, (subjects, gate_keys) in expected.items():
        ev = content.event_by_id[event_id]
        assert ev.person_core_subjects == subjects
        assert gate_keys <= set(ev.trigger_gate)

    not_person_core = {
        "jisi_lubian",
        "dalingghe",
        "lindan_xiqian",
        "huangtaiji_chengdi",
        "wuyin_lubian",
        "songshan_battle",
        "luoyang_fallen",
    }
    assert not {
        event_id for event_id in not_person_core
        if content.event_by_id[event_id].person_core_subjects
    }


def test_issue_194_strategic_foreign_events_are_explicitly_classified_and_gated(content):
    """#194：战略/外敌类事件显式分类，且每条都有结构化 trigger_gate。"""
    raw_by_id = {
        str(item["id"]): item
        for item in json.loads(
            (Path(__file__).resolve().parents[1] / "content" / "events.json").read_text(
                encoding="utf-8"
            )
        )
    }
    expected = {
        "jisi_lubian": {},
        "dalingghe": {
            "region.liaodong.controlled_by": "==ming",
            "army.guanning.supply": "<=45",
            "army.guanning.arrears": ">=40",
            "power.houjin.military_strength": ">=70",
        },
        "lindan_xiqian": {
            "region.mongol_chahar.controlled_by": "==mongol",
            "army.mongol_chahar_host.loyalty": "<=45",
            "power.mongol.military_strength": "<=55",
            "power.houjin.military_strength": ">=70",
        },
        "wuyin_lubian": {
            "army.jizhen.arrears": ">=10",
            "army.xuan_da.morale": "<=55",
            "power.mongol.military_strength": "<=55",
            "power.houjin.military_strength": ">=75",
        },
        "songshan_battle": {
            "region.liaodong.controlled_by": "==ming",
            "army.guanning.supply": "<=45",
            "army.guanning.morale": "<=55",
            "power.houjin.military_strength": ">=70",
        },
        "luoyang_fallen": {
            "region.henan.controlled_by": "==ming",
            "region.henan.unrest": ">=60",
            "power.bandit_li_zicheng.military_strength": ">=45",
        },
        "kaifeng_siege": {
            "event.luoyang_fallen.terminal_state": "==triggered",
            "region.henan.controlled_by": "==ming",
            "region.henan.military_pressure": ">=70",
            "power.bandit_li_zicheng.military_strength": ">=55",
        },
        "beijing_fallen": {
            "region.beizhili.controlled_by": "==ming",
            "region.beizhili.military_pressure": ">=85",
            "army.jingying.morale": "<=40",
            "army.jingying.loyalty": "<=45",
            "power.bandit_li_zicheng.military_strength": ">=65",
        },
    }

    for event_id, trigger_gate in expected.items():
        raw = raw_by_id[event_id]
        ev = content.event_by_id[event_id]
        assert raw["trigger_class"] == "strategic_foreign"
        assert raw["trigger_gate"] == trigger_gate
        assert ev.trigger_class == "strategic_foreign"
        assert ev.event_type in {"node", "ending"}
        assert ev.trigger_gate == trigger_gate
        assert ev.person_core_subjects == []


def test_strategic_foreign_classification_requires_outcome_targets(content, monkeypatch):
    """PR R3：trigger_class 是内容真源，消费者 target map 漏项必须启动期 fail-loud。"""
    targets = dict(issues._STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS)
    targets.pop("luoyang_fallen")
    monkeypatch.setattr(issues, "_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS", targets)

    with pytest.raises(SystemExit, match="luoyang_fallen.*outcome target"):
        issues.bind_content(content)


def test_issue_194_dead_named_general_does_not_obsolete_strategic_foreign_event(game):
    """#194：战略/外敌事件点名将是席位/软判对象，不因该将死亡作废。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 8
    db.set_character_status(state, "祖大寿", "dead", reason="测试：大凌河前已阵亡")

    terminalized = issues.apply_event_terminal_states(state, db)
    cands = issues.gather_candidate_events(state, db)

    assert all(item["id"] != "dalingghe" for item in terminalized)
    assert any(ev.id == "dalingghe" for ev in cands)
    row = db.conn.execute(
        "SELECT terminal_state FROM event_triggers WHERE event_id=?",
        ("dalingghe",),
    ).fetchone()
    assert row is None


def test_issue_194_dalingghe_requires_world_state_main_ledger_result(game):
    """#194：新增战略/外敌事件复用 S3，同信封缺主账则拒收，有主账才记触发。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 8
    assert any(ev.id == "dalingghe" for ev in issues.gather_candidate_events(state, db))

    missing = issues.apply_score_extraction(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "dalingghe"}]},
        content=content,
    )

    assert missing["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in missing["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("dalingghe")

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "dalingghe"}],
            "region_delta": {
                "liaodong": {
                    "origin_ref": "盘面自发", "military_pressure": 8,
                    "reason": "大凌河之围软判：后金围城，辽东军压上升",
                }
            },
        },
        content=content,
    )

    assert applied["issue_summary"]["new_issues"][0]["rejected"] is False
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("dalingghe",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": ""}


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
    assert db.has_event_triggered("huabei_plague")
    assert all(ev.id != "huabei_plague" for ev in issues.gather_candidate_events(state, db))
    after = db.conn.execute(
        "SELECT population, unrest FROM regions WHERE id=?",
        ("shanxi",),
    ).fetchone()
    assert after["population"] == before["population"] - 400000  # #648：新档人口单位=人（ADR 0088），content -40万
    assert after["unrest"] == before["unrest"] + 6


def test_historical_auto_trigger_core_effect_is_applied_once(game):
    """#192：确定性核心事实重进不应二次扣数，event_triggers 是硬幂等门。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7

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


def test_auto_trigger_historical_events_use_preloaded_terminal_refs(game, monkeypatch):
    """PR review：历史 auto_trigger 去重应批量读 event_triggers，避免每事件查 terminal_state。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1633
    state.period = 7

    def _unexpected_per_event_probe(*_args, **_kwargs):
        raise AssertionError("auto_trigger historical loop must not call event_terminal_state per event")

    monkeypatch.setattr(type(db), "event_terminal_state", _unexpected_per_event_probe)

    triggered = issues.auto_trigger_seed_issues(state, db)

    assert any(item["id"] == "huabei_plague" for item in triggered)


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
        assert db.event_terminal_state("__test_expiring_historical_auto__") == "expired"
        assert db.find_any_issue_by_origin("event_pool", "__test_expiring_historical_auto__") is None
    finally:
        content.events.remove(ev)


def test_gated_auto_trigger_seed_event_can_recur_after_previous_issue_resolved(game):
    """PR review：seed auto_trigger 带 gate 时，旧 resolved issue 不应永久压住再触发。"""
    db, state, content = game
    issues.bind_content(content)
    ev = _hist_event("__test_recurring_auto_seed__", {"民心": "<=5"})
    ev.auto_trigger = True
    ev.event_type = "situation"
    content.seed_events.append(ev)
    try:
        state.metrics["民心"] = 3
        first = issues.auto_trigger_seed_issues(state, db)
        first_item = next(item for item in first if item["id"] == "__test_recurring_auto_seed__")
        db.conn.execute(
            "UPDATE issues SET status='resolved' WHERE id=?",
            (first_item["issue_id"],),
        )
        db.conn.commit()

        second = issues.auto_trigger_seed_issues(state, db)

        second_item = next(item for item in second if item["id"] == "__test_recurring_auto_seed__")
        assert second_item["issue_id"] != first_item["issue_id"]
    finally:
        content.seed_events.remove(ev)


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

    monkeypatch.setattr(issues, "_apply_issue_entities", boom)

    with pytest.raises(RuntimeError, match="boom after issue insert"):
        issues.auto_trigger_seed_issues(state, db)

    assert db.conn.execute(
        "SELECT 1 FROM issues WHERE origin_kind=? AND origin_ref=?",
        ("event_pool", "huabei_plague"),
    ).fetchone() is None
    assert not db.has_event_triggered("huabei_plague")


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
    assert db.has_event_triggered("huabei_plague")
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
    assert db.has_event_triggered("jingshi_plague")
    assert all(ev.id != "jingshi_plague" for ev in issues.gather_candidate_events(state, db))
    after = db.conn.execute(
        "SELECT manpower, morale FROM armies WHERE id=?",
        ("jingying",),
    ).fetchone()
    assert after["manpower"] == before["manpower"] - 51000
    assert after["morale"] == before["morale"] - 16


def test_huangtaiji_chengdi_auto_triggers_and_renames_houjin(game):
    """#192：皇太极称帝核心事实确定性落库，后金稳定 id 展示为大清。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1636
    state.period = 4

    triggered = issues.auto_trigger_seed_issues(state, db)

    assert any(item["id"] == "huangtaiji_chengdi" for item in triggered)
    assert db.has_event_triggered("huangtaiji_chengdi")
    assert all(ev.id != "huangtaiji_chengdi" for ev in issues.gather_candidate_events(state, db))
    row = db.conn.execute(
        "SELECT name, aliases, status, last_action FROM powers WHERE id=?",
        ("houjin",),
    ).fetchone()
    assert row["name"] == "大清"
    assert "后金" in row["aliases"]
    assert "大清" in row["aliases"]
    assert "称帝" in row["status"]
    assert row["last_action"] == "皇太极称帝改国号大清"


def test_huangtaiji_chengdi_keeps_diplomatic_response_axis_as_situation_issue(game):
    """#192：称帝核心事实硬落后，承不承认伪号/联蒙抗清仍要留给软判推进。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1636
    state.period = 4

    triggered = issues.auto_trigger_seed_issues(state, db)

    item = next(entry for entry in triggered if entry["id"] == "huangtaiji_chengdi")
    assert item["issue_id"] > 0
    issue = db.conn.execute(
        "SELECT status, kind, origin_kind, origin_ref FROM issues WHERE id=?",
        (item["issue_id"],),
    ).fetchone()
    assert dict(issue) == {
        "status": "active",
        "kind": "situation",
        "origin_kind": "event_pool",
        "origin_ref": "huangtaiji_chengdi",
    }


def test_historical_power_rename_tick_reads_huangtaiji_event_effect(game):
    """CMR：月初展示名 tick 也读事件 effect，避免同一称帝事实维护两份文案。"""
    db, state, content = game
    ev = content.event_by_id["huangtaiji_chengdi"]
    rename = ev.effect_on_trigger["power_renames"][0]
    original = dict(rename)
    try:
        rename.update(
            {
                "new_name": "测试清",
                "aliases": "后金，测试清",
                "reason": "测试称帝事实",
                "status": "测试称帝状态",
                "last_action": "测试称帝行动",
            }
        )
        state.year = 1636
        state.period = 4

        changed = db.apply_historical_power_renames(state)

        assert changed and changed[0]["new_name"] == "测试清"
        row = db.conn.execute(
            "SELECT name, aliases, status, last_action FROM powers WHERE id=?",
            ("houjin",),
        ).fetchone()
        assert dict(row) == {
            "name": "测试清",
            "aliases": "后金，测试清",
            "status": "测试称帝状态",
            "last_action": "测试称帝行动",
        }
    finally:
        rename.clear()
        rename.update(original)


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

        out = issues.apply_issue_tracker_output(
            db,
            state,
            {
                "advances": [{"issue_id": issue_id, "delta_bar": 1, "metric_delta": {"民心": -15}}],
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
            },
            content=content,
        )

        assert state.metrics["民心"] == 5
        assert out["new_issues"][0]["rejected"] is True
        assert "候选" in out["new_issues"][0]["reason"]
        assert not db.has_event_triggered(ev.id)
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

        out = issues.apply_score_extraction(
            db,
            state,
            {
                "metric_delta": {"民心": -15},
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
            },
            content=content,
        )

        assert state.metrics["民心"] == 5
        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
        assert not db.has_event_triggered(ev.id)
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

        out = issues.apply_issue_tracker_output(
            db,
            state,
            {
                "advances": [{"issue_id": issue_id, "delta_bar": 1, "metric_delta": {"民心": -15}}],
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
            },
            content=content,
        )

        assert state.metrics["民心"] == 5
        assert out["new_issues"][0]["rejected"] is True
        assert "候选" in out["new_issues"][0]["reason"]
        assert not db.has_event_triggered(ev.id)
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

        out = issues.apply_issue_tracker_output(
            db,
            state,
            {
                "new_issues": [
                    {"origin_kind": "event_pool", "id": first.id},
                    {"origin_kind": "event_pool", "id": second.id},
                ]
            },
            content=content,
        )

        assert out["new_issues"][0]["rejected"] is False
        assert db.get_character_status("袁崇焕")[0] == "dismissed"
        assert out["new_issues"][1]["rejected"] is True
        assert "候选" in out["new_issues"][1]["reason"]
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
    out = issues.apply_issue_tracker_output(
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
    )
    assert out["new_issues"][0]["rejected"] is False
    issue_id = out["new_issues"][0]["issue_id"]
    db.conn.rollback()

    assert db.conn.execute("SELECT id FROM issues WHERE id=?", (issue_id,)).fetchone() is None


def test_issue_tracker_advance_respects_outer_transaction_rollback(game):
    """post-merge CMR R4：advances 段不得由 db.advance_issue 提前提交外层事务。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·推进事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="推进前",
        effect_on_fail={"metrics": {"民心": -1}},
    )
    before_advances = db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0]
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"advances": [{"issue_id": issue_id, "delta_bar": 7, "stage_text": "推进后"}]},
    )
    assert out["advances"][0]["status"] == "active"
    db.conn.rollback()

    row = db.conn.execute("SELECT bar_value, stage_text, status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert dict(row) == {"bar_value": 40, "stage_text": "推进前", "status": "active"}
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0] == before_advances


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
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"advances": [{"issue_id": issue_id, "delta_bar": 10, "stage_text": "办成"}]},
    )
    assert out["advances"][0]["status"] == "resolved"
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


def test_issue_tracker_close_respects_outer_transaction_rollback(game):
    """post-merge CMR R4：close_issues 段不得由 db.close_issue 提前提交外层事务。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="测试·结案事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="结案前",
        effect_on_resolve={"metrics": {"民心": 1}},
        effect_on_fail={"metrics": {"民心": -1}},
    )
    before_advances = db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0]
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    )
    assert out["closes"][0]["reason"] == "resolved"
    db.conn.rollback()

    row = db.conn.execute("SELECT bar_value, stage_text, status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert dict(row) == {"bar_value": 40, "stage_text": "结案前", "status": "active"}
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0] == before_advances


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
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    )
    assert out["closes"][0]["reason"] == "resolved"
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
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    )
    assert out["closes"][0]["reason"] == "resolved"
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
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "结案"}]},
    )
    assert out["closes"][0]["reason"] == "resolved"
    db.conn.rollback()

    issue_row = db.conn.execute("SELECT status, bar_value FROM issues WHERE id=?", (issue_id,)).fetchone()
    legacy_row = db.conn.execute("SELECT status FROM legacies WHERE id=?", (legacy_id,)).fetchone()
    assert dict(issue_row) == {"status": "active", "bar_value": 40}
    assert legacy_row["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0


def test_apply_issue_entities_person_changes_respect_commit_false(game):
    """post-merge CMR R6：_apply_issue_entities(commit=False) 的人物 DB 写入不得自行提交。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "毛文龙"))
    db.conn.commit()
    before_logs = db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?",
        ("毛文龙",),
    ).fetchone()[0]

    issues._apply_issue_entities(
        db,
        state,
        {
            "人物变更": [
                {"origin_ref": "盘面自发", "name": "毛文龙", "动作": "处置", "status": "dismissed", "reason": "测试 helper no-commit"}
            ]
        },
        "测试 helper no-commit",
        content=content,
        commit=False,
    )
    db.conn.rollback()

    assert db.get_character_status("毛文龙")[0] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?",
        ("毛文龙",),
    ).fetchone()[0] == before_logs


def test_apply_score_extraction_top_level_economy_respects_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 economy_moves 不得自行提交外层事务。"""
    db, state, content = game
    reason = "测试顶层经济事务R7"
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_score_extraction(
        db,
        state,
        {"economy_moves": [{"origin_ref": "盘面自发", "account": "国库", "delta": -1, "category": "测试", "reason": reason}]},
        content=content,
    )
    assert out["economy_moves"][0]["reason"] == reason
    db.conn.rollback()

    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE reason=?",
        (reason,),
    ).fetchone()[0] == 0


def test_apply_score_extraction_fiscal_changes_respect_outer_transaction_rollback(game):
    """post-merge CMR R7：顶层 fiscal_changes 不得由 fiscal_config helper 提前提交。"""
    db, state, content = game
    key, before = next(iter(db.get_fiscal_config().items()))
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_score_extraction(
        db,
        state,
        {"fiscal_changes": [{"origin_ref": "盘面自发", "key": key, "delta": 1, "reason": "测试顶层财政事务R7"}]},
        content=content,
    )
    assert out["fiscal_changes"][0]["key"] == key
    db.conn.rollback()

    assert db.get_fiscal_config()[key] == before


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
    out = issues.apply_score_extraction(
        db,
        state,
        {"class_delta": {class_key: {"satisfaction": -1}}},
        content=content,
    )
    assert out["class_delta"][class_key]["satisfaction"] == -1
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
    out = issues.apply_score_extraction(
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
                    "reason": "测试顶层建军事务R7",
                }
            ],
        },
        content=content,
    )
    assert out["region_changes"]
    assert out["army_changes"]
    assert out["power_changes"]
    assert out["faction_delta"]
    assert out["created_armies"][0]["id"] == new_army_id
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
    remove_key = next(iter(db.get_fiscal_config()))
    created_key = "__test_fiscal_txn_r7_base"
    created_rate_key = "__test_fiscal_txn_r7_rate"
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_score_extraction(
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
    assert out["fiscal_removes"][0]["key"] == f"{db._stem_of(remove_key)}_base"
    assert out["fiscal_creates"][0]["key"] == created_key
    db.conn.rollback()

    assert remove_key in db.get_fiscal_config()
    assert db.conn.execute(
        "SELECT key FROM fiscal_config WHERE key IN (?, ?)",
        (created_key, created_rate_key),
    ).fetchall() == []


def test_event_pool_pending_person_location_change_blocks_gate(game):
    """post-merge CMR R6：同回合行止改变 location 时，事件 text gate 不得沿用旧地点。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, location=?, transit_to='' WHERE name=?",
        ("active", "liaodong", "毛文龙"),
    )
    if "毛文龙" in content.characters:
        content.characters["毛文龙"].status = "active"
        content.characters["毛文龙"].location = "liaodong"
        content.characters["毛文龙"].transit_to = ""
    ev = Event(
        id="__test_pending_location_gate__",
        title="测试·行止地点门",
        kind="朝议",
        summary="毛文龙仍在辽东才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.毛文龙.location": "== liaodong"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert any(c.id == ev.id for c in issues.gather_candidate_events(state, db))

        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "行止", "location": "beizhili"}],
            },
            content=content,
        )

        new_issue = out["issue_summary"]["new_issues"][0]
        assert new_issue["rejected"] is True
        assert "候选" in new_issue["reason"]
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
        assert db.conn.execute(
            "SELECT location FROM characters WHERE name=?",
            ("毛文龙",),
        ).fetchone()["location"] == "beizhili"
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_invalid_appointment_does_not_block_gate(game):
    """post-merge CMR R7：会被任命转移矩阵拒收的人物变更，不应提前阻断事件门。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("dead", "袁崇焕"))
    if "袁崇焕" in content.characters:
        content.characters["袁崇焕"].status = "dead"
    ev = Event(
        id="__test_invalid_appointment_pending__",
        title="测试·非法任命不阻断",
        kind="朝议",
        summary="袁崇焕已死时可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.status": "== dead"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "任命", "office": "兵部尚书"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is False
        assert out["applied_person_changes"][0]["rejected"] is True
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_invalid_allegiance_change_does_not_block_gate(game):
    """post-merge CMR R7：缺方式/反噬的易主拒收项，不应提前阻断 power_id 门。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status=?, power_id=? WHERE name=?", ("active", "ming", "袁崇焕"))
    if "袁崇焕" in content.characters:
        content.characters["袁崇焕"].status = "active"
        content.characters["袁崇焕"].power_id = "ming"
    ev = Event(
        id="__test_invalid_allegiance_pending__",
        title="测试·非法易主不阻断",
        kind="朝议",
        summary="袁崇焕仍属明时可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.power_id": "== ming"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "易主", "new_power": "houjin"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is False
        assert out["applied_person_changes"][0]["rejected"] is True
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_disposition_clears_office_gate(game):
    """post-merge CMR R7：同回合处置会清空 office，事件门不得沿用旧职。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, office=?, office_type=? WHERE name=?",
        ("active", "蓟辽督师", "职名分", "袁崇焕"),
    )
    if "袁崇焕" in content.characters:
        ch = content.characters["袁崇焕"]
        ch.status = "active"
        ch.office = "蓟辽督师"
        ch.office_type = "职名分"
    ev = Event(
        id="__test_disposition_clears_office_pending__",
        title="测试·处置清职门",
        kind="朝议",
        summary="袁崇焕仍为督师时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.office": "== 蓟辽督师"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert any(c.id == ev.id for c in issues.gather_candidate_events(state, db))

        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "测试罢离督师"}],
            },
            content=content,
        )

        new_issue = out["issue_summary"]["new_issues"][0]
        assert new_issue["rejected"] is True
        assert "候选" in new_issue["reason"]
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?",
            ("袁崇焕",),
        ).fetchone()["office"] == ""
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_location_change_clears_transit_gate(game):
    """post-merge CMR R7：同回合行止会清空 transit_to，事件门不得沿用旧在途目的地。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, location=?, transit_to=? WHERE name=?",
        ("active", "liaodong", "beizhili", "毛文龙"),
    )
    if "毛文龙" in content.characters:
        ch = content.characters["毛文龙"]
        ch.status = "active"
        ch.location = "liaodong"
        ch.transit_to = "beizhili"
    ev = Event(
        id="__test_location_clears_transit_pending__",
        title="测试·行止清在途门",
        kind="朝议",
        summary="毛文龙仍在途入京时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.毛文龙.transit_to": "== beizhili"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert any(c.id == ev.id for c in issues.gather_candidate_events(state, db))

        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "行止", "location": "liaodong"}],
            },
            content=content,
        )

        new_issue = out["issue_summary"]["new_issues"][0]
        assert new_issue["rejected"] is True
        assert "候选" in new_issue["reason"]
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
        assert db.conn.execute(
            "SELECT transit_to FROM characters WHERE name=?",
            ("毛文龙",),
        ).fetchone()["transit_to"] == ""
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_rejected_legacy_gate_change_does_not_block(game):
    """post-merge CMR R6：会被 legacy_gate 拒收的人物变更，不应提前阻断事件门。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("dismissed", "袁崇焕"))
    if "袁崇焕" in content.characters:
        content.characters["袁崇焕"].status = "dismissed"
    ev = Event(
        id="__test_rejected_legacy_gate_pending__",
        title="测试·legacy gate 拒收不阻断",
        kind="朝议",
        summary="袁崇焕已罢黜时可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.status": "== dismissed"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": ev.id}]},
            content=content,
            pending_person_changes_for_gates=[
                {"name": "袁崇焕", "动作": "处置", "status": "dead", "reason": "测试 legacy gate", "legacy_gate": True}
            ],
        )

        assert out["new_issues"][0]["rejected"] is False
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_legacy_power_change_blocks_gate(game):
    """post-merge CMR R8：旧 flat 易主会真实落库，pending 闸门也必须按同一语义预检。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=? WHERE name=?",
        ("active", "ming", "袁崇焕"),
    )
    if "袁崇焕" in content.characters:
        ch = content.characters["袁崇焕"]
        ch.status = "active"
        ch.power_id = "ming"
    ev = Event(
        id="__test_legacy_power_pending__",
        title="测试·旧易主门",
        kind="朝议",
        summary="袁崇焕仍属明时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.power_id": "== ming"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        assert any(c.id == ev.id for c in issues.gather_candidate_events(state, db))

        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "character_power_changes": [
                    {"origin_ref": "盘面自发", "name": "袁崇焕", "new_power": "houjin", "reason": "测试旧易主"}
                ],
            },
            content=content,
        )

        new_issue = out["issue_summary"]["new_issues"][0]
        assert new_issue["rejected"] is True
        assert "候选" in new_issue["reason"]
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
        assert db.conn.execute(
            "SELECT power_id FROM characters WHERE name=?",
            ("袁崇焕",),
        ).fetchone()["power_id"] == "houjin"
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_same_power_allegiance_noop_does_not_block_gate(game):
    """post-merge CMR R8：同势力易主是 no-op，不能先把职名覆盖成身份名分再误阻断。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "蓟辽督师", "职名分", "袁崇焕"),
    )
    if "袁崇焕" in content.characters:
        ch = content.characters["袁崇焕"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "蓟辽督师"
        ch.office_type = "职名分"
    ev = Event(
        id="__test_same_power_noop_pending__",
        title="测试·同势力易主 no-op",
        kind="朝议",
        summary="袁崇焕仍为督师时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.office": "== 蓟辽督师"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [
                    {
                        "origin_ref": "盘面自发", "name": "袁崇焕",
                        "动作": "易主",
                        "new_power": "ming",
                        "方式": "主动归附",
                        "反噬": {},
                        "reason": "测试同势力 no-op",
                    }
                ],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is False
        assert out["applied_person_changes"][0]["rejected"] is True
        assert out["applied_person_changes"][0]["category"] == "noop"
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?",
            ("袁崇焕",),
        ).fetchone()["office"] == "蓟辽督师"
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_allegiance_backlash_blocks_power_gate(game):
    """post-merge CMR R11：易主反噬会真实改 power.*，pending 闸门也必须看同回合副作用。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE powers SET leverage=? WHERE id=?",
        (80, "houjin"),
    )
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "蓟辽督师", "职名分", "袁崇焕"),
    )
    if "袁崇焕" in content.characters:
        ch = content.characters["袁崇焕"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "蓟辽督师"
        ch.office_type = "职名分"
    ev = Event(
        id="__test_power_backlash_pending__",
        title="测试·势力反噬门",
        kind="朝议",
        summary="后金威望仍高涨时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"power.houjin.leverage": ">=75"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [
                    {
                        "origin_ref": "盘面自发", "name": "袁崇焕",
                        "动作": "易主",
                        "new_power": "houjin",
                        "方式": "被俘而降",
                        "反噬": {"houjin": {"leverage": -10}},
                        "reason": "测试反噬后门不达标",
                    }
                ],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        assert db.conn.execute(
            "SELECT leverage FROM powers WHERE id=?",
            ("houjin",),
        ).fetchone()["leverage"] == 70
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_person_changes_are_simulated_sequentially(game):
    """post-merge CMR R8：同一人的 pending 变更必须按顺序模拟，后续拒收项不能复活前序处置。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute(
        "UPDATE characters SET loyalty=?, status=? WHERE name=?",
        (44, "active", "毛文龙"),
    )
    db.conn.execute("UPDATE characters SET status=? WHERE name=?", ("active", "袁崇焕"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}],
            "人物变更": [
                {"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "处置", "status": "dead", "reason": "测试先处死"},
                {"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "任命", "office": "兵部尚书", "reason": "测试后任命"},
            ],
        },
        content=content,
    )

    new_issue = out["issue_summary"]["new_issues"][0]
    assert new_issue["rejected"] is True
    assert "候选" in new_issue["reason"]
    assert not db.has_event_triggered("mao_wenlong")
    assert db.get_character_status("毛文龙")[0] == "active"
    assert db.get_character_status("袁崇焕")[0] == "dead"
    assert out["applied_person_changes"][0]["status"] == "dead"
    assert out["applied_person_changes"][1]["rejected"] is True


def test_apply_score_extraction_registry_refresh_rolls_back_with_outer_transaction(game):
    """post-merge CMR R11：外层事务回滚时，任命刷新过的 registry 也要回到旧身份。"""
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

    class _OfficeSnapshotRegistry:
        def __init__(self):
            self.agents = {"韩爌": "内阁首辅"}
            self.session_ids = {"韩爌": "minister-韩爌-turn-test"}

        def refresh(self, name):
            self.agents[name] = content.characters[name].office

    registry = _OfficeSnapshotRegistry()

    with pytest.raises(RuntimeError):
        with atomic(db):
            issues.apply_score_extraction(
                db,
                state,
                {"人物变更": [{"origin_ref": "盘面自发", "name": "韩爌", "动作": "任命", "office": "兵部尚书"}]},
                content=content,
                registry=registry,
            )
            assert registry.agents["韩爌"] == "兵部尚书"
            raise RuntimeError("rollback registry probe")

    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?",
        ("韩爌",),
    ).fetchone()["office"] == "内阁首辅"
    assert content.characters["韩爌"].office == "内阁首辅"
    assert registry.agents == {"韩爌": "内阁首辅"}
    assert registry.session_ids == {"韩爌": "minister-韩爌-turn-test"}


def test_event_pool_pending_alias_appointment_blocks_canonical_gate(game):
    """post-merge CMR R9：任命别名会真实归一到在册大臣，pending 闸门也必须看规范名。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "内阁首辅", "职名分", "韩爌"),
    )
    if "韩爌" in content.characters:
        ch = content.characters["韩爌"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "内阁首辅"
        ch.office_type = "职名分"
    ev = Event(
        id="__test_alias_appointment_pending__",
        title="测试·别名任命门",
        kind="朝议",
        summary="韩爌仍为首辅时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.韩爌.office": "== 内阁首辅"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "韩阁老", "动作": "任命", "office": "兵部尚书"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        assert out["applied_person_changes"][0]["name"] == "韩爌"
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?",
            ("韩爌",),
        ).fetchone()["office"] == "兵部尚书"
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_alias_disposition_blocks_canonical_gate(game):
    """online R1 Gemini：非任命动作也会用别名，pending 闸门须按规范名重算。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "内阁首辅", "职名分", "韩爌"),
    )
    if "韩爌" in content.characters:
        ch = content.characters["韩爌"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "内阁首辅"
        ch.office_type = "职名分"
    ev = Event(
        id="__test_alias_disposition_pending__",
        title="测试·别名处置门",
        kind="朝议",
        summary="韩爌仍为首辅时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.韩爌.office": "== 内阁首辅"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [
                    {"origin_ref": "盘面自发", "name": "韩阁老", "动作": "处置", "status": "dismissed", "reason": "测试别名处置"}
                ],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        assert out["applied_person_changes"][0]["name"] == "韩爌"
        row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?",
            ("韩爌",),
        ).fetchone()
        assert row["status"] == "dismissed"
        assert row["office"] == ""
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_pending_person_gate_prefetches_character_rows_for_displacement(game):
    """online R1 Gemini：独占官职顶替模拟不得对每个人物逐条 SELECT。"""
    db, _state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "蓟辽督师", "职名分", "袁崇焕"),
    )
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "兵部尚书,左都御史", "兵部", "崔呈秀"),
    )
    ev = Event(
        id="__test_prefetch_displacement_pending__",
        title="测试·顶替预加载",
        kind="朝议",
        summary="崔呈秀仍兼兵部尚书时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.崔呈秀.office": "== 兵部尚书,左都御史"},
    )
    select_count = 0

    def trace(sql):
        nonlocal select_count
        if sql.lstrip().upper().startswith("SELECT"):
            select_count += 1

    db.conn.set_trace_callback(trace)
    try:
        blocked = issues._pending_person_changes_block_event_gate(
            ev,
            [{"name": "袁崇焕", "动作": "任命", "office": "兵部尚书"}],
            db,
            content=content,
        )
    finally:
        db.conn.set_trace_callback(None)

    assert blocked is True
    assert select_count <= 8


def test_event_pool_pending_gate_reuses_shadow_prefetch_across_new_issues(game, monkeypatch):
    """online R3 Gemini：同一批 event_pool 不应为每个 pending gate 重查全量人物表。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))
    ev1 = Event(
        id="__test_shared_shadow_prefetch_1__",
        title="测试·共享快照一",
        kind="朝议",
        summary="x",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.status": "== active"},
    )
    ev2 = Event(
        id="__test_shared_shadow_prefetch_2__",
        title="测试·共享快照二",
        kind="朝议",
        summary="x",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.status": "== active"},
    )
    content.seed_events.extend([ev1, ev2])
    content.event_by_id[ev1.id] = ev1
    content.event_by_id[ev2.id] = ev2

    def fake_gather_candidate_events(_state, _db):
        return [ev1, ev2]

    full_character_selects = 0

    def trace(sql):
        nonlocal full_character_selects
        normalized = " ".join(sql.split()).upper()
        if "FROM CHARACTERS" in normalized and "STATUS_REASON" in normalized:
            full_character_selects += 1

    monkeypatch.setattr(issues, "gather_candidate_events", fake_gather_candidate_events)
    db.conn.set_trace_callback(trace)
    try:
        out = issues.apply_issue_tracker_output(
            db,
            state,
            {
                "new_issues": [
                    {"origin_kind": "event_pool", "id": ev1.id},
                    {"origin_kind": "event_pool", "id": ev2.id},
                ]
            },
            content=content,
            pending_person_changes_for_gates=[
                {"name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "测试共享快照"}
            ],
            candidate_event_ids_at_input={ev1.id, ev2.id},
        )
    finally:
        db.conn.set_trace_callback(None)
        content.seed_events.remove(ev1)
        content.seed_events.remove(ev2)
        content.event_by_id.pop(ev1.id, None)
        content.event_by_id.pop(ev2.id, None)

    assert [item["rejected"] for item in out["new_issues"]] == [True, True]
    assert full_character_selects == 1


def test_event_pool_pending_rejected_vassal_appointment_does_not_block_gate(game):
    """post-merge CMR R9：宗藩任命会被真实写口拒收，pending 闸门不得按成功授官误挡。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "福王,就藩洛阳", "宗藩", "朱常洵"),
    )
    if "朱常洵" in content.characters:
        ch = content.characters["朱常洵"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "福王,就藩洛阳"
        ch.office_type = "宗藩"
    ev = Event(
        id="__test_vassal_appointment_pending__",
        title="测试·宗藩拒任不阻断",
        kind="朝议",
        summary="福王仍为宗藩时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.朱常洵.office": "== 福王,就藩洛阳"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "朱常洵", "动作": "任命", "office": "兵部尚书"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is False
        assert out["applied_person_changes"][0]["rejected"] is True
        assert "宗藩" in out["applied_person_changes"][0]["reason"]
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?",
            ("朱常洵",),
        ).fetchone()["office"] == "福王,就藩洛阳"
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is not None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_appointment_displacement_blocks_displaced_office_gate(game):
    """post-merge CMR R9：独占实职顶替会真实改旧任 office，pending 闸门必须模拟被顶替者。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "蓟辽督师", "职名分", "袁崇焕"),
    )
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "兵部尚书,左都御史", "兵部", "崔呈秀"),
    )
    if "袁崇焕" in content.characters:
        ch = content.characters["袁崇焕"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "蓟辽督师"
        ch.office_type = "职名分"
    if "崔呈秀" in content.characters:
        ch = content.characters["崔呈秀"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "兵部尚书,左都御史"
        ch.office_type = "兵部"
    ev = Event(
        id="__test_displacement_pending__",
        title="测试·顶替旧任门",
        kind="朝议",
        summary="崔呈秀仍兼兵部尚书时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.崔呈秀.office": "== 兵部尚书,左都御史"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "任命", "office": "兵部尚书"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?",
            ("崔呈秀",),
        ).fetchone()["office"] == "左都御史"
        assert db.conn.execute(
            "SELECT id FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone() is None
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_appointment_clears_reason_gate(game):
    """post-merge CMR R10：任命起复会真实改 reason_code/status_reason，pending 闸门不得沿用旧缘由。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office='', office_type=?, status_reason=?, reason_code=? WHERE name=?",
        ("dismissed", "ming", "身名分", "获罪削籍", "获罪削籍", "钱谦益"),
    )
    if "钱谦益" in content.characters:
        ch = content.characters["钱谦益"]
        ch.status = "dismissed"
        ch.power_id = "ming"
        ch.office = ""
        ch.office_type = "身名分"
        ch.status_reason = "获罪削籍"
        ch.reason_code = "获罪削籍"
    ev = Event(
        id="__test_reason_gate_pending__",
        title="测试·缘由门",
        kind="朝议",
        summary="钱谦益仍因获罪削籍时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.钱谦益.reason_code": "== 获罪削籍"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "钱谦益", "动作": "任命", "office": "兵部尚书"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        row = db.conn.execute(
            "SELECT status, reason_code, status_reason FROM characters WHERE name=?",
            ("钱谦益",),
        ).fetchone()
        assert row["status"] == "active"
        assert row["reason_code"] == ""
        assert row["status_reason"] != "获罪削籍"
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_appointment_updates_office_type_gate(game):
    """post-merge CMR R10：任命后 office_type 由真实写口推断，pending 闸门也要同步。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "内阁首辅", "内阁", "韩爌"),
    )
    if "韩爌" in content.characters:
        ch = content.characters["韩爌"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "内阁首辅"
        ch.office_type = "内阁"
    ev = Event(
        id="__test_office_type_pending__",
        title="测试·官署门",
        kind="朝议",
        summary="韩爌仍属内阁时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.韩爌.office_type": "== 内阁"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "韩爌", "动作": "任命", "office": "兵部尚书"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is True
        assert db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?",
            ("韩爌",),
        ).fetchone()["office_type"] == "兵部"
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_event_pool_pending_appointment_normalizes_equivalent_office(game):
    """post-merge CMR R10：全角分隔的等价官职经真实写口规范化后，不应误阻断旧 office 门。"""
    db, state, content = game
    issues.bind_content(content)
    db.conn.execute(
        "UPDATE characters SET status=?, power_id=?, office=?, office_type=? WHERE name=?",
        ("active", "ming", "兵部尚书,左都御史", "兵部", "袁崇焕"),
    )
    if "袁崇焕" in content.characters:
        ch = content.characters["袁崇焕"]
        ch.status = "active"
        ch.power_id = "ming"
        ch.office = "兵部尚书,左都御史"
        ch.office_type = "兵部"
    ev = Event(
        id="__test_normalized_office_pending__",
        title="测试·规范化等价官职门",
        kind="朝议",
        summary="袁崇焕仍兼两职时才可触发。",
        urgency=10,
        severity=10,
        credibility=100,
        interests=[],
        audiences=[],
        event_type="situation",
        trigger_gate={"character.袁崇焕.office": "== 兵部尚书,左都御史"},
    )
    content.seed_events.append(ev)
    content.event_by_id[ev.id] = ev
    try:
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": ev.id}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "任命", "office": "兵部尚书，左都御史"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is False
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?",
            ("袁崇焕",),
        ).fetchone()["office"] == "兵部尚书,左都御史"
    finally:
        content.seed_events.remove(ev)
        content.event_by_id.pop(ev.id, None)


def test_issue_tracker_cancel_respects_outer_transaction_rollback(game):
    """post-merge CMR R4：cancels 段不得由 db.cancel_issue 提前提交外层事务。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="测试·撤办事务",
        origin_kind="decree",
        bar_value=40,
        stage_text="撤办前",
        cancellable="decree",
        effect_on_resolve={"metrics": {"民心": 1}},
    )
    before_advances = db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0]
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"cancels": [{"issue_id": issue_id, "narrative": "撤办"}]},
    )
    assert out["cancels"][0]["rejected"] is False
    db.conn.rollback()

    row = db.conn.execute("SELECT bar_value, stage_text, status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert dict(row) == {"bar_value": 40, "stage_text": "撤办前", "status": "active"}
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchone()[0] == before_advances


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
    out = issues.apply_issue_tracker_output(
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
    )
    assert out["cancels"][0]["rejected"] is False
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

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "评定", "loyalty": 10, "reason": "同回合安抚见效"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("mao_wenlong")
    assert db.get_character_status("毛文龙")[0] == "active"
    assert db.conn.execute("SELECT loyalty FROM characters WHERE name=?", ("毛文龙",)).fetchone()["loyalty"] == 70


def test_mao_wenlong_event_pool_rechecks_after_same_turn_yuan_dismissal(game):
    """post-merge CMR R2：同回合袁崇焕退场应阻断袁斩毛文龙事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}],
            "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "同回合罢离督师"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("mao_wenlong")
    assert db.get_character_status("毛文龙")[0] == "active"
    assert db.get_character_status("袁崇焕")[0] == "dismissed"


def test_invalid_pending_person_change_does_not_block_event_gate(game):
    """post-merge CMR R4：未被人物 applier 接受的同回合处置，不得提前阻断事件 gate。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))

    with _restore_yuan_as_guanning_commander(db, content):
        out = issues.apply_score_extraction(
            db,
            state,
            {
                "new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}],
                "人物变更": [{"origin_ref": "盘面自发", "name": "袁崇焕", "动作": "处置", "status": "candidate", "reason": "非法候选"}],
            },
            content=content,
        )

        assert out["issue_summary"]["new_issues"][0]["rejected"] is False
        assert db.has_event_triggered("mao_wenlong")
        assert db.get_character_status("毛文龙")[0] == "dead"
        assert db.get_character_status("袁崇焕")[0] == "active"
        assert out["applied_person_changes"][0]["rejected"] is True
        assert out["applied_person_changes"][0]["category"] == "invalid_transition"


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

    issues.apply_event_terminal_states(state, db)

    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
        content=content,
    )

    assert out["new_issues"][0]["rejected"] is True
    assert "候选" in out["new_issues"][0]["reason"]
    assert db.get_character_status("毛文龙")[0] == "dead"
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

        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
            content=content,
        )

        assert out["new_issues"][0]["rejected"] is True
        assert "候选" in out["new_issues"][0]["reason"]
        assert db.get_character_status("毛文龙")[0] == "active"
        assert content.characters["毛文龙"].status == "active"
        assert not db.has_event_triggered("mao_wenlong")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
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
        out = issues.apply_issue_tracker_output(
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
        )
    finally:
        content.seed_events.remove(ev1)
        content.seed_events.remove(ev2)
        content.event_by_id.pop(ev1.id, None)
        content.event_by_id.pop(ev2.id, None)

    assert [item["rejected"] for item in out["new_issues"]] == [True, True]
    assert calls == 1


def test_mao_wenlong_event_pool_duplicate_emit_is_idempotent(game):
    """#203 CMR：同一轮重复 emit 已触发事件时，第二条应拒收留痕而不是 abort。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (44, "毛文龙"))

    with _restore_yuan_as_guanning_commander(db, content):
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)).fetchone()[0]

        out = issues.apply_issue_tracker_output(
            db,
            state,
            {"new_issues": [
                {"origin_kind": "event_pool", "id": "mao_wenlong"},
                {"origin_kind": "event_pool", "id": "mao_wenlong"},
            ]},
            content=content,
        )

        assert out["new_issues"][0]["rejected"] is False
        assert out["new_issues"][1]["rejected"] is True
        assert "候选" in out["new_issues"][1]["reason"]
        assert db.get_character_status("毛文龙")[0] == "dead"
        assert content.characters["毛文龙"].status == "dead"
        assert db.has_event_triggered("mao_wenlong")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name=?", ("毛文龙",)
        ).fetchone()[0] == before_logs + 1
