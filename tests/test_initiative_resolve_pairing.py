"""#45/#46（M1 状态可信链路）：国策结案实体后果强制配对守门。

军事国策（练军/募营/调将）结案却无 new_armies/office_changes、或经制国策（月经费/俸/饷）
结案却无月度 economy/fiscal_creates 时，响亮告警——不再静默放过「只推进度条、无实体后果」
的空壳结案（#45 太学府月经费没立账、#46 天雄军没建军籍的真踩坑）。warn-only，不阻断结算。
"""
from ming_sim import issues
from ming_sim.issues import _initiative_resolve_pairing_warnings


def _w(title, tags=None, ongoing=None, effect=None):
    return _initiative_resolve_pairing_warnings(title, tags or [], ongoing or {}, effect or {})


def test_military_initiative_without_army_warns():
    warns = _w("练成天雄军镇蓟镇", tags=["练军"], effect={"metrics": {"民心": 1}})
    assert warns, "军事国策结案无 new_armies 应告警"
    # 练军告警用 "new_armies"（缺主将调任才用 "人物变更"）；assert 精确到本例的关键词（PR#107 coderabbit nit）
    assert any("new_armies" in w for w in warns)


def test_military_initiative_with_new_armies_no_warn():
    warns = _w("练成天雄军", tags=["练军"],
               effect={"new_armies": [{"id": "tianxiong", "name": "天雄军", "manpower": 18000}]})
    assert warns == [], f"已带 new_armies 不应告警：{warns}"


def test_military_initiative_with_office_change_no_warn():
    # 调将类：带 office_changes/人物变更（卢象升调任主将）即认配对
    warns = _w("调卢象升督天雄军", tags=["调将"],
               effect={"人物变更": [{"name": "卢象升", "动作": "调任", "office": "荡寇将军"}]})
    assert warns == [], f"调将带 office_changes 不应告警：{warns}"


def test_fiscal_recurring_initiative_without_economy_warns():
    warns = _w("设太学府岁支月经费五百万", tags=["设局"], effect={"metrics": {"民心": 1}})
    assert warns, "经制国策结案无月度 economy/fiscal_creates 应告警"
    assert any("fiscal_creates" in w or "economy" in w for w in warns)


def test_fiscal_recurring_with_ongoing_economy_no_warn():
    warns = _w("设太学府月经费", tags=[],
               ongoing={"economy": [{"account": "国库", "delta": -500}]},
               effect={"metrics": {"民心": 1}})
    assert warns == [], f"已带 ongoing economy 不应告警：{warns}"


def test_neutral_initiative_no_warn():
    warns = _w("整顿吏治提振民心", tags=["民生"], effect={"metrics": {"民心": 5, "皇威": 2}})
    assert warns == [], f"无军/财语义不应告警：{warns}"


def test_military_effect_with_only_legacy_office_changes_warns():
    # CMR R1（gemini high）：office_changes 是 ADR 0009 后的死键，_apply_issue_entities 只读
    # 人物变更/character_status_changes，不读 office_changes → 不应被它消音军事配对告警。
    warns = _w("调卢象升督天雄军", tags=["调将"],
               effect={"office_changes": [{"name": "卢象升", "new_office": "荡寇将军"}]})
    assert warns, "effect 只挂死键 office_changes（引擎不落）不应消音军事配对告警"


def test_fiscal_invalid_economy_shell_warns():
    # CMR R1（codex medium）：flows 跳过缺 account/零额/非数 delta 的 economy 项，不立账；
    # 这类空壳不应消音经制配对告警。
    assert _w("设太学府月经费", effect={"economy": [{}]}), "空 economy 壳不应消音"
    assert _w("设太学府月经费", effect={"economy": [{"account": "国库", "delta": 0}]}), \
        "零额 economy 不应消音"
    assert _w("设太学府月经费", ongoing={"economy": [{"delta": -5}]}, effect={"metrics": {"民心": 1}}), \
        "缺 account 的 ongoing economy 不应消音"
    # 正例：有效月支不告警
    assert _w("设太学府月经费", ongoing={"economy": [{"account": "国库", "delta": -500}]},
              effect={"metrics": {"民心": 1}}) == [], "有效月支不应告警"


def test_raise_with_only_person_change_still_warns():
    # CMR R2（codex high）：练军/募营须落 new_armies；只挂人物变更（无军）应仍告警缺军籍。
    warns = _w("练成天雄军", tags=["练军"],
               effect={"人物变更": [{"name": "卢象升", "动作": "调任", "office": "荡寇将军"}]})
    assert any("new_armies" in w for w in warns), "练军只挂人物变更（无 new_armies）应告警缺军籍"


def test_move_with_only_army_still_warns():
    # CMR R2（codex high）：调将须落人物变更；只挂 new_armies（无调任）应仍告警缺主将调任。
    warns = _w("调卢象升镇蓟镇", tags=["调将"],
               effect={"new_armies": [{"id": "x", "name": "x", "manpower": 1}]})
    assert any("人物变更" in w for w in warns), "调将只挂 new_armies（无人物变更）应告警缺主将调任"


def test_fiscal_account_not_applied_by_flows_warns():
    # CMR R2（codex+claude）：flows 只对 国库/内库 立账，其它账户跳过 → 不应消音告警。
    assert _w("设太学府月经费", effect={"economy": [{"account": "户部", "delta": -500}]}), \
        "非 国库/内库 账户（flows 不立账）不应消音告警"


def test_fiscal_numeric_string_delta_no_warn():
    # CMR R2（claude）：flows 用 int() 强转 delta，数字串 "-500" 会立账 → 不应告警。
    assert _w("设太学府月经费", ongoing={"economy": [{"account": "国库", "delta": "-500"}]},
              effect={"metrics": {"民心": 1}}) == [], "数字串 delta（flows 会立账）不应告警"


def test_nonlist_economy_no_crash_warns():
    # PR#107 R1（gemini high）：非 list 的 economy（int/str/bool）不应 TypeError 崩结算，
    # 按「无有效月支」告警即可（warn-only 不许把畸形数据变成崩溃）。
    assert _w("设太学府月经费", effect={"economy": 5})
    assert _w("设太学府月经费", effect={"economy": "三十万"})
    assert _w("设太学府月经费", ongoing={"economy": True}, effect={"metrics": {"民心": 1}})


def test_malformed_pairing_shape_warns():
    # PR#107 R1（codex P2）：非 list/dict 的配对字段（字符串、错容器）不算真配对——
    # _apply_issue_entities 只落 list 的 new_armies/人物变更、dict 的 army_delta，畸形不该消音。
    assert _w("练成天雄军", tags=["练军"], effect={"new_armies": "天雄军已成"})  # 字符串非 list
    assert _w("练成天雄军", tags=["练军"], effect={"army_delta": [1, 2]})  # list 非 dict
    assert _w("调卢象升督师", tags=["调将"], effect={"人物变更": "已调任"})  # 字符串非 list


def test_resolve_surfaces_pairing_warning_in_result(game):
    """接线：军事国策经 close→resolved 结案、effect 缺 new_armies 时，
    apply_issue_tracker_output 的结果 pairing_warnings 应带告警。"""
    db, state, content = game
    issue_id = db.insert_issue(
        state, kind="initiative", title="练成天雄军镇蓟镇",
        origin_kind="decree", bar_value=50, tags=["练军"],
        effect_on_resolve={"metrics": {"民心": 1}},  # 缺 new_armies/office_changes
    )
    db.conn.commit()
    out = issues.apply_issue_tracker_output(
        db, state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "练成"}]},
        content=content,
    )
    warns = out.get("pairing_warnings") or []
    assert any("new_armies" in w for w in warns), f"军事国策结案应 surface 配对告警：{warns}"


def test_resolve_with_new_armies_no_warning_in_result(game):
    """接线负例：effect 带 new_armies 时不应告警。"""
    db, state, content = game
    issue_id = db.insert_issue(
        state, kind="initiative", title="练成天雄军",
        origin_kind="decree", bar_value=50, tags=["练军"],
        effect_on_resolve={"new_armies": [{"id": "tianxiong", "name": "天雄军", "manpower": 18000}]},
    )
    db.conn.commit()
    out = issues.apply_issue_tracker_output(
        db, state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "练成"}]},
        content=content,
    )
    assert (out.get("pairing_warnings") or []) == [], f"带 new_armies 不应告警：{out.get('pairing_warnings')}"
