import json

from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction, commitment_progress_payload, show_active_issues
from ming_sim.simulation import _extractor_context_payload, build_simulator_payload


def _army_arrears(db, army_id: str) -> int:
    row = db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()
    assert row is not None
    return int(row["arrears"])


def _issue_row(db, issue_id: int):
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row is not None
    return row


def _settle_empty_month(db, state, content):
    before = state.turn
    settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1


def test_until_stop_arrears_commitment_settlement_oracle_resolves_with_restore(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=70 WHERE id='guanning'")
    db.conn.execute("UPDATE armies SET arrears=40 WHERE id='xuan_da'")
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
        effect_on_resolve={"metrics": {"民心": 9}},
        effect_on_fail={"metrics": {"民心": -9}},
        stop_condition="",
        end_turn=start_turn + 2,
        commitment_kind="until_stop",
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
                    "origin_ref": "decree:turn-1:missing-purpose",
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


def test_commitment_targeted_pay_still_uses_priority_arrears_pool(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=100 WHERE id='guanning'")
    db.conn.execute("UPDATE armies SET arrears=100 WHERE id='xuan_da'")
    state.metrics["国库"] = 500
    db.save_state(state)

    db.insert_issue(
        state,
        kind="initiative",
        title="带目标的补饷承诺仍按优先级",
        origin_kind="decree",
        origin_ref="decree:turn-1:targeted-pay",
        bar_value=0,
        inertia=0,
        ongoing_effects={
            "economy": [
                {
                    "account": "国库",
                    "delta": -50,
                    "reason": "补宣大名义但仍入欠饷池",
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

    assert _army_arrears(db, "guanning") == 50
    assert _army_arrears(db, "xuan_da") == 100


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
                    "origin_ref": "decree:turn-1:future-review",
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
