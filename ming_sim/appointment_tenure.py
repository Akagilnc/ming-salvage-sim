"""任命名分成色的持久化契约（ADR 0064）。"""

APPOINTMENT_TENURES = frozenset({"真除", "署理", "兼署", "加衔"})
DEFAULT_APPOINTMENT_TENURE = "真除"


def appointment_tenure_from(payload: dict[str, object]) -> str:
    """读取公开中文字段或内部英文别名；旧载荷按真除兜底。"""
    value = payload.get("任别", payload.get("appointment_tenure"))
    tenure = str(value or DEFAULT_APPOINTMENT_TENURE).strip()
    if tenure not in APPOINTMENT_TENURES:
        raise ValueError(f"任别非白名单：{tenure}")
    return tenure
