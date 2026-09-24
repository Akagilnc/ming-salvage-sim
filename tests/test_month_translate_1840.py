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


def _region_id(db) -> str:
    row = db.conn.execute("SELECT id FROM regions ORDER BY id LIMIT 1").fetchone()
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
    decree_payload = {"action": "增设营堡", "region_id": "amur_frontier"}
    materialized_effects = {
        "new_armies": [{"id": "already-materialized-1840"}],
    }
    calls = []

    def translate(request, llm_config):
        calls.append((request, llm_config))
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
        decree_payload=decree_payload,
        materialized_effects=materialized_effects,
        translate_fn=translate,
    )

    assert staged_id > 0
    assert len(calls) == 1
    assert calls[0][0].decree_payload == decree_payload
    assert calls[0][0].materialized_effects == materialized_effects
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


def test_world_segment_applies_domain_effects_and_reports_rejected_effects(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    army, region = _army_id(db), _region_id(db)
    army_before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0]
    region_before = db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (region,),
    ).fetchone()[0]
    treasury_before = state.metrics["国库"]
    turn = int(state.turn)
    declaration = {
        "effects": {
            "army_delta": {
                army: {"origin_ref": "盘面自发", "morale": 2},
                "missing-army-1840": {"morale": 1},
            },
            "region_delta": {region: {"origin_ref": "盘面自发", "public_support": 2}},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "军需开支",
            }],
        },
    }

    result = dispatch_month_segment(
        db, state, segment="军队士气和地方民心变化，国库支出。",
        translate_fn=lambda request, config: declaration,
    )

    assert result.effects.applied
    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0] == army_before + 2
    assert db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (region,),
    ).fetchone()[0] == region_before + 2
    assert state.metrics["国库"] == treasury_before - 1
    rejection = db.conn.execute(
        "SELECT section, reason, category FROM rejection_reports "
        "WHERE turn=? ORDER BY id", (turn,),
    ).fetchall()
    assert any(row["section"] == "army_changes" and row["reason"] and
               row["category"] == "missing_ref" for row in rejection)
    effect_report = result.effects.applied[0]
    assert effect_report["army_changes"]
    assert effect_report["army_changes"][0]["new"] == army_before + 2
    assert effect_report["army_changes"][-1]["rejected"] is True
    assert effect_report["army_changes"][-1]["reason"]


def test_staged_month_declarations_settle_in_given_order_and_effects_are_idempotent(game):
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    from ming_sim.month_translate import stage_month_segment

    db, state, _ = game
    person, army = _character_name(db), _army_id(db)
    turn = int(state.turn)
    army_before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0]
    declarations = iter((
        {
            "textual_facts": [{
                "subject_kind": "character", "subject_id": person, "body": "早旨",
            }],
            "effects": {"army_delta": {
                army: {"origin_ref": "盘面自发", "morale": 1},
                "missing-army-order": {"morale": 1},
            }},
        },
        {
            "textual_facts": [{
                "subject_kind": "character", "subject_id": person, "body": "晚旨",
            }],
            "effects": {"army_delta": {
                army: {"origin_ref": "盘面自发", "morale": 2},
            }},
        },
    ))
    translate = lambda request, config: next(declarations)

    for ref in ("decree:early", "decree:late"):
        stage_month_segment(
            db, decree_ref=ref, segment="推演段", turn=turn,
            decree_payload={"decree_ref": ref}, materialized_effects={},
            translate_fn=translate,
        )

    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0] == army_before
    results = settle_staged_declarations_in_decree_order(
        db, state, ["decree:late", "decree:early"],
    )

    assert list(results) == ["decree:late", "decree:early"]
    assert [fact.body for fact in db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )] == ["晚旨", "早旨"]
    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0] == army_before + 3
    rejected = db.conn.execute(
        "SELECT section, reason, category FROM rejection_reports WHERE turn=?",
        (turn,),
    ).fetchall()
    assert [(row["section"], row["category"]) for row in rejected] == [
        ("army_changes", "missing_ref"),
    ]
    assert rejected[0]["reason"]
    early_effects = results["decree:early"].effects.applied[0]["army_changes"]
    assert early_effects[-1]["rejected"] is True
    assert early_effects[-1]["reason"]

    assert settle_staged_declarations_in_decree_order(
        db, state, ["decree:late", "decree:early"],
    ) == {}
    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0] == army_before + 3
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM rejection_reports WHERE turn=?", (turn,),
    ).fetchone()["c"] == 1


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
