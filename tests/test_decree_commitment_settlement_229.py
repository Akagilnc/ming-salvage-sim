import json

import pytest

from tests.test_due_review_621 import _settle_empty_month as _player_month
from ming_sim.issues import (
    apply_score_extraction,
)
from ming_sim.situation_drift import apply_situation_monthly_drift


def _promulgated_commitment_origin(db, state, token: str) -> str:
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text=f"测试承诺：{token}",
        target_kind="issue", target_id=token, payload={"token": token},
    )
    db.dossiers.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _army_arrears(db, army_id: str) -> int:
    row = db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()
    assert row is not None
    return int(row["arrears"])


def _seed_central_army_arrears(db, arrears_by_army_id: dict[str, float]) -> None:
    for army_id, arrears in arrears_by_army_id.items():
        db.conn.execute(
            """
            UPDATE armies
            SET province_pay_arrears = 0, central_pay_arrears = ?
            WHERE id = ?
            """,
            (arrears, army_id),
        )


def _character_loyalty(db, name: str) -> int:
    row = db.conn.execute("SELECT loyalty FROM characters WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["loyalty"])


def _faction_satisfaction(db, name: str) -> int:
    row = db.conn.execute("SELECT satisfaction FROM factions WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["satisfaction"])


def _class_satisfaction(db, name: str, region_id: str = "") -> int:
    row = db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    assert row is not None
    return int(row["satisfaction"])


def _region_cannon(db, region_id: str) -> int:
    row = db.conn.execute("SELECT cannon FROM regions WHERE id=?", (region_id,)).fetchone()
    assert row is not None
    return int(row["cannon"])


def _issue_row(db, issue_id: int):
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row is not None
    return row


def _advance_player_month(db, state, content):
    with pytest.MonkeyPatch.context() as patch:
        _player_month(db, state, content, patch)


_settle_empty_month = _advance_player_month







def test_faction_class_commitment_ongoing_applies_monthly_when_counted(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE factions SET satisfaction=50 WHERE name='军队'")
    db.conn.execute("UPDATE classes SET satisfaction=50 WHERE name='士绅' AND region_id=''")
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="军心士绅安抚承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:faction-class",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "factions": {"军队": {"satisfaction": 2}},
            "class_delta": {"士绅": {"satisfaction": -3}},
        },
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _advance_player_month(db, state, content)

    assert _faction_satisfaction(db, "军队") == 52
    assert _class_satisfaction(db, "士绅") == 47
    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["commitment_progress"]["months_elapsed"] == 1


def test_commitment_ongoing_malformed_entity_payloads_are_rejected_without_crashing(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE factions SET satisfaction=50 WHERE name='军队'")
    db.conn.commit()

    db.insert_issue(
        state,
        kind="initiative",
        title="坏实体月度承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:bad-monthly-entities",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "factions": {"军队": {"satisfaction": 2}},
            "region_delta": {"beizhili": "不是dict"},
            "army_delta": {"guanning": ["不是dict"]},
            "power_updates": {"houjin": "不是dict"},
        },
        end_turn=state.turn + 2,
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    assert _faction_satisfaction(db, "军队") == 52
    rows = db.conn.execute(
        "SELECT category, reason FROM rejection_reports WHERE category = 'invalid_shape' "
        "ORDER BY id"
    ).fetchall()
    paths = ("region_delta.beizhili", "army_delta.guanning", "power_updates.houjin")
    matched = [row for row in rows if any(path in row["reason"] for path in paths)]
    assert len(matched) == 3
    assert [row["category"] for row in matched] == ["invalid_shape"] * 3
    found = [next(path for path in paths if path in row["reason"]) for row in matched]
    assert sorted(found) == sorted(paths)






def test_commitment_monthly_ongoing_respects_outer_transaction_rollback(game):
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="事务内月度兑现承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:ongoing-rollback",
        bar_value=0,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": 1}},
        end_turn=state.turn + 2,
        commitment_kind="until_stop",
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    apply_situation_monthly_drift(db, state)
    db.conn.rollback()

    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='ongoing'",
        (issue_id,),
    ).fetchone()[0] == 0




def test_region_cannon_commitment_ongoing_applies_monthly_when_counted(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE regions SET city_level=5, cannon=1 WHERE id='beizhili'")
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="京师城防炮月度加设承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:capital-cannon",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "region_delta": {
                "beizhili": {
                    "cannon": 2,
                    "reason": "每月增设京师城防炮",
                }
            }
        },
        end_turn=state.turn + 2,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _advance_player_month(db, state, content)

    assert _region_cannon(db, "beizhili") == 3
    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["commitment_progress"]["months_elapsed"] == 1










def test_commitment_ongoing_economy_not_scaled_by_bar_discount(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 200})
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="高进度补饷承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:high-bar-pay",
        bar_value=90,
        inertia=0,
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -50, "reason": "高进度仍全额补饷", "purpose": "补饷"}
            ]
        },
        stop_condition=json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    paid = db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger WHERE purpose='补饷' AND target_kind='army'"
    ).fetchone()[0]
    assert paid == -50


def test_arrears_commitment_preserves_explicit_monthly_payment_target(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 70, "xuan_da": 40})
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="宣大定向补饷承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:xuanda-targeted-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -30,
                    "reason": "每月定向补宣大旧欠",
                    "purpose": "补饷",
                    "target_kind": "army",
                    "target_id": "xuan_da",
                }
            ]
        },
        stop_condition=json.dumps({"army.xuan_da.arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    assert [tuple(row) for row in db.conn.execute(
        "SELECT target_id, delta FROM economy_ledger "
        "WHERE purpose='补饷' AND target_kind='army' ORDER BY id"
    )] == [("xuan_da", -30)]




def test_metric_commitment_records_progress_when_monthly_cap_blocks_effect(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    state.metrics["皇威"] = 50
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="先占满本月皇威变动",
        origin_kind="decree",
        origin_ref="decree:turn-1:cap-first",
        bar_value=0,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": 5}},
        cancellable="decree",
    )
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="皇威月度承诺被 cap 阻挡",
        origin_kind="decree",
        origin_ref="decree:turn-1:cap-commitment",
        bar_value=90,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": 1}},
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _advance_player_month(db, state, content)

    assert state.metrics["皇威"] == 55
    advances = db.conn.execute(
        "SELECT trigger_kind, narrative, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["metrics"] == {}
    assert payload["commitment_progress"]["months_elapsed"] == 1










def test_commitment_missing_purpose_still_routes_arrears_budget(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100})
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    result = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "missing-purpose"),
                    "kind": "initiative",
                    "title": "每月补关宁欠饷直到补齐",
                    "ongoing_effects": {
                        "economy": [
                            {"account": "国库", "delta": -50, "reason": "每月补关宁欠饷"}
                        ]
                    },
                    "stop_condition": {"army.guanning.arrears": "<=0"},
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )
    created = result["issue_summary"]["new_issues"][0]
    assert not created.get("rejected")

    _advance_player_month(db, state, content)

    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger "
        "WHERE purpose='补饷' AND target_kind='army'"
    ).fetchone()[0] == -50


def test_commitment_targeted_pay_uses_explicit_arrears_target(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100})
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="带目标的补饷承诺按目标军兑现",
        origin_kind="decree",
        origin_ref="decree:turn-1:targeted-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -50,
                    "reason": "定向补宣大旧欠",
                    "purpose": "补饷",
                    "target_kind": "army",
                    "target_id": "xuan_da",
                }
            ]
        },
        stop_condition=json.dumps({"army.guanning|xuan_da.arrears.sum": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    assert [tuple(row) for row in db.conn.execute(
        "SELECT target_id, delta FROM economy_ledger "
        "WHERE purpose='补饷' AND target_kind='army' ORDER BY id"
    )] == [("xuan_da", -50)]


def test_commitment_malformed_pay_target_does_not_fall_back_to_priority_pool(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100})
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="坏目标补饷承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:bad-target-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -50,
                    "reason": "坏目标不应改付",
                    "purpose": "补饷",
                    "target_kind": "army",
                    "target_id": "__missing_army__",
                }
            ]
        },
        stop_condition=json.dumps({"army.guanning|xuan_da.arrears.sum": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    rejected = db.conn.execute(
        "SELECT item_json FROM rejection_reports "
        "WHERE category='missing_ref'"
    ).fetchall()
    assert any(json.loads(row["item_json"]).get("target_id") == "__missing_army__"
               for row in rejected)
    assert _army_arrears(db, "guanning") == 101
    assert _army_arrears(db, "xuan_da") == 100
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM economy_ledger WHERE purpose='补饷'"
    ).fetchone()[0] == 0


def test_non_arrears_commitment_missing_pay_target_does_not_open_priority_pool(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100})
    state.metrics["国库"] = 500
    state.metrics["皇威"] = 50
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="非欠饷门槛承诺不得空目标补饷",
        origin_kind="decree",
        origin_ref="decree:turn-1:non-arrears-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -50,
                    "reason": "缺目标补饷不应改付",
                    "purpose": "补饷",
                }
            ]
        },
        stop_condition=json.dumps({"皇威": ">=99"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    rejected = db.conn.execute(
        "SELECT item_json FROM rejection_reports "
        "WHERE category='missing_ref'"
    ).fetchall()
    assert any(json.loads(row["item_json"]).get("purpose") == "补饷"
               and not json.loads(row["item_json"]).get("target_id")
               for row in rejected)
    assert _army_arrears(db, "guanning") == 101
    assert _army_arrears(db, "xuan_da") == 100
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM economy_ledger WHERE purpose='补饷'"
    ).fetchone()[0] == 0


def test_commitment_pay_pool_is_scoped_to_arrears_stop_gate_armies(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100, "jizhen": 100})
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="多军范围补饷承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:scoped-pool-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -50,
                    "reason": "只补宣大蓟镇旧欠",
                    "purpose": "补饷",
                }
            ]
        },
        stop_condition=json.dumps({"army.xuan_da|jizhen.arrears.sum": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _advance_player_month(db, state, content)

    paid_targets = {
        row["target_id"]
        for row in db.conn.execute(
            "SELECT target_id FROM economy_ledger WHERE purpose='补饷' AND target_kind='army'"
        ).fetchall()
    }
    assert paid_targets and paid_targets <= {"xuan_da", "jizhen"}
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger "
        "WHERE purpose='补饷' AND target_kind='army'"
    ).fetchone()[0] == -50
