"""ADR 0009 person archive contract index.

This slice does not implement the applier. It turns the accepted prose contract
into a small machine-readable index that later slices can consume.
"""

from __future__ import annotations


def test_person_archive_contract_index_exposes_canonical_terms_and_scenarios():
    """ADR 0009 terms are available as executable contract data."""
    from ming_sim.person_archive_contract import (
        PERSON_ACTIONS,
        PERSON_ALLEGIANCE_CHANGE_WAYS,
        PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS,
        PERSON_REASON_CODES,
        PERSON_STATUSES,
        PERSON_TITLE_KINDS,
        ACCEPTANCE_SCENARIOS,
    )

    assert PERSON_ACTIONS == ("任命", "罢黜", "调任", "处置", "易主", "册封", "行止")
    assert PERSON_STATUSES == (
        "active",
        "candidate",
        "offstage",
        "dismissed",
        "imprisoned",
        "exiled",
        "retired",
        "dead",
    )
    assert PERSON_REASON_CODES == (
        "被顶替",
        "获罪削籍",
        "致仕",
        "丁忧",
        "自请",
        "出宫",
        "陷虏",
        "落选",
        "历史卒",
        "登场",
        "未识别",
    )
    assert PERSON_TITLE_KINDS == ("职名分", "身名分", "无名分")
    assert PERSON_ALLEGIANCE_CHANGE_WAYS == ("主动投敌", "被俘而降", "主动归附")
    assert PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS == ("不明",)

    scenarios_by_id = {scenario["id"]: scenario for scenario in ACCEPTANCE_SCENARIOS}
    assert tuple(scenarios_by_id) == tuple(f"S{i}" for i in range(1, 16))
    assert scenarios_by_id["S1"]["requires"] == (
        "derived_from",
        "invariant:office_implies_active",
    )
    assert scenarios_by_id["S4"]["requires"] == ("reason_code:丁忧", "derive:夺情")
    assert scenarios_by_id["S7"]["requires"] == (
        "reason_code:陷虏",
        "apply",
        "blocks:任命",
        "reject:invalid_transition",
    )
    assert scenarios_by_id["S13"]["requires"] == (
        "reject:invalid_transition",
        "dead_no_outgoing_status",
    )
    assert scenarios_by_id["S15"]["actions"] == ("易主", "任命")


def test_person_transition_matrix_covers_all_status_action_pairs():
    """ADR 0009 transition matrix is complete and pins the hard edge cases."""
    from ming_sim.person_archive_contract import (
        PERSON_ACTIONS,
        PERSON_STATUSES,
        PERSON_TRANSITION_MATRIX,
    )

    assert set(PERSON_TRANSITION_MATRIX) == set(PERSON_STATUSES)
    for status in PERSON_STATUSES:
        assert set(PERSON_TRANSITION_MATRIX[status]) == set(PERSON_ACTIONS)

    assert PERSON_TRANSITION_MATRIX["imprisoned"]["任命"] == "derive:放归"
    assert PERSON_TRANSITION_MATRIX["exiled"]["任命"] == "derive:赦还"
    assert PERSON_TRANSITION_MATRIX["offstage"]["任命"] == "derive:起复"
    assert PERSON_TRANSITION_MATRIX["dismissed"]["任命"] == "derive:昭雪"
    assert all(
        outcome == "reject:invalid_transition"
        for outcome in PERSON_TRANSITION_MATRIX["dead"].values()
    )
    allowed_outcomes = {
        "apply",
        "normalize:任命",
        "normalize:调任",
        "derive:起复",
        "derive:昭雪",
        "derive:放归",
        "derive:赦还",
        "reject:invalid_transition",
    }
    assert {
        outcome
        for row in PERSON_TRANSITION_MATRIX.values()
        for outcome in row.values()
    } <= allowed_outcomes


def test_contract_index_cross_checks_references():
    """All contract index references point back to declared vocabularies."""
    from ming_sim.person_archive_contract import (
        ACCEPTANCE_SCENARIOS,
        PERSON_ACTIONS,
        PERSON_ALLEGIANCE_CHANGE_WAYS,
        PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS,
        PERSON_REASON_CODE_ALIASES,
        PERSON_REASON_CODES,
        PERSON_STATUSES,
        PERSON_TITLE_KINDS,
        PERSON_REASON_TRANSITION_OVERRIDES,
        PERSON_TITLE_KIND_TRANSITION_OVERRIDES,
    )

    assert set(PERSON_REASON_CODE_ALIASES.values()) <= set(PERSON_REASON_CODES)
    assert not (set(PERSON_ALLEGIANCE_CHANGE_WAYS) & set(PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS))
    for scenario in ACCEPTANCE_SCENARIOS:
        assert set(scenario["actions"]) <= set(PERSON_ACTIONS)
        for requirement in scenario["requires"]:
            if requirement.startswith("reason_code:"):
                assert requirement.removeprefix("reason_code:") in PERSON_REASON_CODES
            if requirement.startswith("方式:"):
                assert requirement.removeprefix("方式:") in PERSON_ALLEGIANCE_CHANGE_WAYS
            if requirement.startswith("legacy_方式:"):
                assert requirement.removeprefix("legacy_方式:") in (
                    PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS
                )
            if requirement.startswith("status:"):
                assert requirement.removeprefix("status:") in PERSON_STATUSES
            assert not requirement.startswith("derived:")
            if requirement.startswith(("derive:", "reject:", "normalize:")):
                prefix, _, detail = requirement.partition(":")
                assert prefix in {"derive", "reject", "normalize"}
                assert detail
        for transition_check in scenario.get("transition_checks", ()):
            status, action, reason_code, expected = transition_check
            assert status in PERSON_STATUSES
            assert action in PERSON_ACTIONS
            assert reason_code in PERSON_REASON_CODES
            assert expected in scenario["requires"]
    for _, _, reason_code in PERSON_REASON_TRANSITION_OVERRIDES:
        assert reason_code in PERSON_REASON_CODES
    for _, _, title_kind in PERSON_TITLE_KIND_TRANSITION_OVERRIDES:
        assert title_kind in PERSON_TITLE_KINDS


def test_person_transition_resolver_applies_reason_code_special_cases_first():
    """ADR 0009 reason_code rules override the default status matrix."""
    from ming_sim.person_archive_contract import resolve_person_transition

    assert resolve_person_transition("offstage", "任命", reason_code="丁忧") == "derive:夺情"
    assert resolve_person_transition("offstage", "任命", reason_code="守制") == "derive:夺情"
    # 5b r4（codex-a R1）：offstage 起复无论走 任命 还是 调任（无职名分时 调任 归一为任命），
    # 丁忧/守制 都应派生 夺情 审计标，不能漏（调任 变体此前落到 matrix normalize:任命）。
    assert resolve_person_transition("offstage", "调任", reason_code="丁忧") == "derive:夺情"
    assert resolve_person_transition("offstage", "调任", reason_code="守制") == "derive:夺情"
    assert resolve_person_transition("imprisoned", "任命", reason_code="陷虏") == (
        "reject:invalid_transition"
    )
    assert resolve_person_transition("imprisoned", "任命", reason_code="被俘") == (
        "reject:invalid_transition"
    )
    assert resolve_person_transition("imprisoned", "调任", reason_code="陷虏") == (
        "reject:invalid_transition"
    )
    assert resolve_person_transition("imprisoned", "易主", reason_code="陷虏") == "apply"
    assert resolve_person_transition("imprisoned", "任命") == "derive:放归"
    assert resolve_person_transition("active", "处置", reason_code="陷虏") == "apply"


def test_acceptance_scenario_transition_checks_match_resolver_outputs():
    """Scenario-level transition claims stay tied to executable contract rules."""
    from ming_sim.person_archive_contract import (
        ACCEPTANCE_SCENARIOS,
        resolve_person_transition,
    )

    for scenario in ACCEPTANCE_SCENARIOS:
        for status, action, reason_code, expected in scenario.get("transition_checks", ()):
            assert (
                resolve_person_transition(status, action, reason_code=reason_code) == expected
            ), scenario["id"]


def test_active_transition_normalization_depends_on_current_title_kind():
    """ADR 0009 separates active 职名分 from active 身名分."""
    from ming_sim.person_archive_contract import resolve_person_transition

    assert (
        resolve_person_transition("active", "任命", current_title_kind="职名分")
        == "normalize:调任"
    )
    assert (
        resolve_person_transition("active", "任命", current_title_kind="身名分") == "apply"
    )
    assert (
        resolve_person_transition("active", "任命", current_title_kind="听用候铨")
        == "apply"
    )
    assert (
        resolve_person_transition("active", "调任", current_title_kind="身名分")
        == "normalize:任命"
    )
    assert (
        resolve_person_transition("active", "调任", current_title_kind="无名分")
        == "normalize:任命"
    )
    assert (
        resolve_person_transition("active", "任命", current_title_kind="模型乱写的名分")
        == "normalize:调任"
    )


def test_reason_code_normalization_keeps_missing_distinct_from_unknown():
    """Unknown reason_code uses the sentinel; missing reason_code stays missing."""
    from ming_sim.person_archive_contract import normalize_reason_code

    assert normalize_reason_code(None) == ""
    assert normalize_reason_code("") == ""
    assert normalize_reason_code(" 丁忧 ") == "丁忧"
    assert normalize_reason_code("守制") == "丁忧"
    assert normalize_reason_code("丁艰") == "丁忧"
    assert normalize_reason_code("被俘") == "陷虏"
    assert normalize_reason_code("陷敌") == "陷虏"
    assert normalize_reason_code("模型乱写的缘由") == "未识别"
    assert normalize_reason_code("未识别") == "未识别"
