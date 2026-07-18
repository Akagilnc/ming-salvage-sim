from tests.section_rejection_helpers import SectionRejectionHarness


def test_section_rejection_harness_uses_current_turn_and_filters_section(game):
    harness = SectionRejectionHarness(game)

    rows = harness.settle(
        {"economy_moves": [{"account": "并不存在的账户", "delta": 1}]},
        section="economy_moves_rejections",
    )

    assert len(rows) == 1
    assert rows[0][0] == "economy_moves_rejections"


def test_section_rejection_harness_returns_empty_for_valid_input(game):
    harness = SectionRejectionHarness(game)

    rows = harness.settle(
        {"economy_moves": [{"account": "国库", "delta": 1}]},
        section="economy_moves_rejections",
    )

    assert rows == []
