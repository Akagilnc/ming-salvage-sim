"""Shared qualitative presentation primitives."""

from ming_sim.qualitative import (
    building_qualitative_fields,
    qualitative_band,
    qualitative_bucket,
    safe_historical_text,
)


def test_safe_historical_text_rejects_adjacent_abstract_values():
    """历史文本的 P4 护栏也要咬住无分隔的裸值变异。"""
    for injected in (
        "忠诚88",
        "能力98分",
        "民心73/100",
        "进度73/100",
        "忠诚值88",
        "能力评分98",
        "民心值73",
        "进度评分73/100",
        "清廉98",
        "清廉值：98",
    ):
        rendered = safe_historical_text(injected)
        assert "已略去" in rendered, injected


def test_safe_historical_text_covers_hidden_aliases_without_crossing_sentence_boundary():
    for injected in ("风险91", "等级4", "完好度22", "忠诚仅30分"):
        assert "已略去" in safe_historical_text(injected), injected
    assert "已略去" not in safe_historical_text("火器营已整顿。新募三千人。")


def test_safe_historical_text_rejects_common_labeled_value_forms():
    for injected in (
        "忠诚值为88",
        "能力评分为98",
        "民心数值达73",
        "进度指标至41/100",
        "忠诚值：88",
        "能力评分：98",
        "民心数值：73",
        "进度指标：41/100",
        "清廉98",
        "清廉值：98",
    ):
        assert "已略去" in safe_historical_text(injected), injected


def test_qualitative_audience_text_rejects_compound_and_adverbial_raw_axes():
    from ming_sim.qualitative import qualitative_audience_text
    for injected in ("势力从30升到70", "忠诚度高达98分"):
        assert "已略去" in qualitative_audience_text(injected), injected


def test_safe_historical_text_rejects_nearby_raw_axis_variants():
    for injected in (
        "忠诚已达98分", "忠诚提高到98", "势力提升至70", "能力只有30分", "民心跌至20",
        "忠诚骤降至20", "能力尚余30分", "势力已然达到70",
    ):
        assert "已略去" in safe_historical_text(injected), injected


def test_p4_projection_keeps_lawful_chinese_comma_fragments_and_rejects_comparators():
    rendered = safe_historical_text("忠诚不足30分，拨银三万两，已过六个月")
    assert "忠诚不足30分" not in rendered
    assert "已略去" in rendered
    assert "拨银三万两" in rendered
    assert "已过六个月" in rendered


def test_p4_guard_rejects_approximate_and_comparator_raw_scores():
    """Approximate / comparator score phrasing must not leak past the shared P4 guard.

    Natural LLM prose uses 接近/不及/跌破/约/左右/大约/差不多 forms that sit
    outside the older connector list; player-visible mindreading reply_text
    and history seams all call this one rejector.
    """
    for injected in (
        "忠诚接近40",
        "士气不及20",
        "军心跌破30",
        "能力约70",
        "补给在30左右",
        "能力大约70",
        "忠诚差不多40",
        "山东民心堪忧15分",
        "势力将近80",
        "训练约等于50",
        # Residual synonym / composition holes after the first approx pass.
        "忠诚大概40",
        "忠诚大致40",
        "能力约莫70",
        "能力约摸70",
        "军心跌破到30",
        "忠诚接近到40",
        "补给大约在30左右",
        "能力已在70左右",
        "能力大约是70",
        "能力差不多是70",
        "能力逼近70",
        "能力几乎70",
        "能力到了70",
        "忠诚维持在40",
        # Residual state-verb composition: 降低/升高 + 到 (not only 至/到 alone).
        "能力降低到30",
        "士气升高到80",
        "能力降低至30",
        "士气升高至80",
        "士气回落到40",
        "训练下滑到20",
        # Residual approx synonym: 约略 (and same-class 约计) before bare 约.
        "能力约略70",
        "忠诚约略是70",
        "能力约略在70左右",
        "能力约计70",
    ):
        rendered = safe_historical_text(injected)
        assert "已略去" in rendered, injected
        assert not any(ch.isdigit() for ch in rendered), (injected, rendered)

    # Lawful countable facts beside an approximate leak must survive.
    mixed = safe_historical_text("忠诚大概40，拨银三万两，已过六个月")
    assert "已略去" in mixed
    assert "拨银三万两" in mixed
    assert "已过六个月" in mixed
    assert "大概40" not in mixed


def test_p4_guard_rejects_supply_score_but_keeps_countable_people():
    assert "已略去" in safe_historical_text("补给已经明显恶化至20")
    assert "已略去" in safe_historical_text("补给整体已经明显恶化至20")
    assert safe_historical_text("能力出众的3名将领奉命整训") == "能力出众的3名将领奉命整训"
    assert safe_historical_text("火器营新募3000人") == "火器营新募3000人"
    assert safe_historical_text("前线补给尚余300石，足供三日") == "前线补给尚余300石，足供三日"


def test_p4_guard_rejects_long_connective_and_complete_abstract_axes():
    for injected in (
        "补给前线保障仍在持续恶化至20",
        "机动能力经连日奔袭后已降至20",
        "军事压力在多路来攻下高达90",
        "士绅阻力经多番劝谕仍为80",
        "补给在道路断绝和军需转运迟滞的影响下高达20",
    ):
        assert "已略去" in safe_historical_text(injected), injected


def test_p4_guard_rejects_unbounded_narrative_connective_without_hiding_counts():
    injected = "补给在敌军反复袭扰、道路多处断绝、军需转运一再延误、各营存粮难继的情形下高达20"
    assert "已略去" in safe_historical_text(injected)
    assert safe_historical_text("火器营新募3000人") == "火器营新募3000人"


def test_p4_guard_covers_machine_axis_aliases_without_hiding_countable_facts():
    """Aliases accepted by the game schema are hidden by the same P4 registry."""
    for injected in (
        "军心高达90",
        "凝聚力为20",
        "影响力从30升到70",
        "粮饷保障长期恶化至20",
    ):
        assert "已略去" in safe_historical_text(injected), injected

    assert safe_historical_text("军心振作的3000人已抵营") == "军心振作的3000人已抵营"


def test_qualitative_band_preserves_zero_and_uses_default_only_for_missing_or_invalid():
    words = ("low", "middle", "high", "very high", "max")

    assert qualitative_band(0, words) == "low"
    assert qualitative_band(None, words, default=50) == "middle"
    assert qualitative_band("not-a-score", words, default=50) == "middle"


def test_qualitative_bucket_preserves_zero_and_supports_three_way_identity_bucket():
    assert qualitative_bucket(0, (40, 80), default=50) == 0
    assert qualitative_bucket(40, (40, 80), default=50) == 1
    assert qualitative_bucket(80, (40, 80), default=50) == 2
    assert qualitative_bucket(None, (40, 80), default=50) == 1


def test_building_qualitative_fields_is_shared_public_interface():
    row = {"level": 0, "condition": 0, "risk": 0}

    assert building_qualitative_fields(row) == ("初设", "残损", "低")
