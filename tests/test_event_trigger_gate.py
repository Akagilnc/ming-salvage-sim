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
            "region_delta": {"beizhili": {"military_pressure": 35, "controlled_by": "ming"}},
            "army_delta": {"jingying": {"manpower": -5000, "morale": -8}},
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
            "region_delta": {"liaodong": {"military_pressure": 18}},
            "army_delta": {"guanning": {"manpower": -12000, "morale": -12}},
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


def test_non_battle_foreign_node_can_trigger_without_battle_ledger_delta(game):
    """#189 CMR R2：外族 node 不等于战略战事；称帝类事件不应被战果主账门误挡。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1636
    state.period = 4

    assert any(ev.id == "huangtaiji_chengdi" for ev in issues.gather_candidate_events(state, db))

    out = issues.apply_score_extraction(
        db,
        state,
        {"new_issues": [{"origin_kind": "event_pool", "id": "huangtaiji_chengdi"}]},
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("huangtaiji_chengdi")


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
            "region_delta": {"shaanxi": {"unrest": 1}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
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
            "region_delta": {"beizhili": {"military_pressure": 20}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert out["region_changes"] == []


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
            "region_delta": {"shaanxi": {"unrest": 1}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT unrest FROM regions WHERE id = ?", ("shaanxi",)
    ).fetchone()["unrest"] == 79


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
            "region_delta": {"beizhili": {"military_pressure": 10}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "候选" in out["issue_summary"]["new_issues"][0]["reason"]
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20


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
            "region_delta": {"beizhili": {"不存在字段": 1}},
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert "主账" in out["issue_summary"]["new_issues"][0]["reason"]
    assert not db.has_event_triggered("jisi_lubian")
    assert out["region_changes"][0]["rejected"] is True


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
            "人物变更": [{"name": "卢象升", "动作": "处置", "status": "dead", "reason": "戊寅虏变软判战死"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("wuyin_lubian")
    assert db.get_character_status("卢象升")[0] == "dead"


def test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome():
    """#189：戊寅虏变不能把卢象升写成人物核心；卢死/生是战事软判结果。"""
    events_path = Path(__file__).resolve().parents[1] / "content" / "events.json"
    events = json.loads(events_path.read_text())
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
    db.conn.execute("UPDATE characters SET status = ? WHERE name = ?", ("active", "袁崇焕"))
    content.characters["毛文龙"].status = "active"
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
                {"name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "测试撤任"}
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
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
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
                    "id": army_id,
                    "name": "测试事务营",
                    "manpower": 1200,
                    "owner_power": "ming",
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
                {"name": "毛文龙", "动作": "处置", "status": "dismissed", "reason": "测试 helper no-commit"}
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
        {"economy_moves": [{"account": "国库", "delta": -1, "category": "测试", "reason": reason}]},
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
        {"fiscal_changes": [{"key": key, "delta": 1, "reason": "测试顶层财政事务R7"}]},
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
            "region_delta": {region["id"]: {"unrest": 1, "reason": "测试顶层地区事务R7"}},
            "army_delta": {army["id"]: {"manpower": 1, "reason": "测试顶层军队事务R7"}},
            "power_updates": {power["id"]: {"leverage": 1, "reason": "测试顶层势力事务R7"}},
            "faction_delta": {faction["name"]: {"satisfaction": -1}},
            "new_armies": [
                {
                    "id": new_army_id,
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
            "fiscal_removes": [{"key": remove_key, "reason": "测试顶层财政裁撤事务R7"}],
            "fiscal_creates": [
                {
                    "key": created_key,
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
                "人物变更": [{"name": "毛文龙", "动作": "行止", "location": "beizhili"}],
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
                "人物变更": [{"name": "袁崇焕", "动作": "任命", "office": "兵部尚书"}],
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
                "人物变更": [{"name": "袁崇焕", "动作": "易主", "new_power": "houjin"}],
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
                "人物变更": [{"name": "袁崇焕", "动作": "处置", "status": "dismissed", "reason": "测试罢离督师"}],
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
                "人物变更": [{"name": "毛文龙", "动作": "行止", "location": "liaodong"}],
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
                    {"name": "袁崇焕", "new_power": "houjin", "reason": "测试旧易主"}
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
                        "name": "袁崇焕",
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
                        "name": "袁崇焕",
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
                {"name": "袁崇焕", "动作": "处置", "status": "dead", "reason": "测试先处死"},
                {"name": "袁崇焕", "动作": "任命", "office": "兵部尚书", "reason": "测试后任命"},
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
                {"人物变更": [{"name": "韩爌", "动作": "任命", "office": "兵部尚书"}]},
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
                "人物变更": [{"name": "韩阁老", "动作": "任命", "office": "兵部尚书"}],
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
                    {"name": "韩阁老", "动作": "处置", "status": "dismissed", "reason": "测试别名处置"}
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
                "人物变更": [{"name": "朱常洵", "动作": "任命", "office": "兵部尚书"}],
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
                "人物变更": [{"name": "袁崇焕", "动作": "任命", "office": "兵部尚书"}],
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
                "人物变更": [{"name": "钱谦益", "动作": "任命", "office": "兵部尚书"}],
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
                "人物变更": [{"name": "韩爌", "动作": "任命", "office": "兵部尚书"}],
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
                "人物变更": [{"name": "袁崇焕", "动作": "任命", "office": "兵部尚书，左都御史"}],
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


def test_invalid_pending_person_change_does_not_block_event_gate(game):
    """post-merge CMR R4：未被人物 applier 接受的同回合处置，不得提前阻断事件 gate。"""
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
            "人物变更": [{"name": "袁崇焕", "动作": "处置", "status": "candidate", "reason": "非法候选"}],
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is False
    assert db.has_event_triggered("mao_wenlong")
    assert db.get_character_status("毛文龙")[0] == "dead"
    assert db.get_character_status("袁崇焕")[0] == "active"
    assert out["applied_person_changes"][0]["rejected"] is True
    assert out["applied_person_changes"][0]["category"] == "invalid_transition"


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
