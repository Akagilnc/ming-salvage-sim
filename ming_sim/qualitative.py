"""Shared score-to-language primitives for player-facing presentation."""

from __future__ import annotations

import re


# 历史邸报/章节正文是 LLM 产物，不能假定它已经遵守 P4。只拦截
# ``字段 + 直接数值`` 这种明确的裸抽象轴写法；钱粮、兵额、欠饷月数等
# 真实可数物不在这里列出，仍可随历史叙事传递。
_ABSTRACT_VALUE_RE = re.compile(
    r"(?:民心|动乱|皇威|忠诚(?:度)?|能力|操守|廉洁|胆略|勇气|满意度|态度|"
    r"朝势|军力|财力|士气|训练|装备|火器|机动|士绅阻力|军事压力|"
    r"进度|进展|bar(?:_value)?|public_support|unrest|loyalty|ability|"
    r"integrity|courage|satisfaction|leverage|military_strength|morale|"
    r"training|equipment|firearm_equipment|progress)"
    r"\s*(?:[:：=]\s*|(?:由|为|达|至|是|从)\s*|"
    r"(?:值|评分|分数|得分|指标|数值)?\s*(?:由|为|达|至|是|从)?\s*(?=[-+]?\d))"
    r"[-+]?\d+(?:\.\d+)?"
    r"(?:\s*/\s*100|\s*%)?",
    re.IGNORECASE,
)


def safe_historical_text(text: object, kind: str = "历史记录") -> str:
    """Return historical prose only when it does not leak abstract raw scores.

    Stored reports remain authoritative game history; this presentation guard
    rejects unsafe prose at every minister-facing history seam instead of
    trying to infer a qualitative bucket from arbitrary LLM text.
    """
    rendered = str(text or "").strip()
    if not rendered:
        return ""
    if _ABSTRACT_VALUE_RE.search(rendered):
        return f"（{kind}含抽象指标原值，已略去；请以当时正式定性奏报为准。）"
    return rendered


def qualitative_bucket(
    value: object,
    cutoffs: tuple[int, ...],
    default: int = 0,
) -> int:
    """Return the zero-based bucket for a score, preserving valid zeroes."""
    try:
        score = int(default if value is None else value)
    except (TypeError, ValueError):
        score = default
    return sum(score >= cutoff for cutoff in cutoffs)


def qualitative_band(value: object, words: tuple[str, ...], default: int = 0) -> str:
    """Return one of five ordered labels without exposing the source score."""
    index = qualitative_bucket(value, (20, 40, 60, 80), default)
    index = min(index, len(words) - 1)
    return words[index]


def building_level_description(value: object) -> str:
    level = qualitative_bucket(value, (2, 3, 4, 5), default=0)
    return ("初设", "成形", "完备", "宏整", "巨构")[level]


def building_condition_description(value: object) -> str:
    condition = qualitative_bucket(value, (20, 40, 60, 80), default=0)
    return ("残损", "失修", "尚可", "完好", "坚固")[condition]


def building_risk_description(value: object) -> str:
    risk = qualitative_bucket(value, (20, 50, 80), default=0)
    return ("低", "中", "偏高", "极高")[risk]


def city_defense_description(value: object) -> str:
    """Describe the discrete 0–5 city-defense level without exposing its score."""
    try:
        level = int(0 if value is None else value)
    except (TypeError, ValueError):
        level = 0
    level = max(0, min(level, 5))
    return ("初设", "简陋", "成形", "坚固", "重镇", "雄城")[level]


def building_qualitative_fields(row: object) -> tuple[str, str, str]:
    """Shared building scale, condition, and risk presentation."""
    return (
        building_level_description(row["level"]),
        building_condition_description(row["condition"]),
        building_risk_description(row["risk"]),
    )


def building_output_effect(metric: str, amount: object, prefix: str = "") -> str:
    """Describe a building's output without exposing abstract score values."""
    if not metric:
        return ""
    if metric in ("民心", "皇威"):
        try:
            output = int(0 if amount is None else amount)
        except (TypeError, ValueError):
            output = 0
        effect = "略有裨益" if output < 10 else "颇有裨益" if output < 30 else "有显著裨益"
        return f"{prefix}对{metric}{effect}"
    return f"{prefix}产出{metric}{amount}"


def power_band(value: object) -> str:
    """Present a faction/power abstract score without exposing its number."""
    return qualitative_band(value, ("极弱", "偏弱", "中等", "偏强", "强盛"), default=50)
