"""任命名分成色的持久化契约（ADR 0064）。"""

from __future__ import annotations

from ming_sim.exceptions import DeclarationDataError

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
            raise DeclarationDataError(f"任别非白名单：{value}")
    return payload[keys[0]]  # type: ignore[return-value]


def normalize_appointment_tenure(value: object) -> str:
    """执行侧读端：非法/空值按真除兜底，不抛（缺备字段的现役读口径）。"""
    text = str(value or "").strip()
    if text in APPOINTMENT_TENURES:
        return text
    return DEFAULT_APPOINTMENT_TENURE


def project_appointment_facts(
    db: object,
    payload: dict[str, object],
    *,
    target_id: object = "",
) -> dict[str, object]:
    """任命案卷/预推共用的任别默认与 break_rank 事实投影（#562 / ADR 0064 / #1928）。

    唯一权威实现：正式成案与 office 预推候选均调此函数，禁平行第二套。
    调用方仅对 action_type=appointment 使用；罢免不经此投影。
    """
    from ming_sim.office_rank import appointment_break_rank

    out = dict(payload)
    out["任别"] = appointment_tenure_from(out)
    out.pop("appointment_tenure", None)
    out["break_rank"] = appointment_break_rank(
        db,
        out.get("name") or target_id,
        out.get("office") or out.get("new_office"),
        out.get("office_type") or out.get("new_office_type"),
    )
    return out
