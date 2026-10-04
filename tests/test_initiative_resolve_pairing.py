"""#1847: free title/tag phrase pairing-warning admit deleted.

Callers still return `pairing_warnings: []` for a stable result shape.
Deletion of phrase helpers is covered by evidence/1847-mutation-probes.py
(N10_NO_PAIRING_PHRASE_ADMIT / N10_NO_PAIRING_DEAD_HELPERS), not pytest hasattr.
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
