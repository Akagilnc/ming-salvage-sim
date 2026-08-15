"""ADR 0009 person archive contract index.

This slice does not implement the applier. It turns the accepted prose contract
into a small machine-readable index that later slices can consume.
"""

from __future__ import annotations

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
