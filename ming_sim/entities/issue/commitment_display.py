"""承诺呈现：进度、时限条与展示句。求值器仍留在 issues。"""

from __future__ import annotations

import sqlite3
from typing import Dict, Optional

from ming_sim.db import GameDB
from ming_sim.models import GameState


def commitment_progress_payload(
    db: GameDB,
    state: GameState,
    row: sqlite3.Row,
    *,
    paid_this_month: int = 0,
    include_current_month: bool = False,
) -> Optional[Dict[str, object]]:
    from ming_sim.issues import (
        _commitment_gate_references_arrears,
        _commitment_remaining_from_gate,
        _commitment_stop_gate,
        _latest_commitment_paid_total,
    )
    keys = row.keys() if hasattr(row, "keys") else []
    if not str(row["commitment_kind"] if "commitment_kind" in keys else "").strip():
        return None
    gate = _commitment_stop_gate(row)
    remaining = _commitment_remaining_from_gate(gate, state, db) if gate else None
    paid_total = _latest_commitment_paid_total(db, int(row["id"])) + max(0, int(paid_this_month))
    # Fall back to state.turn (→ 0 elapsed) when origin_turn is unset — whether the
    # key is absent OR present-but-NULL/0. `int(row["origin_turn"] or 0)` would collapse
    # a NULL/0 to 0 and leak the absolute turn number into months_elapsed (#380 cmr:
    # gemini + coderabbit). Only a positive origin_turn is a real anchor.
    origin_turn_raw = row["origin_turn"] if "origin_turn" in keys else None
    try:
        origin_turn = int(origin_turn_raw)
    except (TypeError, ValueError):
        origin_turn = 0
    if origin_turn <= 0:
        origin_turn = int(state.turn)
    months_elapsed = max(0, int(state.turn) - origin_turn)
    if include_current_month:
        months_elapsed = int(months_elapsed) + 1
    payload: Dict[str, object] = {
        "months_elapsed": int(months_elapsed),
        "paid_total": int(paid_total),
    }
    if remaining is not None:
        if _commitment_gate_references_arrears(row):
            payload["remaining_arrears"] = float(remaining)
        else:
            payload["remaining_to_goal"] = int(remaining)
    return payload


def _commitment_arrears_remaining_text(amount: object) -> str:
    from ming_sim.db import _approx_wanliang
    text = _approx_wanliang(amount)
    if text.startswith("欠饷"):
        return "尚欠" + text[len("欠饷"):]
    return text


def commitment_display_text(progress: Dict[str, object], row: sqlite3.Row) -> str:
    from ming_sim.issues import (
        _commitment_gate_references_arrears,
        _commitment_stop_gate,
        _monthly_ongoing_effects_has_work,
    )
    from ming_sim.models import loads_effect_dict
    keys = row.keys() if hasattr(row, "keys") else []
    ongoing = loads_effect_dict(row["ongoing_effects"] if "ongoing_effects" in keys else {})
    end_turn = int(row["end_turn"] or 0) if "end_turn" in keys else 0
    origin_turn = int(row["origin_turn"] or 0) if "origin_turn" in keys else 0
    stop_gate = _commitment_stop_gate(row)
    months = int(progress.get("months_elapsed") or 0)
    duration = max(0, end_turn - origin_turn) if end_turn > 0 else 0

    if not _monthly_ongoing_effects_has_work(ongoing) and end_turn > 0:
        return f"限{duration}月·到期待裁"

    if stop_gate and _commitment_gate_references_arrears(row):
        parts = [f"已第{months}月"]
        if "remaining_arrears" in progress:
            parts.append(_commitment_arrears_remaining_text(progress["remaining_arrears"]))
        parts.append("直到补齐")
        return "·".join(parts)

    if stop_gate:
        parts = [f"已履行{months}月"]
        if "remaining_to_goal" in progress:
            parts.append("距达标仍有差距")
        parts.append("直到达标")
        return "·".join(parts)

    if end_turn > 0:
        remaining = max(0, duration - months)
        return f"限{duration}月·已履行{months}月·还剩{remaining}月"

    return f"已履行{months}月·开放承诺"


def commitment_timed_bar_value(progress: Dict[str, object], row: sqlite3.Row) -> Optional[int]:
    """Time-based bar for auto-expiring timed commitments (ongoing effects + end_turn + no gate).

    Returns None for bar-driven (stop_gate), arrears, or passive (no ongoing effects) commitments.
    When non-None, bar = wall-clock months_elapsed / (end_turn - origin_turn) * 100, clamped 0-100.
    """
    from ming_sim.issues import (
        _commitment_stop_gate,
        _monthly_ongoing_effects_has_work,
    )
    from ming_sim.models import loads_effect_dict
    keys = row.keys() if hasattr(row, "keys") else []
    end_turn = int(row["end_turn"] or 0) if "end_turn" in keys else 0
    if end_turn <= 0:
        return None
    if _commitment_stop_gate(row):
        return None
    ongoing = loads_effect_dict(row["ongoing_effects"] if "ongoing_effects" in keys else {})
    if not _monthly_ongoing_effects_has_work(ongoing):
        return None
    origin_turn = int(row["origin_turn"] or 0) if "origin_turn" in keys else 0
    duration = end_turn - origin_turn
    if duration <= 0:
        return None
    months = int(progress.get("months_elapsed") or 0)
    return max(0, min(100, int(round(months * 100 / duration))))


def _commitment_bar_value(progress: Dict[str, object]) -> Optional[int]:
    if "remaining_arrears" not in progress:
        return None
    paid = max(0, int(progress.get("paid_total") or 0))
    try:
        remaining = max(0.0, float(progress.get("remaining_arrears") or 0))
    except (TypeError, ValueError):
        remaining = 0.0
    total = paid + remaining
    if total <= 0:
        return 100
    return max(0, min(100, int(round(paid * 100 / total))))

