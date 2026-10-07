import pytest

from ming_sim.models import effect_dict_has_work
import ming_sim.issues as I

def _promulgated_commitment_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="测试辽饷承诺",
        target_kind="army", target_id="guanning", payload={"purpose": "补饷"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"

@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"economy": []},
        {"economy": [{}]},
        {"economy": [{"account": "国库", "delta": 0, "reason": "占位"}]},
        {"economy": [{"account": "国库", "delta": 0, "category": "", "reason": ""}]},
        {"economy": [{"target_id": "guanning", "reason": "占位"}]},
        {"metrics": {}},
        {"metrics": {"民心": 0}},
        {"metrics": {"民心": 0}, "note": "无月度动作"},
        {"人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "评定", "loyalty": "2"}]},
        {"character": [{"name": "毛文龙", "loyalty": "2", "reason": "每月安抚"}]},
    ],
)
def test_effect_dict_has_work_ignores_empty_or_invalid_payloads(payload):
    assert effect_dict_has_work(payload) is False

@pytest.mark.parametrize(
    "payload",
    [
        {"economy": [{"account": "国库", "delta": -1, "reason": "补饷"}]},
        {"metrics": {"皇威": 1}},
        {"region_delta": {"shaanxi": {"origin_ref": "盘面自发", "status": "灾荒稍解"}}},
        {"region_delta": {"beizhili": {"origin_ref": "盘面自发", "cannon": 2}}},
        {"army_delta": {"guanning": {"origin_ref": "盘面自发", "commander": "孙承宗"}}},
        {"factions": {"阉党": {"leverage": -1}}},
        {"class_delta": {"农民": {"satisfaction": 1}}},
        {"buildings": [{"action": "remove", "building_id": "beizhili_b1"}]},
        {"new_armies": [{"origin_ref": "盘面自发", "id": "tianxiong", "manpower": 1000}]},
        {"人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "评定", "loyalty": 1}]},
        {"character": [{"name": "毛文龙", "loyalty": 1, "reason": "每月安抚"}]},
        {"legacy": {"modifiers": {"民心": 1}}},
    ],
)
def test_effect_dict_has_work_recognizes_schema_effects(payload):
    assert effect_dict_has_work(payload) is True

def test_issue_resolution_removes_building_and_keeps_remove_audit_log(game):
    db, state, _content = game
    building = db.conn.execute(
        "SELECT id, name FROM buildings ORDER BY id LIMIT 1"
    ).fetchone()
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="奉旨拆除旧建筑",
        effect_on_resolve={
            "buildings": [{"action": "remove", "building_id": building["id"],
                           "origin_ref": "盘面自发"}],
        },
    )

    result = I.apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved"}]},
    )

    assert db.conn.execute(
        "SELECT 1 FROM buildings WHERE id=?", (building["id"],),
    ).fetchone() is None
    log = db.conn.execute(
        "SELECT old_value, field FROM building_logs WHERE building_id=? ORDER BY id DESC LIMIT 1",
        (building["id"],),
    ).fetchone()
    assert dict(log) == {"old_value": building["name"], "field": "remove"}
    assert result["closes"][0]["building_ops"][0]["removed"] is True

def test_insert_issue_persists_commitment_deadline_columns(game):
    db, state, _ = game

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="补辽饷直到补齐",
        origin_kind="decree",
        end_turn=state.turn + 6,
        stop_condition='{"army.guanning.arrears":"<=0"}',
        commitment_kind="until_stop",
    )

    row = db.conn.execute(
        "SELECT end_turn, stop_condition, commitment_kind FROM issues WHERE id=?", (issue_id,)
    ).fetchone()
    assert dict(row) == {
        "end_turn": state.turn + 6,
        "stop_condition": '{"army.guanning.arrears":"<=0"}',
        "commitment_kind": "until_stop",
    }

def test_insert_issue_serializes_structured_stop_condition_as_json(game):
    db, state, _ = game

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="补饷结构化停止条件",
        origin_kind="decree",
        stop_condition={"army.guanning.arrears": "<=0"},
        commitment_kind="until_stop",
    )

    row = db.conn.execute(
        "SELECT stop_condition FROM issues WHERE id=?", (issue_id,)
    ).fetchone()
    assert row["stop_condition"] == '{"army.guanning.arrears":"<=0"}'

def test_new_issue_persists_commitment_columns_from_tracker_output(game):
    db, state, _ = game
    stop_condition = {"army.guanning.arrears": "<=0"}

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "origin_ref": _promulgated_commitment_origin(db, state),
            "kind": "initiative",
            "title": "每月补辽饷直到补齐",
            "end_turn": state.turn + 4,
            "ongoing_effects": {"economy": [{"account": "国库", "delta": -50, "reason": "每月补辽饷"}]},
            "stop_condition": stop_condition,
            "commitment_kind": "until_stop",
        }],
    })

    created = [item for item in out["new_issues"] if item.get("issue_id")]
    assert len(created) == 1, out
    row = db.conn.execute(
        "SELECT end_turn, stop_condition, resolve_condition, commitment_kind FROM issues WHERE id=?",
        (created[0]["issue_id"],),
    ).fetchone()
    assert row["end_turn"] == state.turn + 4
    assert row["stop_condition"] == '{"army.guanning.arrears":"<=0"}'
    assert row["resolve_condition"] == ""
    assert row["commitment_kind"] == "until_stop"

def test_decree_commitment_shape_with_string_stop_condition_requires_marker(read_game):
    db, state, _ = read_game

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "origin_ref": "decree:turn-1:appease-mao",
            "kind": "initiative",
            "title": "安抚毛文龙直到效顺",
            "ongoing_effects": {
                "character": [{"name": "毛文龙", "loyalty": 2, "reason": "每月安抚"}],
            },
            "stop_condition": "character.毛文龙.loyalty >= 65",
        }],
    })

    rejected = [item for item in out["new_issues"] if item.get("rejected")]
    assert len(rejected) == 1, out
    assert rejected[0]["category"] == "invalid_enum"
    row = db.conn.execute(
        "SELECT id FROM issues WHERE title=?", ("安抚毛文龙直到效顺",)
    ).fetchone()
    assert row is None

