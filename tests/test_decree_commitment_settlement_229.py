import json

import pytest

from ming_sim.credit_events import (
    KIND_BACK,
    KIND_BETRAY,
    KIND_FULFILL,
    KIND_SCAPEGOAT,
    write_credit_event,
)
from ming_sim.relations import EMPEROR_NODE
from ming_sim.decree import settle_with_delta
from ming_sim.issues import (
    apply_issue_inertia_and_ongoing,
    apply_score_extraction,
    commitment_progress_payload,
    show_active_issues,
)
from ming_sim.simulation import _extractor_context_payload, build_simulator_payload


def _promulgated_commitment_origin(db, state, token: str) -> str:
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text=f"测试承诺：{token}",
        target_kind="issue", target_id=token, payload={"token": token},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _army_arrears(db, army_id: str) -> int:
    row = db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()
    assert row is not None
    return int(row["arrears"])


def _seed_central_army_arrears(db, arrears_by_army_id: dict[str, int]) -> None:
    for army_id, arrears in arrears_by_army_id.items():
        db.conn.execute(
            """
            UPDATE armies
            SET arrears = ?, province_pay_arrears = 0, central_pay_arrears = ?
            WHERE id = ?
            """,
            (arrears, arrears, army_id),
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


def _settle_empty_month(db, state, content):
    before = state.turn
    settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1


def test_created_future_limited_duration_commitment_applies_first_month(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()
    starting_authority = int(state.metrics["皇威"])
    expected_end_turn = state.turn + 2

    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "future-monthly-authority"),
                    "kind": "initiative",
                    "title": "连续两月宣示皇威",
                    "stage_text": "连续两月遣使宣示皇威。",
                    "ongoing_effects": {"metrics": {"皇威": -1}},
                    "end_turn": expected_end_turn,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created["rejected"] is False
    issue_id = created["issue_id"]

    _settle_empty_month(db, state, content)

    assert int(state.metrics["皇威"]) == starting_authority - 1
    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert row["end_turn"] == expected_end_turn
    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]


def test_character_loyalty_commitment_ongoing_applies_monthly_and_records_progress(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE characters SET loyalty=44 WHERE name='毛文龙'")
    content.characters["毛文龙"].loyalty = 44
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙·持续承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:appease-mao",
        bar_value=0,
        inertia=0,
        stage_text="遣臣常驻皮岛安抚毛文龙，逐月消解其观望。",
        ongoing_effects={},
        stop_condition=json.dumps({"character.毛文龙.loyalty": ">=65"}, ensure_ascii=False),
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _settle_empty_month(db, state, content)

    assert _character_loyalty(db, "毛文龙") == 50
    assert content.characters["毛文龙"].loyalty == 50
    event = db.conn.execute(
        "SELECT event_kind FROM relation_edge_events WHERE target='毛文龙' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event is not None and event["event_kind"] == KIND_BACK
    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["commitment_progress"]["months_elapsed"] == 1
    assert payload["commitment_progress"]["remaining_to_goal"] == 15
    sim_issue = next(
        issue for issue in build_simulator_payload(state, db, "", "")["active_issues"]
        if issue["issue_id"] == issue_id
    )
    assert sim_issue["commitment_progress"]["months_elapsed"] == 1
    assert "直到达标" in sim_issue["待办未解进度"]


def test_legacy_character_resolve_condition_commitment_settles_when_threshold_reached(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE characters SET loyalty=64 WHERE name='毛文龙'")
    content.characters["毛文龙"].loyalty = 64
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="旧档安抚毛文龙·持续承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:legacy-appease-mao",
        bar_value=0,
        inertia=0,
        stage_text="遣臣常驻皮岛安抚毛文龙，逐月消解其观望。",
        resolve_condition="character.毛文龙.loyalty >= 65",
        ongoing_effects={
            "人物变更": [
                {
                    "name": "毛文龙",
                    "动作": "评定",
                    "loyalty": 2,
                    "reason": "奉旨持续安抚，观望稍解",
                }
            ]
        },
        cancellable="decree",
    )

    _settle_empty_month(db, state, content)

    assert _character_loyalty(db, "毛文龙") == 68
    row = _issue_row(db, issue_id)
    assert row["status"] == "resolved"
    assert row["bar_value"] == 100
    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing", "commitment_resolve"]


@pytest.mark.parametrize(
    ("kind", "origin", "starting", "expected"),
    [
        (KIND_FULFILL, "dossier:701:credit:fulfill", 50, 55),
        (KIND_BACK, "dossier:702:credit:back", 50, 55),
        (KIND_BETRAY, "issue:703:credit:reject_grace", 50, 45),
        (KIND_SCAPEGOAT, "dossier:704:credit:scapegoat:pawn:毛文龙", 50, 45),
        (KIND_SCAPEGOAT, "faction:705:credit:scapegoat:pawn:毛文龙", 50, 50),
        (KIND_SCAPEGOAT, "unknown:706:credit:scapegoat:pawn:毛文龙", 50, 50),
        (KIND_FULFILL, "dossier:707:credit:fulfill", 0, 10),
        (KIND_BETRAY, "issue:708:credit:reject_grace", 99, 98),
        (KIND_FULFILL, "dossier:709:credit:fulfill", 100, 100),
        (KIND_BETRAY, "issue:710:credit:reject_grace", 0, 0),
    ],
)
def test_credit_event_is_the_idempotent_loyalty_write_source(
    game, kind, origin, starting, expected,
):
    db, state, content = game
    db.conn.execute("UPDATE characters SET loyalty=? WHERE name='毛文龙'", (starting,))
    content.characters["毛文龙"].loyalty = starting
    event_id = write_credit_event(
        db, state, person="毛文龙", event_kind=kind, context="结构化信用事实", origin=origin,
    )

    assert _character_loyalty(db, "毛文龙") == expected
    assert content.characters["毛文龙"].loyalty == expected
    assert write_credit_event(
        db, state, person="毛文龙", event_kind=kind, context="重放语境不参与判重", origin=origin,
    ) == event_id
    assert _character_loyalty(db, "毛文龙") == expected


def test_old_loyalty_watermark_schema_upgrades_before_new_credit_event(game):
    db, state, content = game
    db.conn.execute("DROP TABLE loyalty_credit_event_applied")
    db.conn.execute(
        "CREATE TABLE loyalty_credit_event_applied ("
        "event_id INTEGER PRIMARY KEY REFERENCES relation_edge_events(id), "
        "character_name TEXT NOT NULL, delta INTEGER NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    db.init_schema()

    columns = {
        row["name"]
        for row in db.conn.execute("PRAGMA table_info(loyalty_credit_event_applied)")
    }
    assert columns == {"event_id"}
    event_id = write_credit_event(
        db, state, person="毛文龙", event_kind=KIND_BACK,
        context="旧档升级后撑腰", origin="dossier:upgrade:credit:back",
    )
    assert db.conn.execute(
        "SELECT event_id FROM loyalty_credit_event_applied WHERE event_id=?", (event_id,)
    ).fetchone() is not None
    assert content.characters["毛文龙"].loyalty == _character_loyalty(db, "毛文龙")


def test_month_settlement_consumes_preexisting_credit_event_once(game):
    db, state, content = game
    db.conn.execute("UPDATE characters SET loyalty=50 WHERE name='毛文龙'")
    db.record_relation_edge_event(
        source=EMPEROR_NODE,
        target="毛文龙",
        event_kind=KIND_BACK,
        context="升级前已经落库的撑腰事实",
        origin="dossier:711:credit:back",
        turn=state.turn,
        year=state.year,
        period=state.period,
    )

    _settle_empty_month(db, state, content)
    assert _character_loyalty(db, "毛文龙") == 55
    _settle_empty_month(db, state, content)
    assert _character_loyalty(db, "毛文龙") == 55


def test_retired_person_rating_cannot_write_loyalty(game):
    db, state, content = game
    before = _character_loyalty(db, "毛文龙")
    out = apply_score_extraction(
        db, state,
        {"人物变更": [{"name": "毛文龙", "动作": "评定", "loyalty": 99,
                      "来源引用": "dossier:1"}]},
        content=content,
    )

    assert _character_loyalty(db, "毛文龙") == before
    rejected = out["applied_person_changes"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "retired_action"


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

    _settle_empty_month(db, state, content)

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

    _settle_empty_month(db, state, content)

    assert _faction_satisfaction(db, "军队") == 52
    rows = db.conn.execute(
        "SELECT category, reason FROM rejection_reports WHERE reason LIKE '%须为对象%' "
        "ORDER BY id"
    ).fetchall()
    assert [row["category"] for row in rows] == ["invalid_shape", "invalid_shape", "invalid_shape"]
    assert any("region_delta.beizhili" in row["reason"] for row in rows)
    assert any("army_delta.guanning" in row["reason"] for row in rows)
    assert any("power_updates.houjin" in row["reason"] for row in rows)


def test_commitment_stop_gate_resolve_respects_outer_transaction_rollback(game):
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="事务内自动结清承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:resolve-rollback",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": []},
        stop_condition=json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    apply_issue_inertia_and_ongoing(db, state)
    db.conn.rollback()

    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='commitment_resolve'",
        (issue_id,),
    ).fetchone()[0] == 0


def test_commitment_expiry_respects_outer_transaction_rollback(game):
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="事务内到期停账承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:expire-rollback",
        bar_value=0,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": -1}},
        end_turn=state.turn,
        commitment_kind="until_stop",
    )
    db.conn.commit()

    db.conn.execute("BEGIN")
    apply_issue_inertia_and_ongoing(db, state)
    db.conn.rollback()

    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='expire'",
        (issue_id,),
    ).fetchone()[0] == 0


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
    apply_issue_inertia_and_ongoing(db, state)
    db.conn.rollback()

    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='ongoing'",
        (issue_id,),
    ).fetchone()[0] == 0


def test_commitment_progress_skips_non_numeric_gate_values(game):
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="坏数值门槛承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:bad-progress-value",
        bar_value=0,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": 1}},
        stop_condition=json.dumps({"皇威": ">=10"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )
    state.metrics["皇威"] = "非数字"

    progress = commitment_progress_payload(db, state, _issue_row(db, issue_id))

    assert progress == {"months_elapsed": 0, "paid_total": 0}


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

    _settle_empty_month(db, state, content)

    assert _region_cannon(db, "beizhili") == 3
    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["commitment_progress"]["months_elapsed"] == 1


def test_until_stop_arrears_commitment_settlement_oracle_resolves_with_restore(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 70, "xuan_da": 40})
    state.metrics["国库"] = 500
    db.save_state(state)

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="边军月饷",
        origin_kind="decree",
        origin_ref="decree:turn-1:border-arrears",
        bar_value=0,
        inertia=0,
        stage_text="户部每月拨银五十万补边军旧欠，直到补齐。",
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -50,
                    "category": "补饷承诺",
                    "reason": "边军月饷每月补旧欠",
                    "purpose": "补饷",
                }
            ]
        },
        stop_condition=json.dumps({"army.guanning|xuan_da.arrears.sum": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
        cancellable="decree",
    )
    open_issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="开放式承诺不应空门收尾",
        origin_kind="decree",
        origin_ref="decree:turn-1:open",
        bar_value=10,
        inertia=0,
        ongoing_effects={"metrics": {"民心": 1}},
        stop_condition="",
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _settle_empty_month(db, state, content)
    assert _army_arrears(db, "guanning") == 20
    assert _army_arrears(db, "xuan_da") == 40
    first = _issue_row(db, issue_id)
    assert first["status"] == "active"
    assert first["bar_value"] == 45
    assert _issue_row(db, open_issue_id)["status"] == "active"
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger "
        "WHERE account='国库' AND purpose='补饷' AND target_kind='army'"
    ).fetchone()[0] == -50

    reloaded_state = db.load_state()
    _settle_empty_month(db, reloaded_state, content)
    assert _army_arrears(db, "guanning") == 0
    assert _army_arrears(db, "xuan_da") == 10
    second = _issue_row(db, issue_id)
    assert second["status"] == "active"
    assert second["bar_value"] == 91

    _settle_empty_month(db, reloaded_state, content)
    assert _army_arrears(db, "guanning") == 0
    assert _army_arrears(db, "xuan_da") == 0
    done = _issue_row(db, issue_id)
    assert done["status"] == "resolved"
    assert done["bar_value"] == 100
    assert done["closed_turn"] == reloaded_state.turn - 1
    assert _issue_row(db, open_issue_id)["status"] == "active"
    assert reloaded_state.turn == state.turn + 2

    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing", "ongoing", "ongoing", "commitment_resolve"]
    payloads = [json.loads(row["metric_delta"]) for row in advances[:3]]
    assert [payload["commitment_progress"]["paid_total"] for payload in payloads] == [50, 100, 110]
    assert payloads[-1]["commitment_progress"]["remaining_arrears"] == 0


def test_commitment_progress_contexts_are_structured(game, capsys):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=25 WHERE id='guanning'")
    db.conn.commit()
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="关宁月饷",
        origin_kind="decree",
        origin_ref="decree:turn-1:guanning-pay",
        bar_value=0,
        inertia=0,
        stage_text="每月拨银补关宁旧欠，直到补齐。",
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -10, "reason": "关宁月饷", "purpose": "补饷"}
            ]
        },
        stop_condition=json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _settle_empty_month(db, state, content)

    sim_issue = next(
        issue for issue in build_simulator_payload(state, db, "", "")["active_issues"]
        if issue["issue_id"] == issue_id
    )
    assert sim_issue["commitment_progress"]["months_elapsed"] == 1
    assert sim_issue["commitment_progress"]["paid_total"] == 10
    assert sim_issue["commitment_progress"]["remaining_arrears"] == 15
    assert "已第1月" in sim_issue["待办未解进度"]
    assert "直到补齐" in sim_issue["待办未解进度"]

    extractor_issue = next(
        issue for issue in _extractor_context_payload(db, state, "", "")["active_issues"]
        if issue["issue_id"] == issue_id
    )
    assert extractor_issue["commitment_progress"] == sim_issue["commitment_progress"]

    show_active_issues(db)
    output = capsys.readouterr().out
    assert "已第1月" in output
    assert "直到补齐" in output


def test_arrears_commitment_progress_preserves_fractional_remaining(game):
    """#305 coder-fix：承诺进度里的欠饷尾数不能截断成精确/归零显示。"""
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=12.5 WHERE id='guanning'")
    db.conn.commit()
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="关宁零星旧欠",
        origin_kind="decree",
        origin_ref="decree:turn-1:fractional-arrears",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": []},
        stop_condition=json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    row = _issue_row(db, issue_id)
    progress = commitment_progress_payload(db, state, row)

    assert progress["remaining_arrears"] == 12.5
    sim_issue = next(
        issue for issue in build_simulator_payload(state, db, "", "")["active_issues"]
        if issue["issue_id"] == issue_id
    )
    assert "尚欠约15万两" in sim_issue["待办未解进度"]


def test_commitment_progress_fractional_strict_gate_can_be_satisfied(game):
    """strict < gates use real-valued comparison once arrears can be fractional."""
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=0.5 WHERE id='guanning'")
    db.conn.commit()
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="关宁欠饷降至一万以下",
        origin_kind="decree",
        origin_ref="decree:turn-1:fractional-strict-arrears",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": []},
        stop_condition=json.dumps({"army.guanning.arrears": "<1"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    progress = commitment_progress_payload(db, state, _issue_row(db, issue_id))

    assert progress["remaining_arrears"] == 0

    db.conn.execute("UPDATE armies SET arrears=1.5 WHERE id='guanning'")
    short_issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="关宁欠饷仍须降至一万以下",
        origin_kind="decree",
        origin_ref="decree:turn-1:fractional-strict-arrears-short",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": []},
        stop_condition=json.dumps({"army.guanning.arrears": "<1"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    short_progress = commitment_progress_payload(db, state, _issue_row(db, short_issue_id))

    assert short_progress["remaining_arrears"] == 1

    db.conn.execute("UPDATE armies SET arrears=1.5 WHERE id='guanning'")
    greater_issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="关宁欠饷升过一万",
        origin_kind="decree",
        origin_ref="decree:turn-1:fractional-strict-arrears-greater",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": []},
        stop_condition=json.dumps({"army.guanning.arrears": ">1"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    greater_progress = commitment_progress_payload(db, state, _issue_row(db, greater_issue_id))

    assert greater_progress["remaining_arrears"] == 0


def test_commitment_progress_text_splits_by_commitment_shape_and_gate(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=30 WHERE id='guanning'")
    db.conn.commit()

    arrears_id = db.insert_issue(
        state,
        kind="initiative",
        title="补饷承诺文案",
        origin_kind="decree",
        origin_ref="decree:turn-1:arrears-text",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": [{"account": "国库", "delta": -10, "reason": "补饷", "purpose": "补饷"}]},
        stop_condition=json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )
    limited_id = db.insert_issue(
        state,
        kind="initiative",
        title="时限承诺文案",
        origin_kind="decree",
        origin_ref="decree:turn-1:limited-text",
        bar_value=0,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": 1}},
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
    )
    due_id = db.insert_issue(
        state,
        kind="initiative",
        title="复核承诺文案",
        origin_kind="decree",
        origin_ref="decree:turn-1:due-text",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": [], "metrics": {}},
        end_turn=state.turn,
        commitment_kind="until_stop",
    )
    character_id = db.insert_issue(
        state,
        kind="initiative",
        title="人物承诺文案",
        origin_kind="decree",
        origin_ref="decree:turn-1:character-text",
        bar_value=0,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": -1}},
        stop_condition=json.dumps({"character.毛文龙.loyalty": ">=101"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    _settle_empty_month(db, state, content)
    issues = {
        item["issue_id"]: item
        for item in build_simulator_payload(state, db, "", "")["active_issues"]
    }

    arrears_text = issues[arrears_id]["待办未解进度"]
    assert "尚欠" in arrears_text
    assert "万两" in arrears_text
    assert "直到补齐" in arrears_text

    limited_text = issues[limited_id]["待办未解进度"]
    assert "已履行1月" in limited_text
    assert "限3月" in limited_text   # duration = end_turn - origin_turn = 3 (relative, not absolute)
    assert "还剩2月" in limited_text  # remaining = 3 - 1 = 2
    assert "限至第" not in limited_text  # no absolute turn numbers
    assert "补齐" not in limited_text

    due_text = issues[due_id]["待办未解进度"]
    assert "到期待裁" in due_text
    assert "补齐" not in due_text
    assert "万两" not in due_text

    character_progress = issues[character_id]["commitment_progress"]
    assert "remaining_to_goal" in character_progress
    assert "remaining_arrears" not in character_progress
    character_text = issues[character_id]["待办未解进度"]
    assert "直到达标" in character_text
    assert "补齐" not in character_text
    assert "万两" not in character_text


def test_commitment_ongoing_economy_not_scaled_by_bar_discount(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=200 WHERE id='guanning'")
    state.metrics["国库"] = 500
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert _army_arrears(db, "guanning") == 150
    paid = db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger WHERE purpose='补饷' AND target_kind='army'"
    ).fetchone()[0]
    assert paid == -50


def test_arrears_commitment_preserves_explicit_monthly_payment_target(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 70, "xuan_da": 40})
    state.metrics["国库"] = 500
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert _army_arrears(db, "guanning") == 70
    assert _army_arrears(db, "xuan_da") == 10


def test_high_bar_metric_only_commitment_applies_and_records_monthly_progress(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    state.metrics["皇威"] = 50
    db.save_state(state)

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="高进度皇威月度承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:imperial-prestige",
        bar_value=90,
        inertia=0,
        ongoing_effects={"metrics": {"皇威": 1}},
        stop_condition="",
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _settle_empty_month(db, state, content)

    assert state.metrics["皇威"] == 51
    assert _issue_row(db, issue_id)["status"] == "active"
    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["metrics"] == {"皇威": 1}
    assert payload["commitment_progress"]["months_elapsed"] == 1


def test_metric_commitment_records_progress_when_monthly_cap_blocks_effect(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    state.metrics["皇威"] = 50
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert state.metrics["皇威"] == 55
    advances = db.conn.execute(
        "SELECT trigger_kind, narrative, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing"]
    assert "未产生额外数值变动" in advances[0]["narrative"]
    payload = json.loads(advances[0]["metric_delta"])
    assert payload["metrics"] == {}
    assert payload["commitment_progress"]["months_elapsed"] == 1


def test_commitment_end_turn_expires_without_resolve_effects(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=200 WHERE id='guanning'")
    state.metrics["国库"] = 500
    starting_popular_support = int(state.metrics["民心"])
    db.save_state(state)

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="到期停账承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:expire-pay",
        bar_value=20,
        inertia=0,
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -50, "reason": "到期前最后一月补饷", "purpose": "补饷"}
            ]
        },
        effect_on_resolve={"metrics": {"民心": 9}},
        stop_condition="",
        end_turn=state.turn,
        commitment_kind="until_stop",
    )

    _settle_empty_month(db, state, content)

    row = _issue_row(db, issue_id)
    assert row["status"] == "dropped"
    assert row["closed_turn"] == state.turn - 1
    assert _army_arrears(db, "guanning") == 200
    assert int(state.metrics["民心"]) == starting_popular_support
    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["expire"]


def test_limited_duration_commitment_ticks_until_end_turn_then_expires(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=200 WHERE id='guanning'")
    state.metrics["国库"] = 500
    starting_popular_support = int(state.metrics["民心"])
    start_turn = state.turn
    db.save_state(state)

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="连续两月补饷承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:two-month-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -40, "reason": "连续两月补饷", "purpose": "补饷"}
            ]
        },
        stop_condition="",
        end_turn=start_turn + 2,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _settle_empty_month(db, state, content)
    assert _issue_row(db, issue_id)["status"] == "active"
    assert _army_arrears(db, "guanning") == 160

    _settle_empty_month(db, state, content)
    assert _issue_row(db, issue_id)["status"] == "active"
    assert _army_arrears(db, "guanning") == 120

    _settle_empty_month(db, state, content)
    row = _issue_row(db, issue_id)
    assert row["status"] == "dropped"
    assert row["closed_turn"] == start_turn + 2
    assert _army_arrears(db, "guanning") == 120
    assert int(state.metrics["民心"]) == starting_popular_support

    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing", "ongoing", "expire"]


def test_until_stop_condition_beats_later_end_turn_for_stacked_commitment(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=30 WHERE id='guanning'")
    state.metrics["国库"] = 500
    db.save_state(state)

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="补饷直到补齐且三月为限",
        origin_kind="decree",
        origin_ref="decree:turn-1:stop-before-expire",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -50, "reason": "补齐即停", "purpose": "补饷"}
            ]
        },
        stop_condition=json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    _settle_empty_month(db, state, content)

    row = _issue_row(db, issue_id)
    assert row["status"] == "resolved"
    assert _army_arrears(db, "guanning") == 0
    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [row["trigger_kind"] for row in advances] == ["ongoing", "commitment_resolve"]


def test_cancelled_commitment_is_distinct_from_expired_commitment(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()

    cancelled_id = db.insert_issue(
        state,
        kind="initiative",
        title="撤销的时限承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:cancel-limited",
        bar_value=15,
        inertia=0,
        ongoing_effects={"metrics": {"民心": 1}},
        end_turn=state.turn,
        commitment_kind="until_stop",
        cancellable="decree",
    )
    expired_id = db.insert_issue(
        state,
        kind="initiative",
        title="到期的时限承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:expire-limited",
        bar_value=15,
        inertia=0,
        ongoing_effects={"metrics": {"民心": 1}},
        end_turn=state.turn,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    db.cancel_issue(state, cancelled_id, narrative="奉旨撤回", commit=False)
    _settle_empty_month(db, state, content)

    assert _issue_row(db, cancelled_id)["status"] == "dropped"
    assert _issue_row(db, expired_id)["status"] == "dropped"
    rows = db.conn.execute(
        "SELECT issue_id, trigger_kind FROM issue_advances "
        "WHERE issue_id IN (?, ?) ORDER BY id",
        (cancelled_id, expired_id),
    ).fetchall()
    assert [(row["issue_id"], row["trigger_kind"]) for row in rows] == [
        (cancelled_id, "cancel"),
        (expired_id, "expire"),
    ]


def test_commitment_missing_purpose_still_routes_arrears_budget(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=100 WHERE id='guanning'")
    state.metrics["国库"] = 500
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert _army_arrears(db, "guanning") == 50
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta),0) FROM economy_ledger "
        "WHERE purpose='补饷' AND target_kind='army'"
    ).fetchone()[0] == -50


def test_commitment_targeted_pay_uses_explicit_arrears_target(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100})
    state.metrics["国库"] = 500
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert _army_arrears(db, "guanning") == 100
    assert _army_arrears(db, "xuan_da") == 50


def test_commitment_malformed_pay_target_does_not_fall_back_to_priority_pool(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100})
    state.metrics["国库"] = 500
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert db.conn.execute(
        """
        SELECT 1 FROM rejection_reports
        WHERE category = 'missing_ref'
          AND reason LIKE '%补饷目标军队未入库%'
        """
    ).fetchone() is not None
    assert _army_arrears(db, "guanning") == 100
    assert _army_arrears(db, "xuan_da") == 100
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM economy_ledger WHERE purpose='补饷'"
    ).fetchone()[0] == 0


def test_non_arrears_commitment_missing_pay_target_does_not_open_priority_pool(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100})
    state.metrics["国库"] = 500
    state.metrics["皇威"] = 50
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert db.conn.execute(
        """
        SELECT 1 FROM rejection_reports
        WHERE category = 'missing_ref'
          AND reason LIKE '%补饷必须指定%'
        """
    ).fetchone() is not None
    assert _army_arrears(db, "guanning") == 100
    assert _army_arrears(db, "xuan_da") == 100
    assert db.conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM economy_ledger WHERE purpose='补饷'"
    ).fetchone()[0] == 0


def test_commitment_pay_pool_is_scoped_to_arrears_stop_gate_armies(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_central_army_arrears(db, {"guanning": 100, "xuan_da": 100, "jizhen": 100})
    state.metrics["国库"] = 500
    db.save_state(state)

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

    _settle_empty_month(db, state, content)

    assert _army_arrears(db, "guanning") == 100
    assert _army_arrears(db, "xuan_da") + _army_arrears(db, "jizhen") == 150
    paid_targets = {
        row["target_id"]
        for row in db.conn.execute(
            "SELECT target_id FROM economy_ledger WHERE purpose='补饷' AND target_kind='army'"
        ).fetchall()
    }
    assert paid_targets <= {"xuan_da", "jizhen"}


def test_commitment_progress_keeps_strict_stop_gate_semantics(game):
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.save_state(state)

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="严格门槛补饷承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:strict-gate",
        bar_value=0,
        inertia=0,
        ongoing_effects={"economy": []},
        stop_condition=json.dumps({"army.guanning.arrears": "<0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )

    progress = commitment_progress_payload(db, state, _issue_row(db, issue_id))

    assert progress is not None
    assert progress["remaining_arrears"] == 1


def test_end_turn_without_ongoing_is_not_expired_by_settlement_tick(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()
    result = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": _promulgated_commitment_origin(db, state, "future-review"),
                    "kind": "initiative",
                    "title": "三月后复试",
                    "ongoing_effects": {},
                    "stop_condition": "",
                    "end_turn": state.turn,
                    "commitment_kind": "until_stop",
                }
            ]
        },
        content=content,
    )
    created = result["issue_summary"]["new_issues"][0]
    assert not created.get("rejected")
    issue_id = int(created["issue_id"])

    _settle_empty_month(db, state, content)

    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert row["closed_turn"] is None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='expire'",
        (issue_id,),
    ).fetchone()[0] == 0


def test_one_shot_end_turn_commitment_surfaces_in_existing_review_channel(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="孙承宗三月后复试",
        origin_kind="decree",
        origin_ref="decree:turn-1:sun-review",
        bar_value=0,
        inertia=0,
        stage_text="孙承宗暂听候政，三月后复试。",
        ongoing_effects={},
        stop_condition="",
        end_turn=state.turn,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    payload = build_simulator_payload(state, db, "", "")

    assert "secret_orders" not in payload
    due_items = [
        item for item in payload["due_commitments"]
        if item.get("entry_kind") == "due_commitment"
    ]
    assert len(due_items) == 1
    due = due_items[0]
    assert due["issue_id"] == issue_id
    assert due["title"] == "孙承宗三月后复试"
    assert due["content"] == "孙承宗暂听候政，三月后复试。"
    assert due["due_turn"] == state.turn
    assert "到期待裁" in due["review_reason"]

    _settle_empty_month(db, state, content)
    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert row["closed_turn"] is None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='expire'",
        (issue_id,),
    ).fetchone()[0] == 0


def test_semantically_empty_one_shot_commitment_surfaces_and_acks_once(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="语义空持续效果的复试承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:semantic-empty-review",
        bar_value=0,
        inertia=0,
        stage_text="三月后复试，不设月度动作。",
        ongoing_effects={"economy": []},
        stop_condition="",
        end_turn=state.turn,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    due_payload = build_simulator_payload(state, db, "", "")
    assert [
        item for item in due_payload["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ]

    _settle_empty_month(db, state, content)
    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert row["closed_turn"] is None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='expire'",
        (issue_id,),
    ).fetchone()[0] == 0

    out = apply_score_extraction(
        db,
        state,
        {
            "close_issues": [
                {
                    "issue_id": issue_id,
                    "reason": "acknowledged",
                    "narrative": "皇帝已复试，此承诺已由圣裁收尾。",
                }
            ]
        },
        content=content,
    )
    assert out["issue_summary"]["closes"][0]["rejected"] is False
    assert _issue_row(db, issue_id)["status"] == "dropped"
    after_ack = build_simulator_payload(state, db, "", "")
    assert [
        item for item in after_ack["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ] == []

    _settle_empty_month(db, state, content)
    next_month = build_simulator_payload(state, db, "", "")
    assert [
        item for item in next_month["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ] == []


def test_metadata_only_one_shot_commitment_surfaces_and_acks_once(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="占位持续效果的复试承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:placeholder-review",
        bar_value=0,
        inertia=0,
        stage_text="三月后复试，占位字段不代表月度动作。",
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": 0, "reason": "占位"},
            ],
        },
        stop_condition="",
        end_turn=state.turn,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    due_payload = build_simulator_payload(state, db, "", "")
    assert [
        item for item in due_payload["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ]

    _settle_empty_month(db, state, content)
    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    assert row["closed_turn"] is None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='expire'",
        (issue_id,),
    ).fetchone()[0] == 0

    out = apply_score_extraction(
        db,
        state,
        {
            "close_issues": [
                {
                    "issue_id": issue_id,
                    "reason": "acknowledged",
                    "narrative": "皇帝已复试，此占位承诺已由圣裁收尾。",
                }
            ]
        },
        content=content,
    )
    assert out["issue_summary"]["closes"][0]["rejected"] is False
    assert _issue_row(db, issue_id)["status"] == "dropped"
    after_ack = build_simulator_payload(state, db, "", "")
    assert [
        item for item in after_ack["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ] == []


def test_due_one_shot_commitment_ack_closes_review_loop_without_effects(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()
    starting_turn = state.turn
    starting_popular_support = int(state.metrics["民心"])

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="孙承宗三月后复试收尾",
        origin_kind="decree",
        origin_ref="decree:turn-1:sun-review-ack",
        bar_value=0,
        inertia=0,
        stage_text="孙承宗暂听候政，三月后复试。",
        ongoing_effects={},
        effect_on_resolve={"metrics": {"民心": 9}},
        effect_on_fail={"metrics": {"民心": -7}},
        stop_condition="",
        end_turn=starting_turn + 1,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    before_due = build_simulator_payload(state, db, "", "")
    assert [
        item for item in before_due["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ] == []

    _settle_empty_month(db, state, content)
    due_payload = build_simulator_payload(state, db, "", "")
    assert [
        item for item in due_payload["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ]

    out = apply_score_extraction(
        db,
        state,
        {
            "close_issues": [
                {
                    "issue_id": issue_id,
                    "reason": "acknowledged",
                    "narrative": "皇帝已复试孙承宗，此承诺已由圣裁处理。",
                }
            ]
        },
        content=content,
    )

    close = out["issue_summary"]["closes"][0]
    assert close["rejected"] is False
    row = _issue_row(db, issue_id)
    assert row["status"] == "dropped"
    assert row["closed_turn"] == state.turn
    assert "圣裁处理" in row["resolution_summary"]
    assert int(state.metrics["民心"]) == starting_popular_support
    advances = db.conn.execute(
        "SELECT trigger_kind, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert [(row["trigger_kind"], json.loads(row["metric_delta"])) for row in advances] == [
        ("commitment_ack", {}),
    ]

    after_ack = build_simulator_payload(state, db, "", "")
    assert [
        item for item in after_ack["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ] == []

    _settle_empty_month(db, state, content)
    next_month = build_simulator_payload(state, db, "", "")
    assert [
        item for item in next_month["due_commitments"]
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") == issue_id
    ] == []
