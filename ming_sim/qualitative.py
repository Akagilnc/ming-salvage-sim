"""Shared score-to-language primitives for player-facing presentation."""

from __future__ import annotations

from typing import Mapping


# ADR 0122: the one vocabulary for character axes crossing a player-facing
# LLM boundary.  Consumers may choose their output shape, but never redefine
# the score bands.
CHARACTER_QUALITATIVE_BANDS = {
    "loyalty": ("离心已显", "心志浮动", "大体守中", "颇知向背", "可托腹心"),
    "ability": ("才具浅薄", "才具有限", "堪当常务", "才具出众", "足任大事"),
    "integrity": ("操守多亏", "操守未稳", "操守平常", "操守清正", "清介可称"),
    "courage": ("临事易退", "多有顾忌", "进退审慎", "敢任其事", "临难不屈"),
    "intrigue": ("不谙权变", "少有心机", "颇有心计", "深谙机变", "权术老辣"),
}

CHARACTER_AXIS_LABELS = {
    "loyalty": "忠诚",
    "ability": "能力",
    "integrity": "清廉",
    "courage": "胆略",
    "intrigue": "阴谋",
}


def qualitative_character_axes(character: object) -> Mapping[str, str]:
    """Project all available character axes for player-facing LLM inputs."""
    projected = {
        CHARACTER_AXIS_LABELS[field]: qualitative_character_axis(
            field, getattr(character, field)
        )
        for field in ("loyalty", "ability", "integrity", "courage")
    }
    projected["党派认同"] = identity_band(getattr(character, "identity"))
    projected["阴谋"] = qualitative_character_axis("intrigue", getattr(character, "intrigue"))
    return projected


def qualitative_character_axis(field: str, value: object) -> str:
    """Project one character score through the canonical ADR 0122 bands."""
    return qualitative_band(value, CHARACTER_QUALITATIVE_BANDS[field])


def qualitative_character_attribute(field: str, value: object) -> str:
    """Render one canonical 0122 character attribute band for a player."""
    return qualitative_character_axis(field, value)

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


IDENTITY_BUCKET_CUTOFFS = (40, 80)


def identity_bucket(value: object) -> int:
    """Return the canonical low/middle/high party-identity bucket index."""
    return qualitative_bucket(value, IDENTITY_BUCKET_CUTOFFS, default=50)


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


_IDENTITY_BANDS = (
    "几乎不染党色", "党色较淡", "党色不显", "党色较深", "党色极深",
)


def identity_band(value: object) -> str:
    """Render party identity through the one shared qualitative vocabulary."""
    return qualitative_band(value, _IDENTITY_BANDS, default=50)


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


# #1356 / ADR 0143: four abstract axes — one ordered vocabulary each.
# Consumers pick the entry helper (or the constant for membership checks);
# never re-declare the five-word tuples at call sites.
PUBLIC_SUPPORT_BANDS = ("堪忧", "偏弱", "起伏", "尚可", "稳固")
POWER_BANDS = ("极弱", "偏弱", "中等", "偏强", "强盛")  # also 皇威
SATISFACTION_BANDS = ("怨愤", "不满", "平常", "顺应", "拥戴")
# Issue/dossier bar progress — single vocabulary (was tools._progress_band).
PROGRESS_BANDS = ("未见起色", "略有起色", "进展过半", "进展顺利", "近于收束")
# Region resistance / military pressure — single vocabulary (db.region_report + #652 two_axis).
GENTRY_RESISTANCE_BANDS = ("极弱", "偏弱", "中等", "偏强", "强")
MILITARY_PRESSURE_BANDS = ("极低", "偏低", "中等", "偏高", "极高")
DISASTER_SEVERITY_BANDS = ("轻微", "偏轻", "中等", "偏重", "极重")


def public_support_band(value: object) -> str:
    """Present 民心 / region public_support without exposing the score."""
    return qualitative_band(value, PUBLIC_SUPPORT_BANDS)


def power_band(value: object) -> str:
    """Present a faction/power abstract score without exposing its number."""
    return qualitative_band(value, POWER_BANDS, default=50)


def imperial_authority_band(value: object) -> str:
    """Present 皇威 through the shared power vocabulary (missing → 0)."""
    return qualitative_band(value, POWER_BANDS, default=0)


def satisfaction_band(value: object) -> str:
    """Present faction/class satisfaction without exposing the score."""
    return qualitative_band(value, SATISFACTION_BANDS)


def progress_band(value: object) -> str:
    """Present issue bar_value / 局势进度 without exposing the score."""
    return qualitative_band(value, PROGRESS_BANDS)


def gentry_resistance_band(value: object) -> str:
    """Present region gentry_resistance without exposing the score."""
    return qualitative_band(value, GENTRY_RESISTANCE_BANDS)


def military_pressure_band(value: object) -> str:
    """Present region military_pressure / 流寇压力 without exposing the score."""
    return qualitative_band(value, MILITARY_PRESSURE_BANDS)


def disaster_severity_band(value: object) -> str:
    """Present issue/disaster severity without exposing the score."""
    return qualitative_band(value, DISASTER_SEVERITY_BANDS)


def population_wan_kou_label(persons: object) -> str:
    """ADR 0088/#648：裸人数 → 「约N万口」定性（P4 玩家可感 LLM 输入）。"""
    try:
        n = int(0 if persons is None else persons)
    except (TypeError, ValueError):
        n = 0
    wan = n // 10000
    if wan <= 0:
        return "不足一万口"
    return f"约{wan}万口"
