from __future__ import annotations
from tests.conftest import stub_month_translate
import sqlite3
import pytest
from ming_sim.settlement.views import section, view
from tests.conftest import active_ming_character
from tests.test_declaration_dispatch_1835 import _minister as _character_name
"""#1840 monthly segment translation through the C0 declaration seam."""






@pytest.mark.parametrize("route,source_cannon,target_cannon,treasury,actual_cannon,source_latched,target_latched", [
    ("direct", 1, 0, 10, 1, 0, 0),
    ("direct", 5, 11, 10, 1, 0, 0),
    ("direct", 0, 0, 0, 0, 0, 0),
    ("direct", 5, 0, 10, 0, 1, 0),
    ("direct", 5, 0, 10, 0, 0, 1),
    ("resolved", 1, 0, 10, 1, 0, 0),
    ("failed", 1, 0, 10, 1, 0, 0),
    ("ongoing", 1, 0, 10, 1, 0, 0),
])
def test_world_segment_explicit_stock_transfers_share_actual_amount(
    game, route, source_cannon, target_cannon, treasury, actual_cannon, source_latched, target_latched, monkeypatch,
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
    origin = "盘面自发"
    if route != "direct":
        dossier_id = db.create_decree_dossier(
            state, action_type="policy", decree_text="调炮", target_kind="issue", target_id="test",
        )
        db.dossiers.record_dossier_decision(dossier_id, "promulgated")
        origin = f"dossier:{dossier_id}"
        army_effect = {"army_delta": declaration["effects"].pop("army_delta")}
        # Nested consequences inherit the authorized parent, not a child claim.
        army_effect["army_delta"][loser]["origin_ref"] = "fabricated:9"
        issue_id = db.insert_issue(
            state, kind="situation", title="调炮", origin_ref=origin,
            ongoing_effects=army_effect if route == "ongoing" else {},
            effect_on_fail=army_effect if route == "failed" else {},
        )
        if route != "ongoing":
            declaration["effects"]["close_issues"] = [{
                "issue_id": issue_id, "reason": route,
                f"effect_on_{'resolve' if route == 'resolved' else 'fail'}": army_effect,
            }]
    stub_month_translate(monkeypatch, lambda request, config: declaration)
    result = dispatch_month_segment(db, state, segment="调拨和缴获")
    if route == "ongoing":
        from ming_sim.situation_drift import apply_situation_monthly_drift
        assert apply_situation_monthly_drift(db, state) == []
    elif route != "direct":
        assert db.issues.row(issue_id)["status"] == route
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 0
    effects = result.effects.applied[0]
    assert [move["delta"] for move in view(effects, "economy_moves")] == [-treasury, treasury]
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
    if route == "direct":
        assert sorted(change["delta"] for change in view(effects, "army_changes")
                      if change.get("field") == "cannon_equipment") == [
                          -actual_cannon, actual_cannon,
                      ]
    logs = db.conn.execute(
        "SELECT army_id, delta, origin_ref FROM army_logs WHERE field='cannon_equipment' AND army_id IN (?, ?)",
        (loser, winner),
    ).fetchall()
    assert sorted(row["delta"] for row in logs) == (
        [-actual_cannon, actual_cannon] if actual_cannon else []
    )
    assert all(row["origin_ref"] == origin for row in logs)


@pytest.mark.parametrize("route,field,bad_value,level", [
    ("resolved", "cannon_transfer", "bad", "item"),
    ("resolved", "army_delta", "bad", "item"),
    ("resolved", "region_delta", "bad", "item"),
    ("resolved", "army_delta", None, "section"),
    ("resolved", "region_delta", "bad", "section"),
    ("failed", "region_delta", None, "section"),
    ("failed", "metrics", "bad", "section"),
    ("cancels", "metrics", None, "section"),
    ("cancels", "army_delta", "bad", "section"),
    ("new_resolved", "army_delta", None, "section"),
    ("new_resolved", "region_delta", "bad", "section"),
    ("new_failed", "region_delta", None, "section"),
    ("new_failed", "metrics", "bad", "section"),
])
def test_world_segment_nested_entity_effects_reject_bad_items(game, route, field, bad_value, level, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment
    import json

    db, state, _ = game
    loser, winner = [row[0] for row in db.conn.execute("SELECT id FROM armies ORDER BY id LIMIT 2")]
    db.conn.execute("UPDATE armies SET cannon_equipment=1, is_mutinied=0 WHERE id=?", (loser,))
    db.conn.execute("UPDATE armies SET cannon_equipment=0, is_mutinied=0 WHERE id=?", (winner,))
    cannon_before = [tuple(row) for row in db.conn.execute(
        "SELECT id, cannon_equipment FROM armies WHERE id IN (?, ?) ORDER BY id", (loser, winner),
    )]
    logs_before = db.conn.execute("SELECT COUNT(*) FROM army_logs WHERE field='cannon_equipment'").fetchone()[0]
    manpower_before = db.armies.row(winner)["manpower"]
    bad_region, good_region = [row[0] for row in db.conn.execute("SELECT id FROM regions ORDER BY id LIMIT 2")]
    db.conn.execute("UPDATE regions SET unrest=10 WHERE id=?", (good_region,))
    bad_region_before = dict(db.regions.row(bad_region))
    state.metrics["民心"] = 50
    metric_before = state.metrics["民心"]
    legal = {
        "army_delta": {winner: {"manpower": 1}},
        "region_delta": {good_region: {"unrest": 1}},
        "metrics": {"民心": 3},
    }
    effect = dict(legal)
    if field == "cannon_transfer":
        bad_changes = {"随军大炮": bad_value, "cannon_transfer_to": winner}
        effect["army_delta"] = {**effect["army_delta"], loser: bad_changes}
        expected_rejections = [("invalid_enum", {"army_id": loser, "changes": bad_changes}, "system_simulation")]
    elif level == "section":
        effect[field] = bad_value
        expected_rejections = [
            ("invalid_shape", {"field": field, "raw_value": bad_value}, "system_simulation")
        ]
    else:
        bad_id = loser if field == "army_delta" else bad_region
        bad_items = {bad_id: bad_value, "unregistered_entity": bad_value}
        effect[field] = {**bad_items, **effect[field]}
        expected_rejections = [
            ("invalid_shape", {"field": field, "id": entity_id, "value": value}, "system_simulation")
            for entity_id, value in bad_items.items()
        ]
    fresh_issue = route in ("new_resolved", "new_failed")
    terminal_route = route.removeprefix("new_")
    effect_field = f"effect_on_{'resolve' if terminal_route == 'resolved' else 'fail'}"
    creation_rejected = []
    if fresh_issue:
        dossier_id = db.create_decree_dossier(
            state, action_type="policy", decree_text="调炮", target_kind="issue", target_id="test",
        )
        db.dossiers.record_dossier_decision(dossier_id, "promulgated")
        stub_month_translate(monkeypatch, lambda request, config: {"effects": {
            "new_issues": [{
                "origin_kind": "decree", "origin_ref": f"dossier:{dossier_id}",
                "kind": "situation", "title": "调炮", effect_field: effect,
            }],
        }})
        created = dispatch_month_segment(db, state, segment="立项")
        creation = section(created.effects.applied[0], "issue_summary")
        issue_id = creation.new_issues[0]["issue_id"]
        creation_rejected = creation.rejected
    # Close + section: seed same-named preset so rejected fresh section keeps preset work.
    elif route == "cancels":
        issue_kwargs = {"cancellable": "decree"}
    elif level == "section":
        issue_kwargs = {
            "effect_on_resolve": legal if route == "resolved" else {},
            "effect_on_fail": legal if route == "failed" else {},
        }
    else:
        issue_kwargs = {"effect_on_fail": effect if route == "failed" else {}}
    if not fresh_issue:
        issue_id = db.insert_issue(state, kind="situation", title="调炮", **issue_kwargs)
    if route == "cancels":
        declaration = {"effects": {
            "cancels": [{"issue_id": issue_id, "narrative": "撤回", "applied_cost": effect}],
        }}
        expected_status = "dropped"
    else:
        declaration = {"effects": {
            "close_issues": [{
                "issue_id": issue_id, "reason": terminal_route,
                **({} if fresh_issue else {effect_field: effect}),
            }],
        }}
        expected_status = terminal_route
    if fresh_issue:
        declaration["effects"]["army_delta"] = {winner: {"origin_ref": "盘面自发", "manpower": 2}}
    stub_month_translate(monkeypatch, lambda request, config: declaration)
    result = dispatch_month_segment(db, state, segment="调炮")
    rejected = section(result.effects.applied[0], "issue_summary").rejected
    if fresh_issue:
        assert rejected == []
        rejected = creation_rejected
        assert json.loads(db.issues.row(issue_id)[effect_field]) == {
            key: value for key, value in legal.items() if key != field
        }
    assert [(item.category, item.item, item.source.value) for item in rejected] == expected_rejections
    reports = db.conn.execute("SELECT category, item_json, source FROM rejection_reports").fetchall()
    assert [(row["category"], json.loads(row["item_json"]), row["source"]) for row in reports] == expected_rejections
    assert [tuple(row) for row in db.conn.execute(
        "SELECT id, cannon_equipment FROM armies WHERE id IN (?, ?) ORDER BY id", (loser, winner),
    )] == cannon_before
    assert db.conn.execute("SELECT COUNT(*) FROM army_logs WHERE field='cannon_equipment'").fetchone()[0] == logs_before
    drop_section = level == "section" and (route == "cancels" or fresh_issue)
    expect_manpower = manpower_before + (2 if fresh_issue else 0) + (
        0 if drop_section and field == "army_delta" else 1
    )
    expect_unrest = 10 if drop_section and field == "region_delta" else 11
    # Section-level bad fresh keeps same-named preset; cancels/new have no preset to keep.
    expect_metric = metric_before + (
        0 if drop_section and field == "metrics" else 3
    )
    assert db.armies.row(winner)["manpower"] == expect_manpower
    assert dict(db.regions.row(bad_region)) == bad_region_before
    assert db.regions.row(good_region)["unrest"] == expect_unrest
    assert state.metrics["民心"] == expect_metric
    assert db.issues.row(issue_id)["status"] == expected_status


def test_world_segment_rejects_transfer_with_pay_arrears_claim(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    db.conn.execute("UPDATE armies SET  province_pay_arrears=0, central_pay_arrears=6 WHERE id='jingying'")
    state.metrics["国库"], state.metrics["内库"] = 100, 0
    move = {
        "origin_ref": "盘面自发", "account": "国库", "delta": -5,
        "transfer_to": "内库", "category": "调拨", "reason": "反例",
        "purpose": "补饷", "target_kind": "army", "target_id": "jingying",
    }
    stub_month_translate(monkeypatch, lambda request, config: {"effects": {"economy_moves": [move]}})
    result = dispatch_month_segment(db, state, segment="矛盾钱库声明")

    outcome = result.effects.applied[0]
    assert view(outcome, "economy_moves") == []
    rejected = section(outcome, "economy_moves").rejected
    assert len(rejected) == 1
    assert rejected[0].category == "invalid_enum"
    assert rejected[0].item == move
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='economy_moves' AND category='invalid_enum'"
    ).fetchone()[0] == 1
    assert (state.metrics["国库"], state.metrics["内库"]) == (100, 0)
    assert db.conn.execute("SELECT arrears FROM armies WHERE id='jingying'").fetchone()[0] == 6
    assert db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE category='调拨'").fetchone()[0] == 0


def _army_id(db) -> str:
    row = db.conn.execute("SELECT id FROM armies ORDER BY id LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def _region_id(db) -> str:
    row = db.conn.execute("SELECT id FROM regions ORDER BY id LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])




def test_world_segment_translates_once_and_persists_repeated_subject_facts_in_order(game, monkeypatch):
    from ming_sim import month_translate

    db, state, _ = game
    person, army = _character_name(db), _army_id(db)
    declaration = {
        "textual_facts": [
            {"subject_kind": "character", "subject_id": person, "body": "  人物先记一事\n据奏尚在京畿。  "},
            {"subject_kind": "character", "subject_id": person, "body": "人物再记一事"},
            {"subject_kind": "army", "subject_id": army, "body": "军队先记一事"},
            {"subject_kind": "army", "subject_id": army, "body": "军队再记一事"},
        ],
    }
    calls = []

    def translate(prompt, llm_config, **kwargs):
        calls.append((prompt, llm_config, kwargs))
        return declaration

    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", translate)
    month_translate.dispatch_month_segment(
        db,
        state,
        segment="完整世界段",
    )

    assert len(calls) == 1
    prompt, _, options = calls[0]
    # Compare the delivered input to its live source, not to frozen wording.
    guidance = month_translate.describe_month_effect_fields()
    assert guidance and guidance in prompt
    assert options["tag"] == "month_segment_translate"
    person_facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    army_facts = db.textual_facts.readable_materials(
        subject_kind="army", subject_id=army,
    )
    assert [fact.body for fact in person_facts] == [
        fact["body"] for fact in declaration["textual_facts"] if fact["subject_kind"] == "character"
    ]
    assert [fact.body for fact in army_facts] == [
        fact["body"] for fact in declaration["textual_facts"] if fact["subject_kind"] == "army"
    ]


def test_world_segment_applies_domain_effects_and_reports_rejected_effects(game, monkeypatch):
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

    stub_month_translate(monkeypatch, lambda request, config: declaration)
    result = dispatch_month_segment(db, state, segment="军队士气和地方民心变化，国库支出。")

    assert result.effects.applied
    person_change = view(result.effects.applied[0], "applied_person_changes")[0]
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
    army_rows = view(effect_report, "army_changes")
    assert army_rows
    assert army_rows[0]["new"] == army_before + 2
    assert section(effect_report, "army_changes").rejected[-1].reason
    economy_deltas = [move["delta"] for move in view(effect_report, "economy_moves")]
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
        change for change in view(effect_report, "army_changes")
        if change.get("field") == "manpower"
    )
    assert manpower_change["old"] == manpower_before
    assert manpower_change["new"] == 0
    assert manpower_change["delta"] == -manpower_before
    assert not section(effect_report, "population_transfers").rejected
    transfer, depleted_transfer = view(effect_report, "population_transfers")
    assert transfer["amount"] == farmer_before
    assert depleted_transfer["amount"] == 0
    assert db.conn.execute(
        "SELECT population FROM classes WHERE name='农民' AND region_id='shaanxi'"
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT population FROM classes WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()[0] == displaced_before + farmer_before




def test_world_segment_failure_rolls_back_only_current_segment(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    person = _character_name(db)
    stub_month_translate(monkeypatch, lambda prompt, config: {
        "textual_facts": [{
            "subject_kind": "character", "subject_id": person, "body": "前一段已落",
        }],
    })
    dispatch_month_segment(db, state, segment="前一段")
    db.conn.execute(
        "CREATE TEMP TRIGGER fail_month_segment_fact "
        "BEFORE INSERT ON textual_facts WHEN NEW.body='阻断本段' "
        "BEGIN SELECT RAISE(ABORT, 'segment write failed'); END"
    )
    db.conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        stub_month_translate(monkeypatch, lambda prompt, config: {
            "textual_facts": [
                {"subject_kind": "character", "subject_id": person, "body": "本段先写"},
                {"subject_kind": "character", "subject_id": person, "body": "阻断本段"},
            ],
        })
        dispatch_month_segment(db, state, segment="发生代码侧落账异常的当前段")

    facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    assert [fact.body for fact in facts] == ["前一段已落"]


def test_world_segment_effects_use_frozen_visible_affairs(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    visible = db.affairs.open(name="可见事务", origin="世界段", year=state.year,
                              period=state.period, turn=state.turn)
    hidden = db.affairs.open(name="不可见事务", origin="未供料", year=state.year,
                             period=state.period, turn=state.turn)
    db.conn.execute(
        "UPDATE affairs SET status='closed', closed_turn=? WHERE id=?",
        (state.turn, hidden.id),
    )
    db.conn.commit()
    before = state.metrics["国库"]
    # 真实入口供料只含未了事务；已了结事务不在本批输入。
    stub_month_translate(monkeypatch, lambda request, config: {"effects": {"economy_moves": [
        {"origin_ref": f"affair:{visible.id}", "account": "国库", "delta": -1,
         "category": "过月支出", "reason": "合法支出"},
        {"origin_ref": f"affair:{hidden.id}", "account": "国库", "delta": -1,
         "category": "过月支出", "reason": "越权支出"},
    ]}})
    result = dispatch_month_segment(db, state, segment="两笔事务回指")
    assert state.metrics["国库"] == before - 1
    assert result.effects.applied
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='invalid_enum'"
    ).fetchone()[0] >= 1






def test_world_segment_repeated_entity_effects_apply_in_order(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment
    from tests.test_refugee_loop_652 import _pop, _recovery_grant

    db, state, _ = game
    army = _army_id(db)
    region = _region_id(db)
    _recovery_grant(db, state, amount=1)
    refugees_before = _pop(db, "流民", "shaanxi")
    affairs_before = db.conn.execute("SELECT COUNT(*) FROM affairs").fetchone()[0]
    db.conn.execute("UPDATE armies SET morale=58 WHERE id=?", (army,))
    db.conn.execute("UPDATE regions SET public_support=38 WHERE id=?", (region,))
    db.conn.commit()
    stub_month_translate(monkeypatch, lambda r, c: {
        "effects": [
            {"new_issues": None,
             "army_delta": {army: {"origin_ref": "盘面自发", "morale": 90}},
             "region_delta": {region: {"origin_ref": "盘面自发", "public_support": 2}},
             "economy_moves": [{"account": "国库", "delta": -1, "category": "过月支出",
                                "reason": "第一笔", "affair_declaration": {
                                    "attach": "new", "identity": "同段一事", "name": "同段一事", "origin": "世界段"}}]},
            {"army_delta": {army: {"origin_ref": "盘面自发", "morale": -30}},
             "region_delta": {region: {"origin_ref": "盘面自发", "public_support": -1}},
             "economy_moves": [{"account": "国库", "delta": -1, "category": "过月支出",
                                "reason": "第二笔", "affair_declaration": {
                                    "attach": "new", "identity": "同段一事", "name": "同段一事", "origin": "世界段"}}]},
        ],
    })
    dispatch_month_segment(db, state, segment="先振奋后受挫")
    assert db.conn.execute("SELECT morale FROM armies WHERE id=?", (army,)).fetchone()[0] == 70
    assert db.conn.execute("SELECT public_support FROM regions WHERE id=?", (region,)).fetchone()[0] == 39
    assert db.conn.execute("SELECT COUNT(*) FROM affairs").fetchone()[0] == affairs_before + 1
    refs = db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE reason IN ('第一笔', '第二笔')"
    ).fetchall()
    assert len(refs) == 2
    assert refs[0][0] == refs[1][0]
    # #652：世界段不回流；仅邸报后月份推进会扣池。
    assert _pop(db, "流民", "shaanxi") == refugees_before


@pytest.mark.parametrize(
    ("initial_pressure", "first_pressure", "second_pressure", "second_morale", "second_reason", "second_army_event", "triggered", "pressure", "morale", "first_reason"),
    [(20, 35, -5, -3, "己巳之变再挫", True, True, 50, 55, "己巳之变敌逼京畿"),
     (20, "非法增量", -5, -3, "己巳之变再挫", True, False, 20, 50, "己巳之变敌逼京畿"),
     (100, -10, 5, -3, "己巳之变再挫", True, True, 95, 55, "己巳之变敌逼京畿"),
     (90, 10, 5, -3, "己巳之变再挫", True, False, 90, 50, "己巳之变敌逼京畿"),
     (20, 35, -5, 5, "己巳之变后京营平日操练", False, True, 50, 63, "己巳之变敌逼京畿"),
     (20, "非法增量", -5, 5, "己巳之变后京营平日操练", False, False, 20, 55, "己巳之变敌逼京畿"),
     (20, 35, None, None, "", False, False, 55, 50, None)],
)
def test_world_segment_repeated_strategic_results_apply_in_order(
    game, initial_pressure, first_pressure, second_pressure, second_morale, second_reason, second_army_event,
    triggered, pressure, morale, first_reason, monkeypatch,
):
    from ming_sim.month_translate import dispatch_month_segment
    from tests.test_refugee_loop_652 import _pop

    db, state, _ = game
    state.year, state.period = 1629, 11
    db.conn.execute("UPDATE regions SET military_pressure=? WHERE id='beizhili'", (initial_pressure,))
    db.conn.execute("UPDATE armies SET morale=50 WHERE id='jingying'")
    db.conn.commit()
    if first_pressure == 35 and second_pressure == -5:
        # Event-owned effects may land after independent effects; do not lock
        # their unprotected relative order at the metric cap (#1873).
        state.metrics["民心"] = 90
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    farmers_before = _pop(db, "农民", "shaanxi")
    refugees_before = _pop(db, "流民", "shaanxi")
    faction = db.conn.execute("SELECT name, satisfaction FROM factions ORDER BY name LIMIT 1").fetchone()
    social_class = db.conn.execute("SELECT name, satisfaction FROM classes ORDER BY name LIMIT 1").fetchone()
    first_region = {"origin_ref": "盘面自发", "military_pressure": first_pressure}
    if first_reason is not None:
        first_region["reason"] = first_reason
    first_effect = {
        "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
        "事件结局": {"jisi_lubian": "入塞被遏"},
        "region_delta": {"beizhili": first_region},
    }
    if first_reason is not None:
        first_effect["event_id"] = "jisi_lubian"
        if first_pressure in (35, 10, "非法增量"):
            first_effect.update({
                "metric_delta": {"民心": -10 if metric_before == 90 else -2},
                "economy_moves": [{"origin_ref": "盘面自发", "account": "国库", "delta": -1,
                                   "category": "过月支出", "reason": "被拒战果军需"}],
                "faction_delta": {faction["name"]: {"satisfaction": -2}},
                "class_delta": {social_class["name"]: {"satisfaction": -2}},
                "population_transfers": [{"origin_ref": "盘面自发", "source": "农民@shaanxi",
                                          "target": "流民@shaanxi", "amount": 300, "reason": "灾害"}],
            })
        first_effect["army_delta"] = {"jingying": {
            "origin_ref": "盘面自发", "morale": 8, "reason": "己巳之变勤王振奋",
        }}
        first_effect["new_armies"] = [{
            "origin_ref": "盘面自发", "id": "jisi_declared_1840",
            "name": "己巳战果新军", "owner_power": "houjin",
            "station": "北直隶 / 遵化", "manpower": 1200,
        }]
        first_effect["人物变更"] = [{
            "origin_ref": "盘面自发", "name": "毛文龙", "动作": "处置",
            "status": "dismissed", "reason": "己巳之变后革职",
        }]
    effects = [first_effect]
    if second_pressure is not None:
        effects.append(
            {"event_id": "jisi_lubian", "region_delta": {"beizhili": {
                "origin_ref": "盘面自发", "military_pressure": second_pressure,
                "reason": "己巳之变稍退"}}})
        army_effect = {"army_delta": {"jingying": {
            "origin_ref": "盘面自发", "morale": second_morale,
            "reason": second_reason}}}
        if second_army_event:
            army_effect["event_id"] = "jisi_lubian"
        effects.append(army_effect)
    if first_reason is not None:
        effects.append({"new_armies": [{
            "origin_ref": "盘面自发", "id": "jisi_independent_1840",
            "name": "独立新军", "owner_power": "houjin",
            "station": "北直隶 / 遵化", "manpower": 1200,
            "reason": "己巳之变后另行成军",
        }]})
        effects.append({"人物变更": [{
            "origin_ref": "盘面自发", "name": "孙传庭", "动作": "处置",
            "status": "dismissed", "reason": "己巳之变后另案革职",
        }]})
    if first_pressure == "非法增量" and first_reason is not None:
        effects.append({"metric_delta": {"民心": 1}})
    elif metric_before == 90:
        effects.append({"metric_delta": {"民心": 5}})
    stub_month_translate(monkeypatch, lambda r, c: {"effects": effects})
    dispatch_month_segment(db, state, segment="己巳之变两笔战果")
    assert db.issues.has_event_terminal_state('jisi_lubian', "triggered") is triggered
    assert db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0] == pressure
    assert db.conn.execute("SELECT morale FROM armies WHERE id='jingying'").fetchone()[0] == morale
    if first_pressure in (35, 10, "非法增量") and first_reason is not None:
        declared_delta = (-10 if metric_before == 90 else -2) if triggered else 0
        independent_delta = 5 if metric_before == 90 else (1 if first_pressure == "非法增量" else 0)
        assert state.metrics["民心"] == metric_before + declared_delta + independent_delta
        assert state.metrics["国库"] == treasury_before + (-1 if triggered else 0)
        assert db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE reason='被拒战果军需'").fetchone()[0] == int(triggered)
        assert db.conn.execute("SELECT satisfaction FROM factions WHERE name=?", (faction["name"],)).fetchone()[0] == faction["satisfaction"] + (-2 if triggered else 0)
        assert db.conn.execute("SELECT satisfaction FROM classes WHERE name=?", (social_class["name"],)).fetchone()[0] == social_class["satisfaction"] + (-2 if triggered else 0)
        assert _pop(db, "农民", "shaanxi") == farmers_before - (300 if triggered else 0)
        assert _pop(db, "流民", "shaanxi") == refugees_before + (300 if triggered else 0)
    if first_reason is not None:
        declared_army = db.conn.execute(
            "SELECT id FROM armies WHERE id='jisi_declared_1840'"
        ).fetchone()
        assert (declared_army is not None) is triggered
        assert db.conn.execute("SELECT id FROM armies WHERE id='jisi_independent_1840'").fetchone() is not None
        assert db.conn.execute("SELECT status FROM characters WHERE name='毛文龙'").fetchone()[0] == (
            "dismissed" if triggered else "active"
        )
        assert db.conn.execute("SELECT status FROM characters WHERE name='孙传庭'").fetchone()[0] == "dismissed"
    if first_pressure == 35 and second_pressure == -5:
        before = (state.metrics["民心"], _pop(db, "流民", "shaanxi"))
        pressure_before = db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0]
        stub_month_translate(monkeypatch, lambda r, c: {
            "effects": [{"event_id": "not_an_event", "metric_delta": {"民心": -1},
                         "population_transfers": [{"origin_ref": "盘面自发", "source": "农民@shaanxi",
                                                   "target": "流民@shaanxi", "amount": 100, "reason": "灾害"}],
                         "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 1}}},
                        {"metric_delta": {"民心": -1}}],
        })
        dispatch_month_segment(db, state, segment="未知归属")
        assert (state.metrics["民心"], _pop(db, "流民", "shaanxi")) == (before[0] - 1, before[1])
        assert db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0] == pressure_before
        assert db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0] == pressure


def test_hidden_affair_strategic_result_does_not_trigger_or_land(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    hidden = db.affairs.open(
        name="已了结事务", origin="未供料", year=state.year,
        period=state.period, turn=state.turn,
    )
    db.conn.execute(
        "UPDATE affairs SET status='closed', closed_turn=? WHERE id=?",
        (state.turn, hidden.id),
    )
    db.conn.commit()
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    stub_month_translate(monkeypatch, lambda _request, _config: {
        "effects": [{
            "event_id": "jisi_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {
                "origin_ref": f"affair:{hidden.id}", "military_pressure": 5,
            }},
            "metric_delta": {"民心": -3},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "事件所属军需",
            }],
        }],
    })
    dispatch_month_segment(db, state, segment="不可见事务战果")
    assert db.issues.has_event_terminal_state('jisi_lubian', "triggered") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before


def _closed_affair(db, state):
    hidden = db.affairs.open(
        name="已了结事务", origin="未供料", year=state.year,
        period=state.period, turn=state.turn,
    )
    # 夹具直接写 closed 态；生产无 declare_closed 动作（ADR 0154）。
    db.conn.execute(
        "UPDATE affairs SET status='closed', closed_turn=? WHERE id=?",
        (state.turn, hidden.id),
    )
    db.conn.commit()
    return hidden


def _json_has_army_id(value, army_id: str) -> bool:
    if isinstance(value, dict):
        if value.get("id") == army_id:
            return True
        return any(_json_has_army_id(child, army_id) for child in value.values())
    if isinstance(value, list):
        return any(_json_has_army_id(child, army_id) for child in value)
    return False


def _army_rejection_categories(db, army_id: str) -> set[str]:
    import json

    return {
        category
        for category, item_json in db.conn.execute(
            "SELECT category, item_json FROM rejection_reports"
        )
        if _json_has_army_id(json.loads(item_json), army_id)
    }


@pytest.mark.parametrize("station_region,category", [
    (None, "unauthorized_affair_origin"),
    ("no-such-region", "invalid_enum"),
])
def test_hidden_affair_new_army_does_not_block_sibling_result(game, station_region, category, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    hidden = _closed_affair(db, state)
    pressure_before = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id='beizhili'"
    ).fetchone()[0]
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    armies_before = db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]
    new_army = {
        "origin_ref": f"affair:{hidden.id}", "id": "jisi_hidden_affair_1840",
        "name": "不可见事务新军", "owner_power": "houjin", "manpower": 1200,
    }
    if station_region is not None:
        new_army["station_region"] = station_region
    stub_month_translate(monkeypatch, lambda _request, _config: {
        "effects": [{
            "event_id": "jisi_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 5}},
            "new_armies": [new_army],
            "metric_delta": {"民心": -3},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "事件所属军需",
            }],
        }],
    })
    dispatch_month_segment(db, state, segment="好坏新军混装")
    assert db.issues.has_event_terminal_state('jisi_lubian', "triggered") is True
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id='beizhili'"
    ).fetchone()[0] == pressure_before + 5
    assert state.metrics["民心"] == metric_before - 3
    assert state.metrics["国库"] == treasury_before - 1
    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == armies_before
    assert _army_rejection_categories(db, "jisi_hidden_affair_1840") == {category}


@pytest.mark.parametrize("station_region", [None, "no-such-region"])
def test_hidden_affair_new_army_alone_does_not_trigger(game, station_region, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    hidden = _closed_affair(db, state)
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    armies_before = db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]
    new_army = {
        "origin_ref": f"affair:{hidden.id}", "id": "jisi_hidden_only_1840",
        "name": "唯一不可见新军", "owner_power": "houjin", "manpower": 1200,
    }
    if station_region is not None:
        new_army["station_region"] = station_region
    stub_month_translate(monkeypatch, lambda _request, _config: {
        "effects": [{
            "event_id": "jisi_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "new_armies": [new_army],
            "metric_delta": {"民心": -3},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "事件所属军需",
            }],
        }],
    })
    dispatch_month_segment(db, state, segment="全坏新军")
    assert db.issues.has_event_terminal_state('jisi_lubian', "triggered") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before
    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == armies_before
    assert _army_rejection_categories(db, "jisi_hidden_only_1840") == {"event_rejected"}


def test_unknown_station_region_new_army_does_not_trigger_or_land(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    armies_before = db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]
    stub_month_translate(monkeypatch, lambda _request, _config: {
        "effects": [{
            "event_id": "jisi_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "new_armies": [{
                "origin_ref": "盘面自发", "id": "jisi_bad_station_1840",
                "name": "驻地不存在的新军", "owner_power": "houjin",
                "station_region": "no-such-region", "manpower": 1200,
            }],
            "metric_delta": {"民心": -3},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "事件所属军需",
            }],
        }],
    })
    dispatch_month_segment(db, state, segment="未知驻地新军")
    assert db.issues.has_event_terminal_state('jisi_lubian', "triggered") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before
    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == armies_before


def test_final_strategic_rejection_leaves_no_owned_effects(game, monkeypatch, tmp_path):
    """The real player month rejects the whole envelope after an independent change."""
    from tests.test_month_chain_1843 import _prepare_player_month
    from tests.test_refugee_loop_652 import _pop
    from tests.army_pay_helpers import configure_guanning_army, _set_guanning_arrears
    from ming_sim.db import GameDB
    from tests.conftest import wait_for_background_jobs

    db, state, content = game
    state.year, state.period = 1631, 8
    state.metrics["民心"] = 50
    db.conn.execute("UPDATE regions SET controlled_by='ming' WHERE id='liaodong'")
    configure_guanning_army(db)
    _set_guanning_arrears(db, 5000)
    db.conn.execute("UPDATE armies SET supply=40 WHERE id='guanning'")
    db.conn.execute("UPDATE powers SET military_strength=80 WHERE id='houjin'")
    # This month already handled the unrelated scheduled levy request.
    db.mark_event_triggered(state, "liao_levy_rise_1631", terminal_reason="已驳", commit=False)
    db.reign.save_game_state(state)
    db.conn.commit()
    declaration = {
        "effects": [
            {"army_delta": {"guanning": {"origin_ref": "盘面自发", "supply": 10}}},
            {
                "event_id": "dalingghe",
                "new_issues": [{"origin_kind": "event_pool", "id": "dalingghe"}],
                "region_delta": {"liaodong": {
                    "origin_ref": "盘面自发", "unrest": 1,
                }},
                "metric_delta": {"民心": -3},
                "economy_moves": [{
                    "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                    "category": "event_owned", "reason": "军需",
                }, {
                    "origin_ref": "盘面自发", "account": "内库", "delta": -1,
                    "category": "event_owned", "reason": "内帑军需",
                }],
                "population_transfers": [{
                    "origin_ref": "盘面自发", "source": "农民@shaanxi",
                    "target": "流民@shaanxi", "amount": 300, "reason": "灾害",
                }],
                "fiscal_creates": [{
                    "origin_ref": "盘面自发", "key": "event_owned", "account": "国库",
                    "direction": "expense", "init_value": 1,
                }],
            },
            {
                "event_id": "dalingghe", "metric_delta": {"皇威": -2},
                "emperor_fate": "abdicate",
            },
        ],
    }
    # Real monthly drift still runs: compare to the same board with only the
    # independent effect, rather than attributing every monthly change to this event.
    control_dir = tmp_path / "control"
    control_dir.mkdir()
    control = GameDB(str(control_dir / "game.db"), content)
    try:
        db.conn.backup(control.conn)
        control_state = control.load_state()
        control_session = _prepare_player_month(
            control, control_state, content, monkeypatch,
            world=lambda *_a, **_k: "关宁补给改善。",
            translate=lambda *_a, **_k: {"effects": declaration["effects"][:1]},
        )
        assert control_session.resolve_turn(allow_empty_decree=True).stage == "gazette"
        wait_for_background_jobs(control)
        expected_metrics = dict(control_state.metrics)
        expected_refugees = _pop(control, "流民", "shaanxi")
    finally:
        wait_for_background_jobs(control)
        control.conn.close()

    def translate(request, _config):
        assert "dalingghe" in {event["id"] for event in request.candidates["events"]}
        return declaration

    session = _prepare_player_month(db, state, content, monkeypatch,
                                    world=lambda *_a, **_k: "关宁补给改善，本月战事未发。",
                                    translate=translate)
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"
    wait_for_background_jobs(db)
    assert not db.issues.has_event_terminal_state("dalingghe", "triggered")
    assert db.conn.execute("SELECT supply FROM armies WHERE id='guanning'").fetchone()[0] == 50
    assert {key: state.metrics[key] for key in ("民心", "皇威", "国库", "内库")} == {
        key: expected_metrics[key] for key in ("民心", "皇威", "国库", "内库")
    }
    assert _pop(db, "流民", "shaanxi") == expected_refugees
    assert db.conn.execute("SELECT COUNT(*) FROM economy_ledger WHERE category='event_owned'").fetchone()[0] == 0
    assert "event_owned_base" not in db.fiscal_config.values()
    assert not state.ended and not state.ending_status
    categories = {row[0] for row in db.conn.execute("SELECT category FROM rejection_reports")}
    assert "event_rejected" in categories








def test_null_emperor_fate_does_not_end_the_month(game, monkeypatch):
    from ming_sim.month_translate import dispatch_month_segment
    db, state, _ = game
    stub_month_translate(monkeypatch, lambda request, config: {"effects": {"emperor_fate": None}})
    result = dispatch_month_segment(db, state, segment="本月")
    assert not state.ended and not state.ending_status
    assert all(not view(applied, "victory_status") for applied in result.effects.applied)
