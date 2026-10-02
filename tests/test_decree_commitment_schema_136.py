import sqlite3


from ming_sim.db import GameDB
import ming_sim.issues as I


def _promulgated_commitment_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="测试辽饷承诺",
        target_kind="army", target_id="guanning", payload={"purpose": "补饷"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"










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
    assert rejected[0]["item"]["title"] == "安抚毛文龙直到效顺"
    row = db.conn.execute(
        "SELECT id FROM issues WHERE title=?", ("安抚毛文龙直到效顺",)
    ).fetchone()
    assert row is None




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
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- #1831 起 CREATE 基线含 affair_id；本测只缺 commitment 列，不模拟缺 affair 旧档
            -- （#1812 Out of Scope：缺 affair_id 时 CREATE INDEX 须响亮失败，不得静默迁移）
            affair_id INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()

    db = GameDB(str(path), content)
    db.close()
    db = GameDB(str(path), content)
    try:
        state = db.load_state()
        issue_id = db.insert_issue(state, kind="initiative", title="迁移后议题")
        row = db.conn.execute(
            "SELECT end_turn, stop_condition, commitment_kind FROM issues WHERE id=?", (issue_id,),
        ).fetchone()
        assert dict(row) == {"end_turn": 0, "stop_condition": "", "commitment_kind": ""}
    finally:
        db.close()
