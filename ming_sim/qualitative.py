"""Shared score-to-language primitives for player-facing presentation."""

from __future__ import annotations

import re


# 历史邸报/章节正文是 LLM 产物，不能假定它已经遵守 P4。只拦截
# ``字段 + 直接数值`` 这种明确的裸抽象轴写法；钱粮、兵额、欠饷月数等
# 真实可数物不在这里列出，仍可随历史叙事传递。
_ABSTRACT_VALUE_RE = re.compile(
    r"(?:民心|动乱|皇威|忠诚(?:度)?|能力|操守|廉洁|清廉|胆略|勇气|满意度|态度|"
    r"朝势|军力|财力|士气|训练|装备|火器|机动|士绅阻力|军事压力|"
    r"满意|势力|威望|实力|经济|"
    r"进度|进展|bar(?:_value)?|public_support|unrest|loyalty|ability|"
    r"integrity|courage|satisfaction|leverage|military_strength|morale|"
    r"training|equipment|firearm_equipment|progress)"
    r"\s*(?:(?:值|评分|分数|得分|指标|数值)\s*)?"
    r"(?:[:：=]\s*|(?:由|为|达|高达|至|是|从)\s*|[（(]\s*|(?=[-+]?\d))"
    r"[-+]?\d+(?:\.\d+)?"
    r"(?:\s*/\s*100|\s*%)?\s*[）)]?",
    re.IGNORECASE,
)

# LLM prose frequently inserts connective words between an axis and its score
# ("忠诚已达98分", "民心跌至20").  This is deliberately fail-closed: all
# listed axes are abstract, while concrete quantities are absent from the set.
_ABSTRACT_NEARBY_NUMBER_RE = re.compile(
    r"(?:民心|动乱|皇威|忠诚(?:度)?|能力|操守|廉洁|清廉|胆略|勇气|满意度|态度|朝势|军力|财力|士气|训练|装备|火器|机动|士绅阻力|军事压力|满意|势力|威望|实力|经济|进度|进展)"
    # LLM prose freely varies the short connective (骤降至 / 尚余 / 已然达到),
    # so do not make the P4 boundary depend on an exhaustively maintained verb
    # list.  The preceding axis is already an abstract-only allowlist.
    r"\s*(?:[\u4e00-\u9fff]{1,4}\s*)?[-+]?\d+(?:\.\d+)?(?:\s*(?:分|%|/\s*100))?",
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
    if _ABSTRACT_VALUE_RE.search(rendered) or _ABSTRACT_NEARBY_NUMBER_RE.search(rendered):
        return f"（{kind}含抽象指标原值，已略去；请以当时正式定性奏报为准。）"
    return rendered


_AUDIENCE_ABSTRACT_BANDS = {
    "民心": ("堪忧", "堪忧", "尚可", "稳固", "拥戴"),
    "动乱": ("低", "渐起", "中等", "高", "已炽"),
    "皇威": ("低迷", "不足", "尚可", "隆重", "极盛"),
    "忠诚": ("疏离", "可疑", "平常", "可靠", "深厚"),
    "能力": ("欠熟", "平常", "能任", "干练", "卓异"),
    "操守": ("不堪", "可议", "平常", "端谨", "清正"),
    "清廉": ("不堪", "可议", "平常", "端谨", "清正"),
    "胆略": ("怯弱", "谨慎", "平常", "果敢", "雄健"),
    "满意度": ("不满", "冷淡", "平常", "顺应", "拥戴"),
    "满意": ("怨愤", "不满", "平常", "顺应", "拥戴"),
    "势力": ("极弱", "偏弱", "中等", "偏强", "强盛"),
    "威望": ("极弱", "偏弱", "中等", "偏强", "强盛"),
    "实力": ("极弱", "偏弱", "中等", "偏强", "强盛"),
    "经济": ("匮乏", "吃紧", "尚可", "充足", "丰裕"),
    "朝势": ("低", "偏低", "平常", "偏高", "强盛"),
    "军力": ("低", "偏低", "平常", "偏高", "强盛"),
    "财力": ("低", "偏低", "平常", "偏高", "充裕"),
    "士气": ("低迷", "不足", "平常", "振作", "高涨"),
    "训练": ("生疏", "不足", "平常", "纯熟", "精练"),
    "装备": ("匮乏", "短缺", "尚可", "精良", "充足"),
    "火器": ("匮乏", "短缺", "尚可", "精良", "充足"),
    "补给": ("断绝", "吃紧", "尚可", "充足", "丰裕"),
    "进度": ("未见起色", "初有进展", "稳步推进", "近于收束", "已平"),
    "进展": ("未见起色", "初有进展", "稳步推进", "近于收束", "已平"),
}


def qualitative_audience_text(text: object, kind: str = "见闻记录") -> str:
    """Translate labeled abstract axes before applying the shared P4 rejector."""
    rendered = str(text or "")
    names = "|".join(re.escape(name) for name in _AUDIENCE_ABSTRACT_BANDS)
    # A compound can contain two raw values ("势力从30升到70").  Translating
    # only its first half would leave the second value exposed, so reject the
    # original sentence before any local substitution.
    compound_axis = re.compile(
        rf"(?:{names})(?:度)?\s*(?:从\s*[-+]?\d+(?:\.\d+)?\s*(?:升到|降到|到)|高达\s*[-+]?\d+)",
        re.IGNORECASE,
    )
    if compound_axis.search(rendered):
        return safe_historical_text(rendered, kind)
    pattern = re.compile(
        rf"({names})\s*(?:(?:值|评分|分数|得分|指标|数值)\s*)?"
        r"(?:[:：=]\s*|(?:由|为|达|高达|至|是|从)\s*|(?=[-+]?\d))"
        r"([-+]?\d+(?:\.\d+)?)(?:\s*/\s*100|\s*%)?",
        re.IGNORECASE,
    )
    def replace(match: re.Match[str]) -> str:
        name, value = match.groups()
        return f"{name}{qualitative_band(value, _AUDIENCE_ABSTRACT_BANDS[name])}"
    return safe_historical_text(pattern.sub(replace, rendered), kind)


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
    # Missing values are not measured values.  Keep their neutral fallback at
    # the lower middle band instead of treating the conventional ``50``
    # default as a real score and promoting it into the next band.
    if value is None:
        index = qualitative_bucket(default, (20, 40, 60, 80), 0) - (1 if default else 0)
    else:
        try:
            int(value)
        except (TypeError, ValueError):
            index = qualitative_bucket(default, (20, 40, 60, 80), 0) - (1 if default else 0)
        else:
            index = qualitative_bucket(value, (20, 40, 60, 80), default)
    index = max(0, index)
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
