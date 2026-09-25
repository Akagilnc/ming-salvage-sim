"""#1483 — engine 阈值输入与 P4 叙事输入分界。

① simulator factions_brief：定性投影 + leverage<=30 语义记号（代码预计算），禁裸数。
走真实装配：build_simulator_payload。
"""

from __future__ import annotations

from ming_sim.qualitative import power_band, satisfaction_band
from ming_sim.simulation import (
    _LEVERAGE_BELOW_SUPPRESSION_MARK,
    _LEVERAGE_SUPPRESSION_LINE,
    build_simulator_payload,
)

_SENT_MINXIN = 55
_SENT_HUANGWEI = 25
_SENT_BAR = 72
_SENT_REGION_PS = 48
_SENT_SAT = 32
_SENT_LEV_LOW = 25   # leverage<=30 规则内侧
_SENT_LEV_MID = 35   # 同属「偏弱」band（20–39），但 >30

_THRESHOLD_FIELDS = ("current_state", "regions", "active_issues")
_NON_ISSUES_MODULES = ("internal", "military_external", "personnel_secret", "relations")


def _plant(db, state) -> tuple[str, str]:
    """写入可区分的阈值哨兵；返回两个派系名（leverage 25 / 35）。"""
    state.metrics["民心"] = _SENT_MINXIN
    state.metrics["皇威"] = _SENT_HUANGWEI
    db.conn.execute("UPDATE regions SET public_support=?", (_SENT_REGION_PS,))
    db.conn.execute("UPDATE factions SET satisfaction=?", (_SENT_SAT,))
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
    # 前提：25 与 35 在玩家面 band 表上不可区分——否则语义记号无刀口。
    assert power_band(_SENT_LEV_LOW) == power_band(_SENT_LEV_MID)
    assert _SENT_LEV_LOW <= _LEVERAGE_SUPPRESSION_LINE < _SENT_LEV_MID
    return low_name, mid_name


def test_simulator_factions_brief_qualitative_with_suppression_mark(game):
    """P1 双向：factions_brief 无裸数 + leverage<=30 含语义记号（代码预计算）。"""
    db, state, _content = game
    low_name, mid_name = _plant(db, state)

    payload = build_simulator_payload(state, db, "测试诏", "")
    brief = str(payload["factions_brief"])

    # —— 无裸数（P4 叙事输入）——
    assert f"势力{_SENT_LEV_LOW}" not in brief
    assert f"势力{_SENT_LEV_MID}" not in brief
    assert f"满意{_SENT_SAT}" not in brief
    # 定性档仍在
    assert f"势力{power_band(_SENT_LEV_LOW)}" in brief
    assert f"满意{satisfaction_band(_SENT_SAT)}" in brief

    # —— 含语义记号；仅 <=30 侧带标（同 band 的 35 不带）——
    assert _LEVERAGE_BELOW_SUPPRESSION_MARK in brief
    assert low_name in brief and mid_name in brief
    # 按分号切段，钉 low 段有标、mid 段无标
    segments = [s for s in brief.split("；") if s]
    low_seg = next(s for s in segments if s.startswith(low_name))
    mid_seg = next(s for s in segments if s.startswith(mid_name))
    assert _LEVERAGE_BELOW_SUPPRESSION_MARK in low_seg, low_seg
    assert _LEVERAGE_BELOW_SUPPRESSION_MARK not in mid_seg, mid_seg
