"""ADR 0011-3 价值轴名归一（矩阵 JSON 读口已无生产消费者，随 F22-R 退役）。"""

from __future__ import annotations

from ming_sim.centrifuge_ledger import CENTRIFUGE_AXES


def normalize_axis(raw: object) -> str | None:
    text = str(raw or "").strip()
    if text in CENTRIFUGE_AXES:
        return text
    return None


def normalize_axes(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[object] = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        axis = normalize_axis(item)
        if axis is None or axis in seen:
            continue
        seen.add(axis)
        out.append(axis)
    return out


def normalize_direction(raw: object, *, default: int = 1) -> int:
    """动作方向：+1 顺轴护向，−1 逆轴护向。非法回 default。"""
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return int(default)
    if value >= 0:
        return 1
    return -1
