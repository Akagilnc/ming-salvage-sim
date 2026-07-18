"""Shared score-to-language primitives for player-facing presentation."""

from __future__ import annotations

import re


# 历史邸报/章节正文是 LLM 产物，不能假定它已经遵守 P4。只拦截
# ``字段 + 直接数值`` 这种明确的裸抽象轴写法；钱粮、兵额、欠饷月数等
# 真实可数物不在这里列出，仍可随历史叙事传递。
def safe_historical_text(text: object, kind: str = "历史记录") -> str:
    """Return historical prose only when it does not leak abstract raw scores.

    Stored reports remain authoritative game history; this presentation guard
    rejects unsafe prose at every minister-facing history seam instead of
    trying to infer a qualitative bucket from arbitrary LLM text.
    """
    rendered = str(text or "").strip()
    if not rendered:
        return ""
    # Chinese commas commonly join independent factual clauses.  Project at
    # that fragment boundary so one unsafe score cannot erase a lawful money,
    # head-count, or elapsed-time fact beside it.
    parts = re.split(r"([，,；;。！？\n])", rendered)
    out: list[str] = []
    for fragment in parts:
        if not fragment or re.fullmatch(r"[，,；;。！？\n]", fragment):
            out.append(fragment)
        elif _has_unqualified_abstract_score(fragment):
            out.append(f"（{kind}含抽象指标原值，已略去）")
        else:
            out.append(fragment)
    return "".join(out)


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
    "机动": ("迟滞", "受限", "尚可", "灵便", "迅捷"),
    "军事压力": ("轻微", "有限", "可控", "沉重", "极重"),
    "士绅阻力": ("轻微", "有限", "可控", "沉重", "极重"),
    "进度": ("未见起色", "初有进展", "稳步推进", "近于收束", "已平"),
    "进展": ("未见起色", "初有进展", "稳步推进", "近于收束", "已平"),
    "风险": ("轻微", "有限", "可控", "沉重", "极重"),
    "等级": ("低", "偏低", "平常", "偏高", "高"),
    "完好度": ("残破", "欠佳", "尚可", "良好", "完好"),
    # Schema aliases are presentation aliases too.  Keep them in this one
    # registry so every player-facing P4 boundary rejects the same raw axes.
    "军心": ("低迷", "不足", "平常", "振作", "高涨"),
    "听命": ("疏离", "可疑", "平常", "可靠", "深厚"),
    "操练": ("生疏", "不足", "平常", "纯熟", "精练"),
    "器械": ("匮乏", "短缺", "尚可", "精良", "充足"),
    "粮饷": ("断绝", "吃紧", "尚可", "充足", "丰裕"),
    "影响力": ("极弱", "偏弱", "中等", "偏强", "强盛"),
    "兵势": ("低", "偏低", "平常", "偏高", "强盛"),
    "军势": ("低", "偏低", "平常", "偏高", "强盛"),
    "军事力量": ("低", "偏低", "平常", "偏高", "强盛"),
    "内聚": ("低", "偏低", "平常", "偏高", "强盛"),
    "凝聚": ("低", "偏低", "平常", "偏高", "强盛"),
    "凝聚力": ("低", "偏低", "平常", "偏高", "强盛"),
}

# This registry is the single source of truth for Chinese abstract P4 axes.
# The raw-score rejector and the renderer must agree on the same vocabulary;
# concrete quantities are exempt only when their unit makes them observable
# game facts rather than a hidden score.
_ABSTRACT_AXIS_PATTERN = "|".join(
    [*(re.escape(name) for name in _AUDIENCE_ABSTRACT_BANDS),
     "bar(?:_value)?", "public_support", "unrest", "loyalty", "ability",
     "integrity", "courage", "satisfaction", "leverage", "military_strength",
     "morale", "training", "equipment", "firearm_equipment", "mobility",
     "military_pressure", "gentry_resistance", "progress"]
)
# Military / fiscal countable units after a number stay lawful (``一营`` / ``三千人``).
_COUNTABLE_FACT_UNITS = r"名|人|门|匹|艘|座|处|条|石|斤|担|斛|日|月|年|营|哨|队|支|标"
# Qualitative band words may sit between an axis and a raw score
# (``民心堪忧15分``).  Keep them optional and axis-local so countable facts
# with unrelated intervening prose stay lawful.
_ABSTRACT_BAND_WORD = "|".join(
    sorted(
        {re.escape(word) for words in _AUDIENCE_ABSTRACT_BANDS.values() for word in words},
        key=len,
        reverse=True,
    )
)
# Approximate / comparator connectors used in natural LLM historical prose.
# Longer alternatives first so ``大约`` / ``约等于`` / ``约略`` / ``大概`` win
# over bare ``约`` (``能力约略70`` must not fall through as ``约`` + ``略70``).
# Bare ``到`` is a free peer of bare ``至`` (digit-bound) so unlisted stems
# such as ``增加到`` / ``涨到`` / ``恢复到`` redline without a stem treadmill.
_ABSTRACT_SCORE_CONNECTOR = (
    r"由|为|达|高达|至|到了|到|是|从|"
    r"不足|不到|低于|少于|不满|超过|高于|大于|"
    r"接近|近于|近乎|将近|不及|逼近|几乎|"
    r"约等于?|大约|大概|大致|约莫|约摸|约略|约计|约|差不多|"
    r"跌破|突破|冲破"
)
# After a connector, natural prose may add a directional complement or copula:
# ``跌破到30`` / ``接近到40`` / ``差不多是70`` / ``大约是70`` / ``提升了70``.
_ABSTRACT_CONNECTOR_COMPLEMENT = r"(?:到|至|了|是)?"
# Softener / state word before ``在 + number`` constructions:
# ``大约在30左右`` / ``约略在70左右`` / ``已在70左右`` / ``维持在40`` / ``处在40``.
_ABSTRACT_AT_PREFIX = (
    r"(?:已(?:经|然)?|则|仍(?:然)?|尚|"
    r"大约|大概|大致|约莫|约摸|约略|约计|差不多|约|"
    r"维持|保持|稳定|停留|处)?"
)
# Chinese abstract scores use complete numeral shapes only — never a free
# ``[十百…]+`` run that swallows idioms (``十分出众`` / ``一尘不染``).
_CHINESE_SCORE_BODY = (
    r"(?:一百(?:零[零〇一二两三四五六七八九])?"
    r"|[二三四五六七八九]十[零〇一二两三四五六七八九]?"
    r"|十[一二三四五六七八九]"
    r"|十(?!分)"  # bare 十 = 10 after a connector; never ``十分`` idiom
    r"|[零〇一二两三四五六七八九])"
)
_ABSTRACT_SCORE_MODIFIERS = ("左右", "上下", "有余", "余")
_ABSTRACT_SCORE_MODIFIER_PATTERN = "|".join(_ABSTRACT_SCORE_MODIFIERS)
_ABSTRACT_NUMBER_START = r"[-+]?\d"
_ABSTRACT_SCORE_NUMBER = (
    rf"(?:"
    rf"[-+]?\d+(?:\.\d+)?(?:\s*/\s*100|\s*%|\s*分)?"
    rf"|{_CHINESE_SCORE_BODY}"
    rf")"
    rf"(?!\d|[零〇一二两三四五六七八九十百])"
    rf"(?:\s*(?:{_ABSTRACT_SCORE_MODIFIER_PATTERN}))?"
    rf"(?!(?:\s*(?:{_ABSTRACT_SCORE_MODIFIER_PATTERN}))?\s*(?:{_COUNTABLE_FACT_UNITS}))"
)
# A bare Chinese score must be a complete standalone token.  The CJK boundary
# preserves both idioms and countable facts (``一尘不染`` / ``八十人``), while
# an abstract axis followed by an otherwise unqualified token (``能力八十``)
# is the same P4 violation as its Arabic form.
_BARE_CHINESE_SCORE_RE = re.compile(
    rf"(?<![第\d零〇一二两三四五六七八九十百]){_CHINESE_SCORE_BODY}"
    rf"(?:\s*(?:分|%|{_ABSTRACT_SCORE_MODIFIER_PATTERN}))?(?![\d\u3400-\u9fff])"
)


def _has_unqualified_abstract_score(fragment: str) -> bool:
    """Reject a bare score in the same factual fragment as an abstract axis.

    P4 is an axis/unit invariant, not a catalogue of verbs between the two.
    Concrete quantities keep their unit (银两、人、月等); a number without one
    near an abstract axis cannot cross the player boundary.
    """
    if _ABSTRACT_VALUE_RE.search(fragment) or _ABSTRACT_NEARBY_NUMBER_RE.search(fragment):
        return True
    axis = re.search(rf"(?:{_ABSTRACT_AXIS_PATTERN})(?:度)?", fragment, re.IGNORECASE)
    if not axis:
        return False
    tail = fragment[axis.end():]
    # The invariant is about *bare numeric scores*.  Complete token boundaries
    # keep Chinese idioms and unit-qualified counts out of this score class.
    return bool(
        re.search(rf"[-+]?\d+(?:\.\d+)?(?!\d|\s*(?:{_COUNTABLE_FACT_UNITS}))", tail)
        or _BARE_CHINESE_SCORE_RE.search(tail)
    )
_ABSTRACT_VALUE_RE = re.compile(
    rf"(?:{_ABSTRACT_AXIS_PATTERN})(?:度)?\s*"
    rf"(?:(?:{_ABSTRACT_BAND_WORD})\s*)?"
    rf"(?:(?:值|评分|分数|得分|指标|数值)\s*)?"
    rf"(?:"
    # ``补给在30左右`` / ``大约在30左右`` / ``已在70左右`` / ``维持在40`` / ``处在40``
    rf"(?:{_ABSTRACT_AT_PREFIX})\s*在\s*{_ABSTRACT_SCORE_NUMBER}"
    rf"|"
    # ``忠诚接近40`` / ``能力约70`` / ``跌破到30`` / ``差不多是70`` / bare ``忠诚88``
    # / Chinese ``能力约七十`` (connector-bound; no bare Chinese adjacency)
    rf"(?:[:：=]\s*|(?:{_ABSTRACT_SCORE_CONNECTOR})\s*{_ABSTRACT_CONNECTOR_COMPLEMENT}\s*|[（(]\s*|(?={_ABSTRACT_NUMBER_START}))"
    rf"{_ABSTRACT_SCORE_NUMBER}\s*[）)]?"
    rf")",
    re.IGNORECASE,
)
# A score may be wrapped in natural prose (``补给整体已经明显恶化至20``),
# but that prose has a small, semantic grammar: a state noun, optional
# adverbial modifiers, then a change/value verb.  Do not use a generic
# ``汉字{1,N}`` bridge here: it both misses longer prose and mistakes concrete
# facts such as ``火器营新募3000人`` for an abstract axis.
_ABSTRACT_STATE_NOUN = r"(?:整体|总体|水平|状况|情形|供应|保障)?"
# Historical prose can insert a full causal clause between an abstract axis
# and its raw score.  Bound the bridge generously enough for that prose while
# still requiring the axis and a state/value verb on both sides.
_ABSTRACT_STATE_CONNECTIVE = r"(?:[^\d。！？；;\n]{0,120}?)"
_ABSTRACT_STATE_MODIFIER = (
    r"(?:(?:已(?:经|然)?|正(?:在)?|仍(?:然)?|尚|逐步|明显|显著|大幅|持续|"
    r"不断|迅速|急剧|骤然|骤|略有|有所|日益|愈发|更为|相当|十分|极其))*"
)
# Directional change verbs allow optional 高/低 then optional 至/到/了 so
# ``升高到`` / ``降低到`` / ``提升了`` match as one verb (aspect 了 peers 至/到).
# Bare ``到`` peers bare ``至`` so unlisted stems (``增加/涨/恢复/减少`` + 到)
# match via the connective bridge without growing the stem list.
_ABSTRACT_DIR_OR_ASPECT = r"(?:至|到|了)?"
_ABSTRACT_STATE_VERB = (
    rf"(?:升(?:高)?{_ABSTRACT_DIR_OR_ASPECT}|降(?:低)?{_ABSTRACT_DIR_OR_ASPECT}|"
    rf"提高{_ABSTRACT_DIR_OR_ASPECT}|提升{_ABSTRACT_DIR_OR_ASPECT}|"
    rf"回落{_ABSTRACT_DIR_OR_ASPECT}|下滑{_ABSTRACT_DIR_OR_ASPECT}|下跌{_ABSTRACT_DIR_OR_ASPECT}|"
    rf"跌破{_ABSTRACT_DIR_OR_ASPECT}|跌{_ABSTRACT_DIR_OR_ASPECT}|恶化{_ABSTRACT_DIR_OR_ASPECT}|改善{_ABSTRACT_DIR_OR_ASPECT}|"
    r"达到?|变为?|到了|"
    rf"接近{_ABSTRACT_DIR_OR_ASPECT}|近于|不及|逼近|几乎|"
    r"约等于?|大约|大概|大致|约莫|约摸|约略|约计|约|差不多|"
    r"只有|仅有|仅|为|至|到|有|余|剩)"
)
_ABSTRACT_NEARBY_NUMBER_RE = re.compile(
    rf"(?:{_ABSTRACT_AXIS_PATTERN})(?:度)?\s*"
    rf"(?:{_ABSTRACT_STATE_CONNECTIVE}{_ABSTRACT_STATE_NOUN}{_ABSTRACT_STATE_MODIFIER}{_ABSTRACT_STATE_VERB}\s*|(?={_ABSTRACT_NUMBER_START}))"
    rf"{_ABSTRACT_SCORE_NUMBER}",
    re.IGNORECASE,
)


def qualitative_audience_text(text: object, kind: str = "见闻记录") -> str:
    """Translate labeled abstract axes before applying the shared P4 rejector."""
    rendered = str(text or "")
    names = "|".join(re.escape(name) for name in _AUDIENCE_ABSTRACT_BANDS)
    # A compound can contain two raw values ("势力从30增加到70").  Translating
    # only its first half would leave the second value exposed, so reject the
    # original sentence before any local substitution.  Any second score after
    # 从/由 within a short span counts — do not hard-code 升到/降到 only.
    compound_axis = re.compile(
        rf"(?:{names})(?:度)?\s*"
        rf"(?:"
        rf"(?:从|由)\s*{_ABSTRACT_SCORE_NUMBER}\s*.{{0,24}}?{_ABSTRACT_SCORE_NUMBER}"
        rf"|高达\s*{_ABSTRACT_SCORE_NUMBER}"
        rf")",
        re.IGNORECASE,
    )
    if compound_axis.search(rendered):
        return safe_historical_text(rendered, kind)
    pattern = re.compile(
        rf"({names})\s*(?:(?:{_ABSTRACT_BAND_WORD})\s*)?"
        rf"(?:(?:值|评分|分数|得分|指标|数值)\s*)?"
        rf"(?:[:：=]\s*|"
        rf"(?:{_ABSTRACT_SCORE_CONNECTOR})\s*{_ABSTRACT_CONNECTOR_COMPLEMENT}\s*|"
        rf"(?:{_ABSTRACT_AT_PREFIX})\s*在\s*|(?={_ABSTRACT_NUMBER_START}))"
        rf"({_ABSTRACT_SCORE_NUMBER})",
        re.IGNORECASE,
    )
    def replace(match: re.Match[str]) -> str:
        name, value = match.groups()
        # Band substitution needs a machine int; Chinese numeral scores fall
        # through to the shared rejector instead of inventing a parser.
        raw = str(value).strip()
        for suffix in (*_ABSTRACT_SCORE_MODIFIERS, "分", "%"):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)].strip()
        if "/" in raw:
            raw = raw.split("/", 1)[0].strip()
        try:
            score: object = int(float(raw))
        except (TypeError, ValueError):
            return match.group(0)
        return f"{name}{qualitative_band(score, _AUDIENCE_ABSTRACT_BANDS[name])}"
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


def power_band(value: object) -> str:
    """Present a faction/power abstract score without exposing its number."""
    return qualitative_band(value, ("极弱", "偏弱", "中等", "偏强", "强盛"), default=50)
