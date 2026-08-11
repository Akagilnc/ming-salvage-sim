import sqlite3

import pytest

from ming_sim.db import GameDB
from ming_sim.models import effect_dict_has_work
import ming_sim.issues as I
from ming_sim.simulation import canonicalize_extraction


def _promulgated_commitment_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="测试辽饷承诺",
        target_kind="army", target_id="guanning", payload={"purpose": "补饷"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _table_columns(db, table: str) -> dict[str, dict[str, object]]:
    return {
        row["name"]: dict(row)
        for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def test_issues_schema_has_commitment_deadline_columns(read_game):
    db, _, _ = read_game

    cols = _table_columns(db, "issues")

    assert "end_turn" in cols
    assert "stop_condition" in cols
    assert "commitment_kind" in cols
    assert cols["end_turn"]["dflt_value"] == "0"
    assert cols["stop_condition"]["dflt_value"] == "''"
    assert cols["commitment_kind"]["dflt_value"] == "''"


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
    ],
)
def test_effect_dict_has_work_ignores_metadata_only_payloads(payload):
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


@pytest.mark.parametrize(
    "payload",
    [
        {"人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "评定", "loyalty": "2"}]},
        {"character": [{"name": "毛文龙", "loyalty": "2", "reason": "每月安抚"}]},
    ],
)
def test_effect_dict_has_work_ignores_malformed_person_loyalty(payload):
    assert effect_dict_has_work(payload) is False


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
    assert "commitment_kind 必填" in rejected[0]["reason"]
    row = db.conn.execute(
        "SELECT id FROM issues WHERE title=?", ("安抚毛文龙直到效顺",)
    ).fetchone()
    assert row is None


def test_canonicalize_new_issue_preserves_commitment_columns():
    out = canonicalize_extraction({
        "new_issues": [{
            "标题": "每月补饷直到补齐",
            "来源引用": "decree:turn-1:pay-arrears",
            "停止条件": {"army.guanning.arrears": "<=0"},
            "承诺标记": "until_stop",
            "end_turn": 9,
        }],
    })

    assert out["new_issues"][0]["origin_ref"] == "decree:turn-1:pay-arrears"
    assert out["new_issues"][0]["stop_condition"] == {"army.guanning.arrears": "<=0"}
    assert out["new_issues"][0]["commitment_kind"] == "until_stop"
    assert out["new_issues"][0]["end_turn"] == 9
    assert "resolve_condition" not in out["new_issues"][0]


def test_decree_initiative_cap_allows_fifteen_active_issues(game):
    db, state, _ = game
    for idx in range(14):
        db.insert_issue(
            state,
            kind="initiative",
            title=f"既有国策{idx}",
            origin_kind="decree",
            effect_on_resolve={"metrics": {"民心": 1}},
        )

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "origin_ref": _promulgated_commitment_origin(db, state),
            "kind": "initiative",
            "title": "第十五条承诺地基",
            "effect_on_resolve": {"metrics": {"民心": 1}},
        }],
    })

    created = [item for item in out["new_issues"] if item.get("issue_id")]
    assert len(created) == 1, out
    assert db.count_active_initiatives() == 15


def test_show_active_issues_uses_fifteen_initiative_cap(game, capsys):
    db, state, _ = game
    db.insert_issue(state, kind="initiative", title="国策展示", origin_kind="decree")

    I.show_active_issues(db)

    out = capsys.readouterr().out
    assert "玩家 1/15" in out
    assert "玩家 1/10" not in out


def test_existing_issues_table_gets_commitment_columns_idempotently(tmp_path, content):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            origin_kind TEXT NOT NULL DEFAULT '',
            origin_ref TEXT NOT NULL DEFAULT '',
            origin_turn INTEGER NOT NULL,
            bar_value INTEGER NOT NULL DEFAULT 40,
            bar_good_meaning TEXT NOT NULL DEFAULT '已平',
            bar_bad_meaning TEXT NOT NULL DEFAULT '失控',
            inertia INTEGER NOT NULL DEFAULT 0,
            phase TEXT NOT NULL DEFAULT '起',
            stage_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            severity INTEGER NOT NULL DEFAULT 50,
            region_hint TEXT NOT NULL DEFAULT '',
            faction_hint TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            ongoing_effects TEXT NOT NULL DEFAULT '{}',
            cancellable TEXT NOT NULL DEFAULT 'never',
            cancel_cost TEXT NOT NULL DEFAULT '{}',
            effect_on_resolve TEXT NOT NULL DEFAULT '{}',
            effect_on_fail TEXT NOT NULL DEFAULT '{}',
            resolve_condition TEXT NOT NULL DEFAULT '',
            fail_condition TEXT NOT NULL DEFAULT '',
            resolution_summary TEXT NOT NULL DEFAULT '',
            last_advance_turn INTEGER NOT NULL DEFAULT 0,
            closed_turn INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    db = GameDB(str(path), content)
    db.close()
    db = GameDB(str(path), content)
    try:
        cols = _table_columns(db, "issues")
        assert cols["end_turn"]["dflt_value"] == "0"
        assert cols["stop_condition"]["dflt_value"] == "''"
        assert cols["commitment_kind"]["dflt_value"] == "''"
    finally:
        db.close()


def test_decree_initiative_cap_rejects_sixteenth_with_updated_message(game):
    db, state, _ = game
    for idx in range(15):
        db.insert_issue(
            state,
            kind="initiative",
            title=f"既有国策{idx}",
            origin_kind="decree",
            effect_on_resolve={"metrics": {"民心": 1}},
        )

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "origin_ref": _promulgated_commitment_origin(db, state),
            "kind": "initiative",
            "title": "第十六条应拒",
            "effect_on_resolve": {"metrics": {"民心": 1}},
        }],
    })

    rejected = [item for item in out["new_issues"] if item.get("rejected")]
    assert len(rejected) == 1, out
    assert "十五事在办" in rejected[0]["reason"]
    assert "十事在办" not in rejected[0]["reason"]
