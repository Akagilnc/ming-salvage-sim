"""#1847: free title/tag phrase pairing-warning admit deleted.

Callers still return `pairing_warnings: []` for a stable result shape.
"""
from ming_sim import issues


def test_pairing_warnings_key_stays_empty_on_resolve(game):
    db, state, content = game
    out = issues.apply_issue_tracker_output(
        db,
        state,
        {
            "resolved_issues": [],
            "new_issues": [],
            "cancelled_issues": [],
            "advanced_issues": [],
        },
        content=content,
    )
    assert out.get("pairing_warnings") == []


def test_pairing_warning_helpers_deleted():
    assert not hasattr(issues, "_initiative_resolve_pairing_warnings")
    assert not hasattr(issues, "_emit_pairing_warnings")
    assert not hasattr(issues, "_MILITARY_RAISE_PHRASES")
    assert not hasattr(issues, "_FISCAL_RECURRING_PHRASES")
    assert not hasattr(issues, "_nonempty_list")
    assert not hasattr(issues, "_nonempty_dict")
    assert not hasattr(issues, "_has_economy_entry")
    assert not hasattr(issues, "_STRATEGIC_EVENT_OUTCOME_LABEL_ALIASES")
