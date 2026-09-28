"""#1483 — engine 阈值输入与 P4 叙事输入分界。

① simulator factions_brief：定性投影 + leverage<=30 语义记号（代码预计算），禁裸数。
"""

from __future__ import annotations

from ming_sim.qualitative import power_band, satisfaction_band
from ming_sim.simulation import (
    _LEVERAGE_BELOW_SUPPRESSION_MARK,
    _LEVERAGE_SUPPRESSION_LINE,
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


