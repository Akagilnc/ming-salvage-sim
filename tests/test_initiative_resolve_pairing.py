"""#45/#46（M1 状态可信链路）：国策结案实体后果强制配对守门。

军事国策（练军/募营/调将）结案却无 new_armies/office_changes、或经制国策（月经费/俸/饷）
结案却无月度 economy/fiscal_creates 时，响亮告警——不再静默放过「只推进度条、无实体后果」
的空壳结案（#45 太学府月经费没立账、#46 天雄军没建军籍的真踩坑）。warn-only，不阻断结算。
"""
from ming_sim import issues


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
        # manpower 必填（fresh seed 无 tianxiong → 走建新军严格校验路；#5 deterministic）；
        # maintenance_per_turn #173 PR2 后退役、不再必填，保留此值仅证「在场仍兼容接收」。
        effect_on_resolve={"new_armies": [{
            "id": "tianxiong", "name": "天雄军", "manpower": 18000, "maintenance_per_turn": 50,
            "pay_source_region": "shaanxi", "province_pay_share": 1.0, "central_pay_share": 0.0,
        }]},
    )
    db.conn.commit()
    out = issues.apply_issue_tracker_output(
        db, state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "练成"}]},
        content=content,
    )
    assert (out.get("pairing_warnings") or []) == [], f"带 new_armies 不应告警：{out.get('pairing_warnings')}"


