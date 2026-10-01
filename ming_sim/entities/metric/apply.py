"""民心 / 皇威账面核算。声明段与局势效果共用这一处，不另写一套公式。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ming_sim.models import GameState

ISSUE_METRIC_KEYS = {"民心", "皇威"}


def apply_metric_dict(
    state: GameState,
    metric_delta: Dict[str, object],
    caps: Optional[Dict[str, int]] = None,
    db=None,
) -> Dict[str, int]:
    """已知整数指标落账。

    非 dict 整包按空处理（#117：未过形状闸的 issue-effect 不得因 .items() 崩回合）。
    未知键与非整数值在此跳过；声明段用 :func:`declare_metric_pairs` 把它们收成拒收。
    """
    mods = db.legacy_modifiers(state) if db is not None else {}
    applied: Dict[str, int] = {}
    metric_delta = metric_delta if isinstance(metric_delta, dict) else {}
    for key, val in metric_delta.items():
        if key not in ISSUE_METRIC_KEYS:
            continue
        try:
            amount = int(val)
        except (TypeError, ValueError):
            continue
        net_pct = int(mods.get(key, 0) or 0)
        if net_pct and db is not None:
            amount = db.apply_legacy_pct(amount, net_pct)
        if caps and key in caps:
            cap = caps[key]
            if amount > cap:
                amount = cap
            elif amount < -cap:
                amount = -cap
        if amount == 0:
            continue
        state.metrics[key] = int(state.metrics.get(key, 0)) + amount
        applied[key] = applied.get(key, 0) + amount
    return applied


def declare_metric_pairs(
    state: GameState,
    pairs: List[Tuple[object, object]],
    db=None,
) -> Tuple[Dict[str, int], List[Tuple[object, object, str, str]]]:
    """声明有序对：合法指标落账，未知键与非整数值逐项拒收。"""
    totals: Dict[str, int] = {}
    refused: List[Tuple[object, object, str, str]] = []
    for key, val in pairs:
        if key not in ISSUE_METRIC_KEYS:
            refused.append((key, val, f"未知指标：{key!r}", "invalid_enum"))
            continue
        try:
            int(val)
        except (TypeError, ValueError):
            refused.append((key, val, f"「{key}」值非整数：{val!r}", "invalid_enum"))
            continue
        for metric, delta in apply_metric_dict(state, {key: val}, db=db).items():
            totals[metric] = totals.get(metric, 0) + delta
    return totals, refused
