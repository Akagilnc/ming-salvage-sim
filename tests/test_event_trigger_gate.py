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
        row = db.conn.execute(
            "SELECT terminal_status FROM event_triggers WHERE event_id=?",
            ("__test_expiring_hist__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_status"] == "expired"

        state.metrics["民心"] = 3
        later_cands = issues.gather_candidate_events(state, db)
        assert all(c.id != "__test_expiring_hist__" for c in later_cands)
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
            "SELECT terminal_status FROM event_triggers WHERE event_id=?",
            ("__test_latest_month_hist__",),
        ).fetchone()
        assert row is None
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
            "SELECT terminal_status FROM event_triggers WHERE event_id=?",
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
        row = db.conn.execute(
            "SELECT terminal_status FROM event_triggers WHERE event_id=?",
            ("__test_expiring_seed__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_status"] == "expired"
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
            "SELECT terminal_status FROM event_triggers WHERE event_id=?",
            ("__test_expiring_auto_seed__",),
        ).fetchone()
        assert row is not None
        assert row["terminal_status"] == "expired"
    finally:
        content.seed_events.remove(ev)


def test_gate_passed_tolerates_none(game):
    # PR#107 R1（gemini medium）：trigger_gate=None（content JSON 显式 null）传进 _gate_passed
    # 不应 None.items() AttributeError 崩候选收集；None 视同空门、恒过。
    db, state, content = game
    from ming_sim.issues import _gate_passed
    assert _gate_passed(None, state.metrics, db) is True


def test_gate_passed_tolerates_nonstring_cond(game):
    # PR#107 R2（gemini high）：条件值写成非字符串（{"民心":60} 而非 ">=60"）不应 cond.strip()
    # AttributeError 崩候选收集；str() 强转后不匹配操作符正则 → 门不达标（安全降级、不崩）。
    db, state, content = game
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
              "region.x.controlled_by"):
        assert gate_key_form_error(k) == "", (k, gate_key_form_error(k))


def test_gate_key_form_error_rejects_typo_metric_table_structure():
    """typo'd metric / 未知表 / 结构不完整 → 非空错误说明（fail-loud 素材）。"""
    from ming_sim.content import gate_key_form_error
    assert "未知 metric" in gate_key_form_error("民生")        # 民心 typo
    assert "未知表" in gate_key_form_error("regon.x.unrest")   # region typo
    assert gate_key_form_error("region.x")                      # 2 段，结构不完整


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


def test_typo_field_gate_raises_clear_not_operationalerror(game):
    """gate 引用 typo'd 字段（DB 无此列）→ 求值期 SELECT 抛 OperationalError，被 fail-loud
    成清晰 ValueError（含 key + 'DB 无此列'），不留 cryptic 崩（#12 Q3）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = game
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


def test_typo_field_text_gate_raises_clear(game):
    """cmr r1（Claude）：文本相等 gate 引用 typo'd 字段 → text-branch（_eval_gate_key_str）的
    OperationalError 也被 fail-loud 成清晰 ValueError（覆盖文本分支 wrap）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = game
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


def test_numeric_cond_on_text_field_raises_clear(game):
    """#159：数值比较 cond 配文本字段（如 region.x.controlled_by >=1）→ runtime int(str) ValueError
    被 fail-loud 成清晰 ValueError（数值不可比文本字段），不静默回 None 当条件不满足（Q3）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = game
    # controlled_by 是文本字段（'ming'/'houjin'），对它做数值比较 → fail-loud
    with pytest.raises(ValueError, match="字段非数值|不可比文本"):
        _gate_passed({"region.huguang.controlled_by": ">=1"}, state.metrics, db)
