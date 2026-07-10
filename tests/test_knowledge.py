"""Per-character knowledge projection tests (#489)."""

from __future__ import annotations

import pytest

from ming_sim.knowledge import build_character_knowledge


@pytest.mark.parametrize(
    ("target_kind", "expected_visible"),
    [
        ("none", True),
        ("unrelated-office", True),
        ("office-type", False),
        ("office-name", False),
    ],
    ids=["no-exclusion", "unrelated-office", "matching-office-type", "matching-office-name"],
)
def test_knowledge_exclusion_reads_current_office_without_nameerror(
    game, monkeypatch, target_kind, expected_visible
):
    db, state, content = game
    name, character = next(
        (name, character)
        for name, character in content.characters.items()
        if character.office_type == "户部"
    )
    row = {
        "turn": state.turn,
        "year": state.year,
        "period": state.period,
        "kind": "secret",
        "title": "密令",
        "body": "不可忽略的密令",
        "source_id": "test:office-exclusion",
        "excluded_names": "[]",
    }
    excluded_office = {
        "none": [],
        "unrelated-office": ["不相干职位"],
        "office-type": [character.office_type],
        "office-name": [character.office],
    }[target_kind]
    targets = {"people": [], "offices": excluded_office}

    def events(character_name, *, include_exclusions=False):
        return [row] if character_name == name else []

    monkeypatch.setattr(db, "_character_knowledge_events", events)
    monkeypatch.setattr(db, "list_issued_directives", lambda: [])
    monkeypatch.setattr(db, "list_turn_reports", lambda: [])
    monkeypatch.setattr(db, "knowledge_exclusion_targets_for_source", lambda _: targets)

    knowledge = build_character_knowledge(db, state, name)

    assert (knowledge["events"] != []) is expected_visible
    if expected_visible:
        assert knowledge["events"][0]["body"] == "不可忽略的密令"
    else:
        assert knowledge["events"] == []
