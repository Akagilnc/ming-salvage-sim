"""#1840 monthly segment translation through the C0 declaration seam."""

from __future__ import annotations

import sqlite3

import pytest

from tests.conftest import active_ming_character


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
    army, region = _army_id(db), _region_id(db)
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


def test_world_segment_effects_use_frozen_visible_affairs(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    visible = db.affairs.open(name="可见事务", origin="世界段", year=state.year,
                              period=state.period, turn=state.turn)
    hidden = db.affairs.open(name="不可见事务", origin="未供料", year=state.year,
                             period=state.period, turn=state.turn)
    db.affairs.declare_closed(hidden.id, turn=state.turn)
    before = state.metrics["国库"]
    # 真实入口供料只含未了事务；已了结事务不在本批输入。
    result = dispatch_month_segment(
        db, state, segment="两笔事务回指",
        translate_fn=lambda request, config: {"effects": {"economy_moves": [
            {"origin_ref": f"affair:{visible.id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "合法支出"},
            {"origin_ref": f"affair:{hidden.id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "越权支出"},
        ]}},
    )
    assert state.metrics["国库"] == before - 1
    assert result.effects.applied
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='invalid_enum'"
    ).fetchone()[0] >= 1


def test_unparseable_month_segment_does_not_stage_or_commit(game, monkeypatch):
    from ming_sim.audience_translate import AudienceTranslateError
    from ming_sim.month_translate import dispatch_month_segment, stage_month_segment

    db, state, _ = game
    monkeypatch.setattr("ming_sim.cli_backend._run_json_extractor_for_config",
                        lambda *args, **kwargs: ("not-json", ""))
    with pytest.raises(AudienceTranslateError):
        stage_month_segment(db, decree_ref="bad-json", segment="推演段",
                            turn=int(state.turn), decree_payload={})
    assert db.staged_declarations.staged_for("bad-json") == ()
    with pytest.raises(AudienceTranslateError):
        dispatch_month_segment(db, state, segment="世界段")
    assert db.staged_declarations.staged_for("bad-json") == ()

    with pytest.raises(AudienceTranslateError):
        dispatch_month_segment(db, state, segment="世界段",
                               translate_fn=lambda request, config: None)


def test_staged_month_effects_keep_input_reference_authority(game):
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    from ming_sim.month_translate import stage_month_segment

    db, state, _ = game
    visible = db.affairs.open(name="预推可见", origin="旨意", year=state.year,
                              period=state.period, turn=state.turn)
    future_affair_id = visible.id + 1
    before = state.metrics["国库"]
    stage_month_segment(
        db, decree_ref="frozen-refs", segment="预推段", turn=int(state.turn),
        decree_payload={}, translate_fn=lambda request, config: {"effects": {"economy_moves": [
            {"origin_ref": f"affair:{visible.id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "可见事务"},
            {"origin_ref": f"affair:{future_affair_id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "预推后新开事务"},
        ]}},
    )
    assert state.metrics["国库"] == before
    hidden = db.affairs.open(name="暂存后新开", origin="世界段", year=state.year,
                             period=state.period, turn=state.turn)
    assert hidden.id == future_affair_id
    result = settle_staged_declarations_in_decree_order(db, state, ["frozen-refs"])["frozen-refs"]
    assert state.metrics["国库"] == before - 1
    rejections = result.effects.applied[0]["economy_moves_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["rejected"] is True
    assert rejections[0]["item"]["origin_ref"] == f"affair:{hidden.id}"


def test_world_segment_repeated_entity_effects_apply_in_order(game):
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
    dispatch_month_segment(db, state, segment="先振奋后受挫", translate_fn=lambda r, c: {
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
    assert db.conn.execute("SELECT morale FROM armies WHERE id=?", (army,)).fetchone()[0] == 70
    assert db.conn.execute("SELECT public_support FROM regions WHERE id=?", (region,)).fetchone()[0] == 39
    assert db.conn.execute("SELECT COUNT(*) FROM affairs").fetchone()[0] == affairs_before + 1
    refs = db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE reason IN ('第一笔', '第二笔')"
    ).fetchall()
    assert len(refs) == 2
    assert refs[0][0] == refs[1][0]
    assert _pop(db, "流民", "shaanxi") == refugees_before - 2000


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
    triggered, pressure, morale, first_reason,
):
    from ming_sim.month_translate import dispatch_month_segment
    from tests.test_refugee_loop_652 import _pop

    db, state, _ = game
    state.year, state.period = 1629, 11
    db.conn.execute("UPDATE regions SET military_pressure=? WHERE id='beizhili'", (initial_pressure,))
    db.conn.execute("UPDATE armies SET morale=50 WHERE id='jingying'")
    db.conn.commit()
    if first_pressure == 35 and second_pressure == -5:
        state.metrics["民心"] = 100
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
                "metric_delta": {"民心": -10 if metric_before == 100 else -2},
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
    elif metric_before == 100:
        effects.append({"metric_delta": {"民心": 5}})
    dispatch_month_segment(db, state, segment="己巳之变两笔战果", translate_fn=lambda r, c: {
        "effects": effects,
    })
    assert db.has_event_triggered("jisi_lubian") is triggered
    assert db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0] == pressure
    assert db.conn.execute("SELECT morale FROM armies WHERE id='jingying'").fetchone()[0] == morale
    if first_pressure in (35, 10, "非法增量") and first_reason is not None:
        declared_delta = (-10 if metric_before == 100 else -2) if triggered else 0
        independent_delta = 5 if metric_before == 100 else (1 if first_pressure == "非法增量" else 0)
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
        dispatch_month_segment(db, state, segment="未知归属", translate_fn=lambda r, c: {
            "effects": [{"event_id": "not_an_event", "metric_delta": {"民心": -1},
                         "population_transfers": [{"origin_ref": "盘面自发", "source": "农民@shaanxi",
                                                   "target": "流民@shaanxi", "amount": 100, "reason": "灾害"}],
                         "region_delta": {"beizhili": {"origin_ref": "盘面自发", "military_pressure": 1}}},
                        {"metric_delta": {"民心": -1}}],
        })
        assert (state.metrics["民心"], _pop(db, "流民", "shaanxi")) == (before[0] - 1, before[1])
        assert db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0] == pressure_before
        assert db.conn.execute("SELECT military_pressure FROM regions WHERE id='beizhili'").fetchone()[0] == pressure


def test_hidden_affair_strategic_result_does_not_trigger_or_land(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    hidden = db.affairs.open(
        name="已了结事务", origin="未供料", year=state.year,
        period=state.period, turn=state.turn,
    )
    db.affairs.declare_closed(hidden.id, turn=state.turn)
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    dispatch_month_segment(db, state, segment="不可见事务战果", translate_fn=lambda _request, _config: {
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
    assert db.has_event_triggered("jisi_lubian") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before


def _closed_affair(db, state):
    hidden = db.affairs.open(
        name="已了结事务", origin="未供料", year=state.year,
        period=state.period, turn=state.turn,
    )
    db.affairs.declare_closed(hidden.id, turn=state.turn)
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
def test_hidden_affair_new_army_does_not_block_sibling_result(game, station_region, category):
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
    dispatch_month_segment(db, state, segment="好坏新军混装", translate_fn=lambda _request, _config: {
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
    assert db.has_event_triggered("jisi_lubian") is True
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id='beizhili'"
    ).fetchone()[0] == pressure_before + 5
    assert state.metrics["民心"] == metric_before - 3
    assert state.metrics["国库"] == treasury_before - 1
    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == armies_before
    assert _army_rejection_categories(db, "jisi_hidden_affair_1840") == {category}


@pytest.mark.parametrize("station_region", [None, "no-such-region"])
def test_hidden_affair_new_army_alone_does_not_trigger(game, station_region):
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
    dispatch_month_segment(db, state, segment="全坏新军", translate_fn=lambda _request, _config: {
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
    assert db.has_event_triggered("jisi_lubian") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before
    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == armies_before
    assert _army_rejection_categories(db, "jisi_hidden_only_1840") == {"event_rejected"}


def test_unknown_station_region_new_army_does_not_trigger_or_land(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    armies_before = db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]
    dispatch_month_segment(db, state, segment="未知驻地新军", translate_fn=lambda _request, _config: {
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
    assert db.has_event_triggered("jisi_lubian") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before
    assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == armies_before


def test_final_strategic_rejection_leaves_no_owned_effects(game):
    """Owned fields and the event ledger stay one envelope.

    An independent same-kind delta may move the board before the event is
    judged (#1844). Whatever this entry finally records, a non-trigger must
    not keep the event's own metric or treasury delta.
    """
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    db.conn.execute("UPDATE regions SET military_pressure=90 WHERE id='beizhili'")
    db.conn.commit()
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    dispatch_month_segment(db, state, segment="独立军压后事件战果", translate_fn=lambda _request, _config: {
        "effects": [
            {"region_delta": {"beizhili": {
                "origin_ref": "盘面自发", "military_pressure": 10,
            }}},
            {
                "event_id": "jisi_lubian",
                "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
                "事件结局": {"jisi_lubian": "入塞被遏"},
                "region_delta": {"beizhili": {
                    "origin_ref": "盘面自发", "military_pressure": 5,
                    "reason": "己巳之变敌逼京畿",
                }},
                "metric_delta": {"民心": -3},
                "economy_moves": [{
                    "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                    "category": "过月支出", "reason": "事件所属军需",
                }],
            },
        ],
    })
    triggered = db.has_event_triggered("jisi_lubian")
    assert state.metrics["民心"] == metric_before + (-3 if triggered else 0)
    assert state.metrics["国库"] == treasury_before + (-1 if triggered else 0)
