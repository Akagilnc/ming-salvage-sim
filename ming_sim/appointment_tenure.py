"""任命名分成色的持久化契约（ADR 0064）与执行侧号令力读端（#613）。"""

from __future__ import annotations

from typing import Mapping, Sequence

APPOINTMENT_TENURES = frozenset({"真除", "署理", "兼署", "加衔"})
DEFAULT_APPOINTMENT_TENURE = "真除"

# 号令力次序（PRD ID-1）：真除＞兼署＞署理＞加衔。数值越大号令越实。
# 四档必须两两可分，兼署不得与真除/署理塌缩混同。
COMMAND_POWER_RANK: Mapping[str, int] = {
    "真除": 3,
    "兼署": 2,
    "署理": 1,
    "加衔": 0,
}

# 执行格打折走样权重：越大越易走样（号令力的逆序）。
BASE_DISTORTION_WEIGHT: Mapping[str, int] = {
    "真除": 0,
    "兼署": 1,
    "署理": 2,
    "加衔": 3,
}

# 在持授权按权项抬升号令力（降低走样权重）；收回后不再计。
AUTHORITY_COMMAND_RELIEF: Mapping[str, int] = {
    "尚方剑密授": 2,
    "便宜行事": 1,
    "专差督办": 1,
    "新机构专办": 1,
}


def appointment_tenure_from(payload: dict[str, object]) -> str:
    """读取公开中文字段或内部英文别名；仅无任别字段的旧载荷按真除兜底。"""
    keys = [key for key in ("任别", "appointment_tenure") if key in payload]
    if not keys:
        return DEFAULT_APPOINTMENT_TENURE

    for key in keys:
        value = payload[key]
        if not isinstance(value, str) or value not in APPOINTMENT_TENURES:
            raise ValueError(f"任别非白名单：{value}")
    return payload[keys[0]]  # type: ignore[return-value]


def normalize_appointment_tenure(value: object) -> str:
    """执行侧读端：非法/空值按真除兜底，不抛（旧档与缺备档兼容）。"""
    text = str(value or "").strip()
    if text in APPOINTMENT_TENURES:
        return text
    return DEFAULT_APPOINTMENT_TENURE


def command_power_rank(tenure: object) -> int:
    """号令力档位：真除=3 … 加衔=0。"""
    return int(COMMAND_POWER_RANK[normalize_appointment_tenure(tenure)])


def execution_distortion_weight(
    tenure: object,
    held_authorities: Sequence[Mapping[str, object]] | None = None,
) -> int:
    """执行格打折走样权重：任别定基线，在持授权按 privilege 减免，下限 0。"""
    base = int(BASE_DISTORTION_WEIGHT[normalize_appointment_tenure(tenure)])
    relief = 0
    for item in held_authorities or ():
        if not isinstance(item, dict):
            continue
        privilege = str(item.get("privilege") or "").strip()
        relief = max(relief, int(AUTHORITY_COMMAND_RELIEF.get(privilege, 0)))
    return max(0, base - relief)
