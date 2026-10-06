"""回合展示与变更报告纯函数（返回 str / 打印）。L7。"""

from __future__ import annotations

from typing import Dict, List, Optional

from ming_sim.assets import format_money, wrap
from ming_sim.constants import ECONOMY_ACCOUNTS, SCORE_METRICS
from ming_sim.db import GameDB
from ming_sim.models import Event, GameState, period_label


def metric_bar(value: int) -> str:
    filled = value // 10
    return "█" * filled + "░" * (10 - filled)


def print_header(state: GameState, db: Optional[GameDB] = None) -> None:
    print("\n" + "=" * 88)
    print(f"崇祯重生 MVP | {period_label(state.year, state.period)} | 第 {state.turn} 回合")
    print("=" * 88)
    for key in ECONOMY_ACCOUNTS:
        print(f"{key:>4}: {format_money(state.metrics[key])}")
    for key in SCORE_METRICS:
        value = state.metrics[key]
        print(f"{key:>4}: {value:>3}/100 {metric_bar(value)}")
    if db is not None:
        print()
        print(wrap(db.region_report(limit=3)))
        # #321 P7：不在 CLI header 直显 army_report（含 mutiny_tier/morale_text/arrears_text）；
        # 军情只经既有 LLM 装配面（army_report/detail/roster → knowledge/tools/intelligence）。
    print()


def metric_delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    keys = list(before.keys())
    for key in after:
        if key not in before:
            keys.append(key)
    return {key: after.get(key, 0) - before.get(key, 0) for key in keys if after.get(key, 0) != before.get(key, 0)}
