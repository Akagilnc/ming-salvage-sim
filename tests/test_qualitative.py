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


def test_p4_guard_rejects_supply_score_but_keeps_countable_people():
    assert "已略去" in safe_historical_text("补给已经明显恶化至20")
    assert safe_historical_text("能力出众的3名将领奉命整训") == "能力出众的3名将领奉命整训"


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
