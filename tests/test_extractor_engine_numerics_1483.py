"""#1483 — engine 侧 extractor/simulator 输入保留阈值比对所需精确数值。

P4 只管玩家可见面；modular extractor 与 season_simulator 规则输入是 engine 管线。
走真实装配：build_simulator_payload + build_extractor_shared_context(module=issues)。
"""

from __future__ import annotations

from ming_sim.qualitative import power_band
from ming_sim.simulation import (
    build_extractor_shared_context,
    build_simulator_payload,
)

_SENT_MINXIN = 55
_SENT_HUANGWEI = 25
_SENT_BAR = 72
_SENT_REGION_PS = 48
_SENT_LEV_LOW = 25   # leverage<=30 规则内侧
_SENT_LEV_MID = 35   # 同属「偏弱」band（20–39），但 >30


def _plant(db, state) -> tuple[str, str]:
    """写入可区分的阈值哨兵；返回两个派系名（leverage 25 / 35）。"""
    state.metrics["民心"] = _SENT_MINXIN
    state.metrics["皇威"] = _SENT_HUANGWEI
    db.conn.execute("UPDATE regions SET public_support=?", (_SENT_REGION_PS,))
    names = [
        str(r["name"])
        for r in db.conn.execute("SELECT name FROM factions ORDER BY name").fetchall()
    ]
    assert len(names) >= 2, "需要至少两个派系以钉 leverage 可区分性"
    low_name, mid_name = names[0], names[1]
    db.conn.execute(
        "UPDATE factions SET leverage=? WHERE name=?", (_SENT_LEV_LOW, low_name),
    )
    db.conn.execute(
        "UPDATE factions SET leverage=? WHERE name=?", (_SENT_LEV_MID, mid_name),
    )
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="1483阈值钉测局势",
        origin_kind="decree",
        origin_ref="test-1483-engine-numerics",
        bar_value=_SENT_BAR,
        inertia=0,
        stage_text="钉测",
        resolve_condition="民心>60",
        fail_condition="unrest>80",
    )
    db.conn.commit()
    # 前提：25 与 35 在玩家面 band 表上不可区分——否则 P2 无刀口。
    assert power_band(_SENT_LEV_LOW) == power_band(_SENT_LEV_MID)
    return low_name, mid_name


def test_issues_extractor_context_keeps_threshold_numerics(game):
    """P1：modular issues extractor_context 保留 current_state/regions/active_issues 裸数。"""
    db, state, _content = game
    _plant(db, state)

    ctx = build_extractor_shared_context(
        db, state, "邸报正文", "测试诏", module="issues", decree_dossiers=[],
    )

    # current_state：民心/皇威必须是精确整数，供「民心>60」类对照
    cs = ctx["current_state"]
    assert cs["民心"] == _SENT_MINXIN
    assert cs["皇威"] == _SENT_HUANGWEI
    assert isinstance(cs["民心"], int)
    assert isinstance(cs["皇威"], int)

    # regions：public_support 裸数（非 band 字）
    cols = ctx["regions"]["cols"]
    rows = ctx["regions"]["rows"]
    assert rows
    ps_idx = cols.index("public_support")
    assert rows[0][ps_idx] == _SENT_REGION_PS
    assert isinstance(rows[0][ps_idx], (int, float))

    # active_issues：bar_value 裸数 + resolve_condition 仍在
    pinned = next(
        i for i in ctx["active_issues"] if i.get("title") == "1483阈值钉测局势"
    )
    assert pinned["bar_value"] == _SENT_BAR
    assert isinstance(pinned["bar_value"], int)
    assert "民心>60" in str(pinned.get("resolve_condition") or "")


def test_simulator_factions_brief_keeps_exact_leverage_for_lte30_rule(game):
    """P2：simulator factions_brief 保留精确 leverage，25 与 35 可区分（≤30 规则输入）。"""
    db, state, _content = game
    low_name, mid_name = _plant(db, state)

    payload = build_simulator_payload(state, db, "测试诏", "")
    brief = str(payload["factions_brief"])

    assert f"势力{_SENT_LEV_LOW}" in brief, (
        f"leverage={_SENT_LEV_LOW} 必须原样可见，否则 season_simulator "
        f"leverage<=30 规则无法命中；got: {brief!r}"
    )
    assert f"势力{_SENT_LEV_MID}" in brief, (
        f"leverage={_SENT_LEV_MID} 必须原样可见，与 {_SENT_LEV_LOW} 区分；got: {brief!r}"
    )
    # 同一 band 字不足以区分——精确值必须同时在场
    assert power_band(_SENT_LEV_LOW) == power_band(_SENT_LEV_MID)
    assert low_name in brief and mid_name in brief
