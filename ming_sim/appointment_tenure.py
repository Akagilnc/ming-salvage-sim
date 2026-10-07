"""任命名分成色的持久化契约（ADR 0064）。"""

from __future__ import annotations

APPOINTMENT_TENURES = frozenset({"真除", "署理", "兼署", "加衔"})
DEFAULT_APPOINTMENT_TENURE = "真除"


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
    """执行侧读端：非法/空值按真除兜底，不抛（缺备档与空任别合法读取）。"""
    text = str(value or "").strip()
    if text in APPOINTMENT_TENURES:
        return text
    return DEFAULT_APPOINTMENT_TENURE
