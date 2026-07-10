"""Shared qualitative presentation primitives."""

from ming_sim.qualitative import (
    building_qualitative_fields,
    qualitative_band,
    qualitative_bucket,
)


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
