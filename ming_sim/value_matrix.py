"""ADR 0011-3 价值画像矩阵读口。

单一真源：content/value_matrix.json（D3-8 build-upon：矩阵值落库为 content 静态配置）。
本模块只校验闭集并提供读函数，不另立 42 格常量。
"""

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
