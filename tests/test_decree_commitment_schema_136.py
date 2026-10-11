import pytest
from ming_sim.models import effect_dict_has_work
from ming_sim.entities.issue.tracker import apply_issue_tracker_output
from ming_sim.applier import Provenance
import ming_sim.issues as I

def _promulgated_commitment_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="测试辽饷承诺",
        target_kind="army", target_id="guanning", payload={"purpose": "补饷"},
    )
    db.dossiers.record_dossier_decision(dossier_id, "promulgated")
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

    result = apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved"}]},
    source=Provenance.system_simulation)

    assert db.conn.execute(
        "SELECT 1 FROM buildings WHERE id=?", (building["id"],),
    ).fetchone() is None
    log = db.conn.execute(
        "SELECT old_value, field FROM building_logs WHERE building_id=? ORDER BY id DESC LIMIT 1",
        (building["id"],),
    ).fetchone()
    assert dict(log) == {"old_value": building["name"], "field": "remove"}
    assert result.closes[0]["building_ops"][0]["removed"] is True


def test_new_issue_persists_commitment_columns_from_tracker_output(game):
    db, state, _ = game
    stop_condition = {"army.guanning.arrears": "<=0"}

    out = apply_issue_tracker_output(db, state, {
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
    }, source=Provenance.system_simulation)

    created = [item for item in out.new_issues if item.get("issue_id")]
    assert len(created) == 1, out
    row = db.conn.execute(
        "SELECT end_turn, stop_condition, resolve_condition, commitment_kind FROM issues WHERE id=?",
        (created[0]["issue_id"],),
    ).fetchone()
    assert row["end_turn"] == state.turn + 4
    assert row["stop_condition"] == '{"army.guanning.arrears":"<=0"}'
    assert row["resolve_condition"] == ""
    assert row["commitment_kind"] == "until_stop"

@pytest.mark.parametrize(
    "payload",
    [
        {"人物变更": [{"origin_ref": "盘面自发", "name": "毛文龙", "动作": "评定", "loyalty": "2"}]},
    ],
)
def test_effect_dict_has_work_ignores_malformed_person_loyalty(payload):
    assert effect_dict_has_work(payload) is False
