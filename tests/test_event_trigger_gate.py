"""#12（M1 P0）：历史锚定事件结构化前提门。

`trigger_gate` + `_gate_passed`（能查 character/faction/army/region/metric 真实字段）此前只接
seed 情势，历史 `events` 分支只过纯日历窗口 `_event_window_open` → 前提已不成立的历史事件按
年月误触发（毛文龙已安抚/效顺仍被弹出的机制半）。把门接进历史分支：带 gate 的历史事件须达标
才进候选；无 gate（空 dict）= 纯日历锚定，行为不变。
"""
import json
from pathlib import Path

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


def test_character_numeric_gate_supports_comparison(game):
    """character.<name>.<field> 数值字段可参与 trigger_gate 比较（#201）。"""
    from ming_sim.issues import _gate_passed
    db, state, content = game

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


def test_character_gate_rejects_malformed_field_before_sql(game):
    """trigger_gate 字段名必须先过白名单，不能把畸形字段拼进 SQL。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, _content = game

    with pytest.raises(ValueError, match="字段无效"):
        _gate_passed({"character.毛文龙.loyalty;DROP": ">=1"}, state.metrics, db)


def test_character_numeric_field_text_gate_raises_clear(game):
    """character 数值字段走文本比较时必须 fail-loud，不能 str(loyalty) 后静默 False。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, _content = game

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


def test_character_typo_field_gate_raises_clear(game):
    """character gate 字段名 typo（DB 无此列）沿用清晰 ValueError（#201）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = game

    with pytest.raises(ValueError, match="字段无效|DB 无此列"):
        _gate_passed({"character.毛文龙.loyality": ">=1"}, state.metrics, db)


def test_character_text_typo_field_gate_raises_clear(game):
    """character 文本 gate 字段名 typo 也必须 fail-loud（#201 cmr P2）。"""
    import pytest
    from ming_sim.issues import _gate_passed
    db, state, content = game

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
    events = json.loads(events_path.read_text())
    mao = next(item for item in events if item["id"] == "mao_wenlong")

    effect = mao["effect_on_trigger"]
    assert "人物变更" in effect
    assert "character_status_changes" not in effect
    assert effect["人物变更"] == [
        {"name": "毛文龙", "动作": "处置", "status": "dead", "reason": "袁崇焕双岛斩帅"}
    ]


def test_mao_wenlong_event_excluded_after_appeasement(game):
    """#203/#12：毛文龙 loyalty 已过阈值时，袁斩毛文龙不应再按日历进候选。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (70, "毛文龙"))

    cands = issues.gather_candidate_events(state, db)

    assert all(ev.id != "mao_wenlong" for ev in cands)


def test_mao_wenlong_event_trigger_lands_character_status(game):
    """#203：未安抚时袁斩毛文龙触发后，毛文龙退场事实必须落库。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (44, "毛文龙"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))

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


def test_mao_wenlong_event_trigger_respects_outer_transaction_rollback(game):
    """post-merge CMR：event trigger 写入不得提前提交外层普通事务。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ?, status = ? WHERE name = ?", (44, "active", "毛文龙"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))
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
    assert not db.has_event_triggered("mao_wenlong")
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
            "人物变更": [{"name": "毛文龙", "动作": "评定", "loyalty": 10, "reason": "同回合安抚见效"}],
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
            "人物变更": [{"name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "同回合罢离督师"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("mao_wenlong")
    assert db.get_character_status("毛文龙")[0] == "active"
    assert db.get_character_status("袁崇焕")[0] == "dismissed"


def test_mao_wenlong_event_excluded_when_character_already_inactive(game):
    """#203 CMR：毛文龙已退场时，斩毛事件不应再按低 loyalty 进入候选。"""
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

    out = issues.apply_issue_tracker_output(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "mao_wenlong"}]},
        content=content,
    )

    assert out["new_issues"][0]["rejected"] is True
    assert "候选" in out["new_issues"][0]["reason"]
    assert db.get_character_status("毛文龙")[0] == "dead"
    assert not db.has_event_triggered("mao_wenlong")


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


def test_mao_wenlong_event_pool_duplicate_emit_is_idempotent(game):
    """#203 CMR：同一轮重复 emit 已触发事件时，第二条应拒收留痕而不是 abort。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1629
    state.period = 6
    db.conn.execute("UPDATE characters SET loyalty = ? WHERE name = ?", (44, "毛文龙"))
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))
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
