"""#1840 monthly segment translation through the C0 declaration seam."""

from __future__ import annotations

import sqlite3

import pytest

from tests.conftest import active_ming_character


@pytest.mark.parametrize("source_cannon,target_cannon,treasury,actual_cannon,source_latched,target_latched", [
    (1, 0, 10, 1, 0, 0), (5, 11, 10, 1, 0, 0), (0, 0, 0, 0, 0, 0),
    (5, 0, 10, 0, 1, 0), (5, 0, 10, 0, 0, 1),
])
def test_world_segment_explicit_stock_transfers_share_actual_amount(
    game, source_cannon, target_cannon, treasury, actual_cannon, source_latched, target_latched,
):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    armies = [row[0] for row in db.conn.execute("SELECT id FROM armies ORDER BY id LIMIT 2")]
    assert len(armies) == 2
    loser, winner = armies
    db.conn.execute("UPDATE armies SET cannon_equipment=?, is_mutinied=? WHERE id=?",
                    (source_cannon, source_latched, loser))
    db.conn.execute("UPDATE armies SET cannon_equipment=?, is_mutinied=? WHERE id=?",
                    (target_cannon, target_latched, winner))
    state.metrics["国库"], state.metrics["内库"] = treasury, 0
    declaration = {"effects": {
        "economy_moves": [{
            "origin_ref": "盘面自发", "account": "国库", "transfer_to": "内库",
            "delta": -100, "category": "转库", "reason": "调拨",
        }],
        "army_delta": {loser: {
            "origin_ref": "盘面自发", "随军大炮": -100,
            "cannon_transfer_to": winner, "reason": "缴获",
        }},
    }}
    result = dispatch_month_segment(
        db, state, segment="调拨和缴获", translate_fn=lambda request, config: declaration,
    )
    effects = result.effects.applied[0]
    assert [move["delta"] for move in effects["economy_moves"]] == [-treasury, treasury]
    assert (state.metrics["国库"], state.metrics["内库"]) == (0, treasury)
    rows = db.conn.execute(
        "SELECT account, delta FROM economy_ledger WHERE category='转库' ORDER BY id"
    ).fetchall()
    assert [(row["account"], row["delta"]) for row in rows] == (
        [("国库", -10), ("内库", 10)] if treasury else []
    )
    cannon = db.conn.execute(
        "SELECT id, cannon_equipment FROM armies WHERE id IN (?, ?) ORDER BY id", (loser, winner)
    ).fetchall()
    assert {row["id"]: row["cannon_equipment"] for row in cannon} == {
        loser: source_cannon - actual_cannon, winner: target_cannon + actual_cannon,
    }
    assert sorted(change["delta"] for change in effects["army_changes"]
                  if change.get("field") == "cannon_equipment") == [
                      -actual_cannon, actual_cannon,
                  ]
    logs = db.conn.execute(
        "SELECT army_id, delta FROM army_logs WHERE field='cannon_equipment' AND army_id IN (?, ?)",
        (loser, winner),
    ).fetchall()
    assert sorted(row["delta"] for row in logs) == (
        [-actual_cannon, actual_cannon] if actual_cannon else []
    )


def test_world_segment_rejects_transfer_with_pay_arrears_claim(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    db.conn.execute("UPDATE armies SET arrears=6 WHERE id='jingying'")
    state.metrics["国库"], state.metrics["内库"] = 100, 0
    move = {
        "origin_ref": "盘面自发", "account": "国库", "delta": -5,
        "transfer_to": "内库", "category": "调拨", "reason": "反例",
        "purpose": "补饷", "target_kind": "army", "target_id": "jingying",
    }
    result = dispatch_month_segment(
        db, state, segment="矛盾钱库声明",
        translate_fn=lambda request, config: {"effects": {"economy_moves": [move]}},
    )

    assert result.effects.applied[0]["economy_moves"] == []
    assert len(result.effects.applied[0]["economy_moves_rejections"]) == 1
    rejected = result.effects.applied[0]["economy_moves_rejections"][0]
    assert rejected["account"] == "国库"
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert rejected["item"] == move
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='economy_moves_rejections' AND category='invalid_enum'"
    ).fetchone()[0] == 1
    assert (state.metrics["国库"], state.metrics["内库"]) == (100, 0)
    assert db.conn.execute("SELECT arrears FROM armies WHERE id='jingying'").fetchone()[0] == 6
    assert db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE category='调拨'").fetchone()[0] == 0


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
    decree_payload = {
        "appointment": {
            "name": person, "office": "兵部尚书", "appoint_action": "任命",
        },
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
        translate_fn=translate,
    )

    assert staged_id > 0
    assert len(calls) == 1
    assert calls[0][0].decree_payload == decree_payload
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

    db, state, content = game
    army_row = db.conn.execute(
        "SELECT id, manpower FROM armies WHERE manpower > 0 ORDER BY id LIMIT 1"
    ).fetchone()
    assert army_row is not None
    army, manpower_before = str(army_row["id"]), int(army_row["manpower"])
    region = _region_id(db)
    person = active_ming_character(db, content)
    old_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (person,),
    ).fetchone()["office"]
    new_office = "陕西总督" if old_office != "陕西总督" else "陕西巡抚"
    army_before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0]
    region_before = db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (region,),
    ).fetchone()[0]
    farmer_before = int(db.conn.execute(
        "SELECT population FROM classes WHERE name='农民' AND region_id='shaanxi'"
    ).fetchone()[0])
    displaced_before = int(db.conn.execute(
        "SELECT population FROM classes WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()[0])
    treasury_before = state.metrics["国库"]
    economy_ledger_count = int(db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger"
    ).fetchone()[0])
    turn = int(state.turn)
    declaration = {
        "effects": {
            "army_delta": {
                army: {
                    "origin_ref": "盘面自发", "morale": 2,
                    "manpower": -(manpower_before + 100),
                },
                "missing-army-1840": {"morale": 1},
            },
            "region_delta": {region: {"origin_ref": "盘面自发", "public_support": 2}},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库",
                "delta": -(treasury_before + 100),
                "category": "超额拨出", "reason": "超过国库现银的拨出",
            }, {
                "origin_ref": "盘面自发", "account": "国库", "delta": 7,
                "category": "一次性进账", "reason": "抄没人物家产",
            }],
            "population_transfers": [{
                "origin_ref": "盘面自发",
                "source": "农民@shaanxi", "target": "流民@shaanxi",
                "amount": farmer_before + 100, "reason": "灾害",
            }, {
                "origin_ref": "盘面自发",
                "source": "农民@shaanxi", "target": "流民@shaanxi",
                "amount": 1, "reason": "灾害",
            }],
            "人物变更": [{
                "origin_ref": "盘面自发", "name": person, "动作": "任命",
                "office": new_office, "office_type": "地方",
                "region_id": "shaanxi", "reason": "世界段任命",
            }],
        },
    }

    result = dispatch_month_segment(
        db, state, segment="军队士气和地方民心变化，国库支出。",
        translate_fn=lambda request, config: declaration,
    )

    assert result.effects.applied
    person_change = result.effects.applied[0]["applied_person_changes"][0]
    assert not person_change.get("rejected", False)
    assert person_change["new_office"] == new_office
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (person,),
    ).fetchone()["office"] == new_office
    assert db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army,),
    ).fetchone()[0] == army_before + 2
    assert db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (region,),
    ).fetchone()[0] == region_before + 2
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
    economy_deltas = [move["delta"] for move in effect_report["economy_moves"]]
    assert economy_deltas[0] == -treasury_before
    # A personal-wealth proposal has no source ledger; keep the existing
    # one-off treasury income path (income modifiers may change 7 to 6).
    assert economy_deltas[1] > 0
    ledger_deltas = [row["delta"] for row in db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE id > ? ORDER BY id",
        (economy_ledger_count,),
    ).fetchall()]
    assert ledger_deltas == economy_deltas
    assert state.metrics["国库"] == treasury_before + sum(ledger_deltas)
    manpower_change = next(
        change for change in effect_report["army_changes"]
        if change.get("field") == "manpower"
    )
    assert manpower_change["old"] == manpower_before
    assert manpower_change["new"] == 0
    assert manpower_change["delta"] == -manpower_before
    assert not effect_report["population_transfers_rejections"]
    transfer, depleted_transfer = effect_report["population_transfers"]
    assert transfer["amount"] == farmer_before
    assert depleted_transfer["amount"] == 0
    assert not depleted_transfer.get("rejected", False)
    assert db.conn.execute(
        "SELECT population FROM classes WHERE name='农民' AND region_id='shaanxi'"
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT population FROM classes WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()[0] == displaced_before + farmer_before


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
            decree_payload={"decree_ref": ref},
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
