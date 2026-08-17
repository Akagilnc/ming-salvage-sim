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


def clear_orphan_month_open_snapshot(db: "GameDB", state: "GameState") -> bool:
    """服务进程唯一启动缝（WebGame.__init__）：快照在 ∧ 相位仍常态 → 清快照并记一行日志。

    settling / awaiting_decision → 不清，交既有恢复通道。
    幂等；故障注入 oracle 同调此函数（禁旁路造绿灯）。
    """
    turn = int(state.turn)
    snap = db.get_month_open_snapshot(turn)
    if snap is None:
        return False
    phase = str(state.turn_phase or "")
    if phase in FRONT_HALF_DONE_PHASES:
        return False
    db.clear_month_open_snapshot(turn)
    tlog(f"[month_open_snapshot] 启动清除孤儿月初快照 turn={turn} phase={phase}")
    return True
