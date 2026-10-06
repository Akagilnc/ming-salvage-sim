"""任命名分成色的持久化契约（ADR 0064）与执行侧号令力读端（#613）。"""

from __future__ import annotations

from typing import Mapping

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
