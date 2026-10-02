"""Issue close/inertia contracts at the public tracker/settlement adapters."""
from __future__ import annotations

import json

import pytest

import ming_sim.issues as I
from ming_sim.models import LLMConfig
from tests.conftest import active_ming_character


def _decree_origin(db, state):
    dossier_id = db.create_decree_dossier(state, action_type="policy", decree_text="测试国策来源", target_kind="issue", target_id="test")
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


@pytest.mark.parametrize("scenario", ["new_army", "reinforce", "exile", "death_in_prison", "exit_transit", "departure", "appointment_shadows_legacy", "metrics_only"])
def test_resolve_applies_entities_through_tracker(game, monkeypatch, scenario):
    db, state, content = game
    name = active_ming_character(db, content)
    person = content.characters[name]
    for field in ("status", "office", "office_type", "location", "transit_to", "reason_code", "transit_distance_remaining", "transit_speed_factor", "transit_start_turn"):
        if hasattr(person, field):
            monkeypatch.setattr(person, field, getattr(person, field))
    before_count = db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]
    before_manpower = db.conn.execute("SELECT manpower FROM armies WHERE id='jingying'").fetchone()[0]
    effects = {
        "new_army": {"new_armies": [{"id": "tianxiongjun_test", "name": "天雄军测试", "owner_power": "ming", "manpower": 18000,
            "maintenance_per_turn": 3, "commander": "卢象升", "station": "大名", "troop_type": "步",
            "pay_source_region": "shaanxi", "province_pay_share": 1, "central_pay_share": 0}]},
        "reinforce": {"army_delta": {"jingying": {"manpower": 500, "reason": "国策募兵"}}},
        "exile": {"character_status_changes": [{"name": name, "status": "exiled", "reason": "国策清算"}]},
        "death_in_prison": {"character_status_changes": [{"name": name, "status": "dead", "reason": "结案赐死"}]},
        "exit_transit": {"character_status_changes": [{"name": name, "status": "dismissed", "reason": "局势问责"}]},
        "departure": {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
        "appointment_shadows_legacy": {
            "character_status_changes": [{"name": name, "status": "imprisoned", "reason_code": "陷虏"}],
            "人物变更": [{"name": name, "动作": "任命", "office": "陕西总督", "office_type": "地方", "region_id": "shaanxi", "reason": "新键任官"}],
        },
        "metrics_only": {"metrics": {"民心": 5}},
    }
    if scenario == "death_in_prison":
        db.set_character_status(state, name, "imprisoned", "前置下狱")
        person.status, person.office, person.transit_to = "imprisoned", "", ""
    elif scenario in ("exit_transit", "departure"):
        db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
        person.location = "beizhili"
        if scenario == "exit_transit":
            I.apply_person_changes_only(db, state, [{"name": name, "动作": "行止", "transit_to": "liaodong"}], content=content)
    issue_id = db.insert_issue(state, kind="initiative", title="实体结案", origin_kind="decree",
        origin_ref=_decree_origin(db, state), effect_on_resolve=effects[scenario])
    result = I.apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": issue_id, "reason": "resolved"}]}, content=content)
    assert result["closes"]
    assert result["entity_rejections"] == []
    if scenario == "new_army":
        assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == before_count + 1
        row = db.conn.execute("SELECT manpower,commander FROM armies WHERE id='tianxiongjun_test'").fetchone()
        assert dict(row) == {"manpower": 18000, "commander": "卢象升"}
    elif scenario == "reinforce":
        assert db.conn.execute("SELECT manpower FROM armies WHERE id='jingying'").fetchone()[0] == before_manpower + 500
        assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == before_count
    elif scenario == "metrics_only":
        assert db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0] == before_count
    else:
        row = db.conn.execute("SELECT status,office,transit_to,reason_code FROM characters WHERE name=?", (name,)).fetchone()
        if scenario == "departure":
            assert row["transit_to"] == person.transit_to == "liaodong"
        elif scenario == "appointment_shadows_legacy":
            assert row["status"] == "active"
            assert row["office"] == person.office == "陕西总督"
            assert row["reason_code"] == ""
            changes = result["applied_person_changes"]
            assert all(item.get("status") != "imprisoned" for item in changes)
            assert any(item.get("new_office") == "陕西总督" for item in changes)
        else:
            expected = {"exile": "exiled", "death_in_prison": "dead", "exit_transit": "dismissed"}[scenario]
            assert row["status"] == person.status == expected
            assert row["office"] == person.office == ""
            assert row["transit_to"] == person.transit_to == ""
        logs = db.conn.execute("SELECT action,person_name,origin_ref FROM person_logs WHERE person_name=? ORDER BY id DESC LIMIT 1", (name,)).fetchone()
        assert logs["person_name"] == name
        assert logs["origin_ref"].startswith("dossier:")


@pytest.mark.parametrize("case", ["dead_transition", "person_missing", "person_shape", "person_item", "army_missing_fields", "army_owner", "legacy_person_missing", "legacy_status", "army_missing", "legacy_item"])
def test_resolve_rejects_bad_entities_at_tracker_entry(game, monkeypatch, case):
    db, state, content = game
    name = active_ming_character(db, content)
    effects = {
        "dead_transition": {"character_status_changes": [{"name": name, "status": "dismissed", "reason": "旧键误写"}]},
        "person_missing": {"人物变更": [{"name": "不存在的人", "动作": "行止", "transit_to": "liaodong"}]},
        "person_shape": {"人物变更": "bad"},
        "person_item": {"人物变更": ["bad"]},
        "army_missing_fields": {"new_armies": [{"id": "broken", "name": "残军", "owner_power": "ming"}]},
        "army_owner": {"new_armies": [{"id": "x", "name": "野军", "owner_power": "不存在的势力", "manpower": 1000, "maintenance_per_turn": 1}]},
        "legacy_person_missing": {"character_status_changes": [{"name": "查无此人张三", "status": "dead"}]},
        "legacy_status": {"character_status_changes": [{"name": name, "status": "升仙"}]},
        "army_missing": {"army_delta": {"查无此军": {"manpower": 100}}},
        "legacy_item": {"character_status_changes": ["not-a-dict"]},
    }
    if case == "dead_transition":
        monkeypatch.setattr(content.characters[name], "status", "dead")
        db.set_character_status(state, name, "dead", "前置死亡")
    issue_id = db.insert_issue(state, kind="initiative", title="非法实体结案", origin_kind="decree",
        origin_ref=_decree_origin(db, state), effect_on_resolve=effects[case])
    with pytest.raises(ValueError):
        I.apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": issue_id, "reason": "resolved"}]}, content=content)
    if case == "dead_transition":
        assert db.get_character_status(name)[0] == content.characters[name].status == "dead"


def test_apply_score_extraction_splits_bad_nested_entity(game):
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"region_delta": {"shanxi": "not-a-dict", "henan": {"unrest": 1}}})
    assert applied["validate_shape_rejections"][0]["item"] == {"entity_id": "shanxi", "raw_value": "not-a-dict"}


def test_apply_score_extraction_accepts_flat_faction_scalar(game):
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"faction_delta": {"阉党": -10}, "class_delta": {"农民": 0}})
    assert applied["faction_delta"] == {"阉党": -10}
    assert applied["class_delta"] == {}
    assert len(applied["class_delta_rejections"]) == 1
    assert applied["class_delta_rejections"][0]["category"] == "invalid_enum"


def test_apply_score_extraction_rejects_nondict_power_second_level_per_entity(game):
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"power_updates": {"houjin": {"leverage": 1}, "mongol": "bad"}})
    assert applied["validate_shape_rejections"][0]["item"] == {"entity_id": "mongol", "raw_value": "bad"}


def test_apply_score_extraction_rejects_nondict_list_item_per_item(game):
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"fiscal_creates": [{"key": "x"}, "bad-scalar"]})
    assert applied["validate_shape_rejections"][0]["item"] == {"raw_value": "bad-scalar"}


def test_apply_score_extraction_tolerates_null_field(game):
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"region_delta": None, "army_delta": None})
    assert applied["region_changes"] == applied["army_changes"] == applied["validate_shape_rejections"] == []


def test_apply_score_extraction_rejects_unknown_top_level_key(game):
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"region_delta_typo": {"shanxi": {"unrest": 5}}, "metric_delta": {"民心": 1}})
    shape = applied["validate_shape_rejections"]
    assert len(shape) == 1
    assert shape[0]["rejected"] is True
    assert shape[0]["item"] == {"raw_value": {"shanxi": {"unrest": 5}}}
    assert applied["metric_delta"].get("民心") == 1


def test_new_issue_nondict_effect_fields_do_not_crash(game, monkeypatch):
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    before = db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [{
        "origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "畸形效果国策", "kind": "initiative",
        "effect_on_resolve": "not-a-dict", "ongoing_effects": ["not-a-dict"], "effect_on_fail": None,
    }]})
    assert out["new_issues"] and not out["new_issues"][0].get("rejected")
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before + 1


@pytest.mark.parametrize("channel,env,expected", [("", "agy", {"metrics": {"民心": 1}}), ("cli", None, {"metrics": {"民心": 1}}), ("api", "agy", {})])
def test_initiative_floor_follows_runtime_channel(game, monkeypatch, channel, env, expected):
    import ming_sim.cli_backend as cb
    db, state, _ = game
    if env:
        monkeypatch.setenv("MING_SIM_LLM_BACKEND", env)
    else:
        monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    calls = []
    monkeypatch.setattr(cb, "enrich_initiative_effects", lambda *a, **k: calls.append((a, k)) or {
        "effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {},
    })
    cfg = LLMConfig(api_key="sk-test", base_url="https://example.test/v1", model="m", channel=channel, cli_runner="codex", cli_model="gpt-test") if channel else None
    I.apply_score_extraction(db, state, {"new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "空回报国策", "kind": "initiative"}]}, llm_config=cfg)
    row = db.conn.execute("SELECT effect_on_resolve FROM issues WHERE title='空回报国策'").fetchone()
    assert json.loads(row[0]) == expected
    if channel == "api":
        assert calls == []


@pytest.mark.parametrize("effect_key,bar,inertia", [("effect_on_resolve", 99, 1), ("effect_on_fail", 1, -1)])
def test_inertia_terminal_applies_entities(game, monkeypatch, effect_key, bar, inertia):
    db, state, content = game
    name = active_ming_character(db, content)
    person = content.characters[name]
    for field in ("status", "office", "office_type", "transit_to"):
        monkeypatch.setattr(person, field, getattr(person, field))
    db.insert_issue(state, kind="situation", title="自然结案", bar_value=bar, inertia=inertia,
        **{effect_key: {"character_status_changes": [{"name": name, "status": "dismissed", "reason": "局势问责"}]}})
    I.apply_issue_inertia_and_ongoing(db, state)
    assert db.get_character_status(name)[0] == person.status == "dismissed"


def test_inertia_natural_resolve_applies_entities(game):
    db, state, _ = game
    db.insert_issue(state, kind="situation", title="自然结案建军", bar_value=99, inertia=1,
        effect_on_resolve={"new_armies": [{"id": "inertia_army_test", "name": "惯性军", "owner_power": "ming", "manpower": 5000,
            "maintenance_per_turn": 1, "pay_source_region": "shaanxi", "province_pay_share": 1, "central_pay_share": 0}]})
    I.apply_issue_inertia_and_ongoing(db, state)
    assert db.conn.execute("SELECT COUNT(*) FROM armies WHERE id='inertia_army_test'").fetchone()[0] == 1


def test_inertia_natural_resolve_applies_unified_person_change_with_bound_content(game, monkeypatch):
    db, state, content = game
    name = active_ming_character(db, content)
    person = content.characters[name]
    for field in ("office", "office_type", "status", "transit_to"):
        monkeypatch.setattr(person, field, getattr(person, field))
    db.insert_issue(state, kind="situation", title="自然结案人事", bar_value=99, inertia=1,
        effect_on_resolve={"人物变更": [{"name": name, "动作": "调任", "office": "陕西总督", "office_type": "督抚", "region_id": "shaanxi", "reason": "自然结案调任"}]})
    I.apply_issue_inertia_and_ongoing(db, state)
    assert db.conn.execute("SELECT office FROM characters WHERE name=?", (name,)).fetchone()[0] == person.office == "陕西总督"
