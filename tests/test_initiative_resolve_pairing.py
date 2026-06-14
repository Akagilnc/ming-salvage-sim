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
    assert any("new_armies" in w or "office_changes" in w for w in warns)


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
