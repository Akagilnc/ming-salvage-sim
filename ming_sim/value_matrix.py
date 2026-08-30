"""ADR 0011-3 价值画像矩阵读口。

单一真源：content/value_matrix.json（D3-8 build-upon：矩阵值落库为 content 静态配置）。
本模块只校验闭集并提供读函数，不另立 42 格常量。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping

from ming_sim.assets import load_json_asset, require_dict
from ming_sim.centrifuge_ledger import CENTRIFUGE_AXES

_ASSET = "value_matrix.json"
_VALUE_FACTIONS = frozenset({"东林", "阉党", "军队", "皇党", "宗室", "西学", "中立"})


@lru_cache(maxsize=1)
def _loaded() -> tuple[tuple[str, ...], dict[str, dict[str, int]]]:
    raw = require_dict(load_json_asset(_ASSET), _ASSET)
    axes_raw = raw.get("axes")
    if not isinstance(axes_raw, list) or not axes_raw:
        raise SystemExit(f"content/{_ASSET}: axes 必须为非空数组")
    axes = tuple(str(item) for item in axes_raw)
    if len(axes) != 6 or frozenset(axes) != CENTRIFUGE_AXES:
        raise SystemExit(f"content/{_ASSET}: axes 必须等于六轴闭集")
    factions = require_dict(raw.get("factions"), f"{_ASSET}.factions")
    if frozenset(factions) != _VALUE_FACTIONS:
        raise SystemExit(f"content/{_ASSET}: factions 必须等于七派闭集")
    matrix: dict[str, dict[str, int]] = {}
    for faction, row in factions.items():
        cells = require_dict(row, f"{_ASSET}.factions.{faction}")
        if frozenset(cells) != CENTRIFUGE_AXES:
            raise SystemExit(f"content/{_ASSET}: {faction} 必须恰有六轴")
        parsed: dict[str, int] = {}
        for axis in axes:
            value = cells[axis]
            if isinstance(value, bool) or not isinstance(value, int) or not -2 <= value <= 2:
                raise SystemExit(f"content/{_ASSET}: {faction}.{axis} 必须为 -2..2 整数")
            parsed[axis] = value
        matrix[str(faction)] = parsed
    if sum(len(row) for row in matrix.values()) != 42:
        raise SystemExit(f"content/{_ASSET}: 须为 7 派 × 6 轴 = 42 格")
    return axes, matrix


def value_axes() -> tuple[str, ...]:
    return _loaded()[0]


VALUE_AXES: tuple[str, ...] = ()  # 兼容旧 import；运行时用 value_axes()


def _ensure_axes_alias() -> tuple[str, ...]:
    global VALUE_AXES
    VALUE_AXES = value_axes()
    return VALUE_AXES


_ensure_axes_alias()


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


def faction_axis_stance(faction: object, axis: object) -> int:
    """读矩阵格；未知派/轴 → 0（中性，不发明）。"""
    fac = str(faction or "").strip()
    ax = normalize_axis(axis)
    if not fac or ax is None:
        return 0
    row = _loaded()[1].get(fac)
    if row is None:
        return 0
    return int(row.get(ax, 0))


def mean_aligned_stance(
    faction: object,
    axes: object,
    *,
    direction: object = 1,
) -> float:
    """合同轴集上 stance×direction 的均值（−2…+2）。无轴 → 0。"""
    axis_list = normalize_axes(axes)
    if not axis_list:
        return 0.0
    direction_i = normalize_direction(direction, default=1)
    total = 0.0
    for axis in axis_list:
        total += float(faction_axis_stance(faction, axis) * direction_i)
    return total / float(len(axis_list))


def matrix_snapshot() -> Mapping[str, Mapping[str, int]]:
    """只读快照（测试/审计）。"""
    _axes, matrix = _loaded()
    return {faction: dict(cells) for faction, cells in matrix.items()}
