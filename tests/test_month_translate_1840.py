"""#1840 monthly segment translation through the C0 declaration seam."""

from __future__ import annotations

import sqlite3

import pytest


def _character_name(db) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _army_id(db) -> str:
    row = db.conn.execute("SELECT id FROM armies ORDER BY id LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def test_pre_push_segment_translation_stages_declaration_without_world_writes(game):
    from ming_sim.month_translate import stage_month_segment

    db, state, _ = game
    person = _character_name(db)
    declaration = {
        "textual_facts": [{
            "subject_kind": "character", "subject_id": person, "body": "预推段事实",
        }],
    }
    calls = []

    def translate(prompt, llm_config):
        calls.append((prompt, llm_config))
        return declaration

    facts_before = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    ledger_before = db.conn.execute("SELECT COUNT(*) c FROM story_ledger_entries").fetchone()["c"]
    pending_before = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    staged_id = stage_month_segment(
        db,
        decree_ref="pre-push:1840",
        segment="完整预推段",
        turn=int(state.turn),
        translate_fn=translate,
    )

    assert staged_id > 0
    assert len(calls) == 1
    staged = db.staged_declarations.staged_for("pre-push:1840")
    assert len(staged) == 1
    assert staged[0].declaration["textual_facts"] == declaration["textual_facts"]
    assert db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    ) == facts_before
    assert db.conn.execute("SELECT COUNT(*) c FROM story_ledger_entries").fetchone()["c"] == ledger_before
    assert db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"] == pending_before

    from ming_sim.declaration_dispatch import discard_staged_declaration

    assert discard_staged_declaration(db, "pre-push:1840") == 1
    assert db.staged_declarations.staged_for("pre-push:1840") == ()
    assert db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    ) == facts_before


def test_world_segment_translates_once_and_persists_repeated_subject_facts_in_order(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    person, army = _character_name(db), _army_id(db)
    declaration = {
        "textual_facts": [
            {"subject_kind": "character", "subject_id": person, "body": "人物先记一事"},
            {"subject_kind": "character", "subject_id": person, "body": "人物再记一事"},
            {"subject_kind": "army", "subject_id": army, "body": "军队先记一事"},
            {"subject_kind": "army", "subject_id": army, "body": "军队再记一事"},
        ],
    }
    calls = []

    def translate(prompt, llm_config):
        calls.append((prompt, llm_config))
        return declaration

    dispatch_month_segment(
        db,
        state,
        segment="完整世界段",
        translate_fn=translate,
    )

    assert len(calls) == 1
    person_facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    army_facts = db.textual_facts.readable_materials(
        subject_kind="army", subject_id=army,
    )
    assert [fact.body for fact in person_facts] == ["人物先记一事", "人物再记一事"]
    assert [fact.body for fact in army_facts] == ["军队先记一事", "军队再记一事"]


def test_world_segment_failure_rolls_back_only_current_segment(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    person = _character_name(db)
    dispatch_month_segment(
        db,
        state,
        segment="前一段",
        translate_fn=lambda prompt, config: {
            "textual_facts": [{
                "subject_kind": "character", "subject_id": person, "body": "前一段已落",
            }],
        },
    )
    db.conn.execute(
        "CREATE TEMP TRIGGER fail_month_segment_fact "
        "BEFORE INSERT ON textual_facts WHEN NEW.body='阻断本段' "
        "BEGIN SELECT RAISE(ABORT, 'segment write failed'); END"
    )
    db.conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        dispatch_month_segment(
            db,
            state,
            segment="发生代码侧落账异常的当前段",
            translate_fn=lambda prompt, config: {
                "textual_facts": [
                    {"subject_kind": "character", "subject_id": person, "body": "本段先写"},
                    {"subject_kind": "character", "subject_id": person, "body": "阻断本段"},
                ],
            },
        )

    facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    assert [fact.body for fact in facts] == ["前一段已落"]
