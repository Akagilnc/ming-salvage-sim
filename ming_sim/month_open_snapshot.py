"""#1234 / ADR 0148 路③：月初快照呈现投影（非结算/恢复权威）。

载体裁定（票庭）：当前回合未过期快照存在 ⇔ 核账展示态。
引擎控制流永不读此投影；仅状态口 / HUD / 户部余额呈现读取。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ming_sim.constants import ECONOMY_ACCOUNTS, SCORE_METRICS
from ming_sim.models import FRONT_HALF_DONE_PHASES
from ming_sim.token_stats import tlog

if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState

# 点击前四键：国库/内库/民心/皇威（GATE_METRIC_KEYS 同源，显式钉死顺序）
MONTH_OPEN_KEYS = tuple(ECONOMY_ACCOUNTS) + tuple(SCORE_METRICS)


def accept_settlement_period(db: "GameDB", state: "GameState") -> None:
    """#1235 / ADR 0149 点即入：点击受理即独立提交月初快照（幂等）。

    FRONT_HALF_DONE（settling / awaiting_decision）不重写——恢复态已有快照或
    半程活值不可作点击前真源。须在 await 在飞 / auto_close / 任何盘面突变之前调用。
    """
    phase = str(state.turn_phase or "")
    if phase in FRONT_HALF_DONE_PHASES:
        return
    db.capture_month_open_snapshot(state)


def _clear_settlement_display_if_orphan(
    db: "GameDB", state: "GameState", *, reason: str,
) -> bool:
    """同谓词 clearer：快照在 ∧ 相位非常态前半段 → 清快照。settling/awaiting 不清。"""
    turn = int(state.turn)
    phase = str(state.turn_phase or "")
    if phase in FRONT_HALF_DONE_PHASES:
        return False
    if db.get_month_open_snapshot(turn) is None:
        return False
    db.clear_month_open_snapshot(turn)
    tlog(f"[month_open_snapshot] {reason} turn={turn} phase={phase}")
    return True


def exit_settlement_display_on_failure(db: "GameDB", state: "GameState") -> bool:
    """#1235 / ADR 0149 真失败另形：前半段未提交时清快照，核账展示态退出。

    settling / awaiting_decision → 不清，交既有恢复通道（AC3 不回归）。
    终态与「未了在办」（展示态仍在）可区分。返回是否清除。
    """
    return _clear_settlement_display_if_orphan(
        db, state, reason="真失败退出核账展示态",
    )


def clear_orphan_month_open_snapshot(db: "GameDB", state: "GameState") -> bool:
    """服务进程唯一启动缝（WebGame.__init__）：快照在 ∧ 相位仍常态 → 清快照并记一行日志。

    settling / awaiting_decision → 不清，交既有恢复通道。
    幂等；故障注入 oracle 同调此函数（禁旁路造绿灯）。
    """
    return _clear_settlement_display_if_orphan(
        db, state, reason="启动清除孤儿月初快照",
    )
