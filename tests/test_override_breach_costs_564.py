"""#564 强颁与毁约的确定性代价轨（ADR 0056）。"""

import json

import pytest

from ming_sim import issues
from ming_sim.applier import atomic


def _dossier(db, state, *, mode="ordinary", roster=None):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text="清丈畿辅",
        target_kind="issue", target_id="land-survey",
        payload={"mode": mode}, participants=roster or [],
    )


def _cost_events(db, dossier_id):
    return [dict(row) for row in db.conn.execute(
        "SELECT * FROM decree_cost_events WHERE dossier_id=? ORDER BY id",
        (int(dossier_id),),
    ).fetchall()]


def _sat(db, table, name):
    return db.conn.execute(
        f"SELECT satisfaction FROM {table} WHERE name=? ORDER BY region_id LIMIT 1"
        if table == "classes" else f"SELECT satisfaction FROM {table} WHERE name=?",
        (name,),
    ).fetchone()[0]


def _verdict(dossier_id, decision="rejected"):
    return {
        "dossier_id": dossier_id, "decision": decision,
        "blocked_layer": "six_offices", "reason": "清议封驳",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": "韩爌", "criteria_snapshot": {
            "imperial_authority_band": "强盛", "appointment_tenure": "",
            "authorization_ids": [], "endorsement_entry_ids": [],
        },
        "affected_parties": [
            {"kind": "class", "key": "士绅", "direction": "negative", "intensity": "strong"},
            {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "weak"},
        ],
    }


def test_force_land_survey_charges_three_costs_without_eunuch_reaction(game):
    db, state, _ = game
    dossier_id = _dossier(db, state)
    before = {k: _sat(db, t, k) for t, k in [("classes", "士绅"), ("factions", "东林"), ("factions", "阉党")]}
    authority = state.metrics["皇威"]
    db.apply_dossier_verdicts(state, [_verdict(dossier_id)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert _sat(db, "classes", "士绅") == max(0, before["士绅"] - 8)
    assert _sat(db, "factions", "东林") == max(0, before["东林"] - 4)
    assert _sat(db, "factions", "阉党") == before["阉党"]
    assert state.metrics["皇威"] == max(0, authority - 5)
    events = _cost_events(db, dossier_id)
    assert {(x["cost_kind"], x["target_kind"], x["target_id"]) for x in events} == {
        ("authority", "metric", "皇威"), ("satisfaction", "class", "士绅"),
        ("satisfaction", "faction", "东林"),
    }
    assert all(x["target_id"] != "阉党" for x in events)


def test_signed_reactions_use_typed_direction_not_narrative_words(game):
    db, state, _ = game
    dossier_id = _dossier(db, state, mode="midzhi")
    verdict = _verdict(dossier_id, decision="promulgated")
    verdict["reason"] = "东林震怒，士绅欣然"
    verdict["affected_parties"] = [
        {"kind": "faction", "key": "东林", "direction": "positive", "intensity": "weak"},
        {"kind": "class", "key": "士绅", "direction": "negative", "intensity": "strong"},
    ]
    before_faction = _sat(db, "factions", "东林")
    before_class = _sat(db, "classes", "士绅")
    db.apply_dossier_verdicts(state, [verdict])
    assert _sat(db, "factions", "东林") == min(100, before_faction + 4)
    assert _sat(db, "classes", "士绅") == max(0, before_class - 8)


def test_midzhi_rejection_charges_only_parties_and_stigma_then_force_only_authority(game):
    db, state, _ = game
    dossier_id = _dossier(db, state, mode="midzhi")
    authority = state.metrics["皇威"]
    db.apply_dossier_verdicts(state, [_verdict(dossier_id)])
    assert state.metrics["皇威"] == authority
    assert {x["cost_kind"] for x in _cost_events(db, dossier_id)} == {"satisfaction"}
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    assert state.metrics["皇威"] == max(0, authority - 5)
    assert len(_cost_events(db, dossier_id)) == 3


def test_midzhi_rejudgment_changed_party_list_has_group_level_idempotency(game):
    db, state, _ = game
    dossier_id = _dossier(db, state, mode="midzhi")
    first = _verdict(dossier_id)
    db.apply_dossier_verdicts(state, [first])
    before_new_party = _sat(db, "classes", "农民")
    db.record_dossier_decision(dossier_id, "hold")
    state.turn += 1
    db.conn.execute("UPDATE game_state SET turn=? WHERE id=1", (state.turn,))
    changed = _verdict(dossier_id)
    changed["affected_parties"] = [
        {"kind": "class", "key": "农民", "direction": "positive", "intensity": "strong"},
    ]

    db.apply_dossier_verdicts(state, [changed])

    assert _sat(db, "classes", "农民") == before_new_party
    assert len([row for row in _cost_events(db, dossier_id) if row["cost_kind"] == "satisfaction"]) == 2


def test_costs_are_idempotent_and_survive_restore(game):
    db, state, content = game
    dossier_id = _dossier(db, state, mode="midzhi")
    verdict = _verdict(dossier_id)
    db.apply_dossier_verdicts(state, [verdict])
    db.record_dossier_decision(dossier_id, "hold")
    state.turn += 1
    db.conn.execute("UPDATE game_state SET turn=? WHERE id=1", (state.turn,))
    db.apply_dossier_verdicts(state, [verdict])
    assert len(_cost_events(db, dossier_id)) == 2
    path = db.path
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        assert len(_cost_events(restored, dossier_id)) == 2
    finally:
        restored.close()


def test_force_then_breach_charges_each_real_entry_independently(game):
    db, state, _ = game
    dossier_id = _dossier(db, state, roster=[
        {"character_id": "倪元璐", "tier": "主办", "role": "总理"},
    ])
    db.apply_dossier_verdicts(state, [_verdict(dossier_id)])
    authority = state.metrics["皇威"]
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    after_force = _sat(db, "factions", "东林")

    assert db.breach_decree_dossier(state, dossier_id, reason="撤回成命") is True
    assert state.metrics["皇威"] == max(0, authority - 10)
    assert _sat(db, "factions", "东林") == max(0, after_force - 4)
    authority_events = [
        row for row in _cost_events(db, dossier_id)
        if row["cost_kind"] == "authority"
    ]
    assert {row["cost_identity"] for row in authority_events} == {"override", "breach"}


def test_breach_excludes_stale_minister_faction_from_costs(game):
    db, state, _ = game
    dossier_id = _dossier(db, state, roster=[
        {"character_id": "倪元璐", "tier": "主办", "role": "总理"},
    ])
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    db.conn.execute("UPDATE characters SET faction='旧党' WHERE name='倪元璐'")

    assert db.breach_decree_dossier(state, dossier_id) is True
    assert not any(
        event["cost_kind"] == "satisfaction"
        for event in _cost_events(db, dossier_id)
    )


def test_breach_skips_dead_but_records_living_inactive_relations(game, caplog):
    db, state, _ = game
    roster = [
        {"character_id": "徐光启", "tier": "主办", "role": "总理"},
        {"character_id": "毕自严", "tier": "主办", "role": "核账"},
    ]
    dossier_id = _dossier(db, state, roster=roster)
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    dead_faction = db.conn.execute(
        "SELECT faction FROM characters WHERE name='徐光启'"
    ).fetchone()[0]
    before_dead_faction = _sat(db, "factions", dead_faction)
    db.conn.execute("UPDATE characters SET status='dead' WHERE name='徐光启'")
    db.conn.execute("UPDATE characters SET status='inactive' WHERE name='毕自严'")

    assert db.breach_decree_dossier(state, dossier_id) is True
    targets = {row["target"] for row in db.get_relation_edge_events(event_kind="辜负")}
    assert "徐光启" not in targets
    assert "毕自严" in targets
    assert _sat(db, "factions", dead_faction) == max(0, before_dead_faction - 4)
    dead_faction_events = [
        row for row in _cost_events(db, dossier_id)
        if row["cost_kind"] == "satisfaction"
        and row["target_kind"] == "faction"
        and row["target_id"] == dead_faction
    ]
    assert [(row["delta"], row["cost_identity"]) for row in dead_faction_events] == [
        (-4, "breach")
    ]
    assert "跳过已故参与者徐光启" in caplog.text


def test_cancel_linked_issue_breaches_only_its_origin_dossier_once(game):
    db, state, _ = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="兴修河渠",
        target_kind="issue", target_id="river-works",
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    issue_id = db.insert_issue(
        state, kind="initiative", title="兴修河渠", origin_kind="decree",
        origin_ref=f"dossier:{dossier_id}", cancellable="decree",
    )
    authority = state.metrics["皇威"]
    popular_support = state.metrics["民心"]
    cancel = {"issue_id": issue_id, "narrative": "撤回成命", "applied_cost": {"metrics": {"民心": -9}}}

    issues.apply_issue_tracker_output(db, state, {"cancels": [cancel]})
    issues.apply_issue_tracker_output(db, state, {"cancels": [cancel]})

    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()[0] == "dropped"
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"
    assert state.metrics["皇威"] == max(0, authority - 5)
    assert state.metrics["民心"] == popular_support
    events = _cost_events(db, dossier_id)
    assert [(event["cost_kind"], event["cost_identity"]) for event in events] == [
        ("breach", "breach"), ("authority", "breach"),
    ]


@pytest.mark.parametrize(
    ("mode", "decision", "affected", "message"),
    [
        ("ordinary", "rejected", None, "affected_parties"),
        ("ordinary", "rejected", [], "affected_parties"),
        ("midzhi", "rejected", None, "affected_parties"),
        ("midzhi", "promulgated", [], "affected_parties"),
        ("ordinary", "promulgated", [
            {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "weak"},
        ], "affected_parties"),
    ],
)
def test_public_apply_rejects_invalid_mode_decision_reaction_shape_before_writes(
    game, mode, decision, affected, message,
):
    db, state, _ = game
    dossier_id = _dossier(db, state, mode=mode)
    verdict = _verdict(dossier_id, decision=decision) if decision == "rejected" else {
        "dossier_id": dossier_id, "decision": decision,
    }
    if affected is None:
        verdict.pop("affected_parties", None)
    else:
        verdict["affected_parties"] = affected

    with pytest.raises(ValueError, match=message):
        db.apply_dossier_verdicts(state, [verdict])

    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"


def test_legacy_persisted_reaction_severity_migrates_narrowly_and_idempotently(game):
    db, state, content = game
    dossier_id = _dossier(db, state)
    legacy = [{"kind": "faction", "key": "东林", "severity": "大怒", "note": "留存"},
              {"kind": "class", "key": "士绅", "severity": "不满"},
              {"kind": "class", "key": "农民", "severity": "高兴"}]
    db.conn.execute(
        "INSERT INTO decree_dossier_decisions(dossier_id,turn,decision,affected_parties_json) VALUES (?,?,?,?)",
        (dossier_id, state.turn, "rejected", json.dumps(legacy, ensure_ascii=False)),
    )
    pending = {"dossier_id": dossier_id, "decision": "rejected", "affected_parties": legacy}
    db.conn.execute(
        "INSERT INTO pending_promulgation_verdicts(turn,dossier_id,verdict_json) VALUES (?,?,?)",
        (state.turn, dossier_id, json.dumps(pending, ensure_ascii=False)),
    )

    db.conn.commit()
    path = db.path
    db.close()
    from ming_sim.db import GameDB
    reopened = GameDB(path, content)
    reopened.close()
    reopened = GameDB(path, content)
    try:
        saved = reopened.get_pending_promulgation_verdicts(state.turn)[0]["affected_parties"]
        assert saved[0] == {"kind": "faction", "key": "东林", "note": "留存", "direction": "negative", "intensity": "strong"}
        assert (saved[1]["direction"], saved[1]["intensity"]) == ("negative", "weak")
        assert saved[2]["severity"] == "高兴"
    finally:
        reopened.close()


def test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation(game, monkeypatch):
    db, state, _ = game
    dossier_id = _dossier(db, state, roster=[
        {"character_id": "倪元璐", "tier": "主办", "role": "总理"},
    ])
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    before = state.metrics["皇威"]
    monkeypatch.setattr(
        db, "record_relation_edge_event",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("after authority")),
    )

    with pytest.raises(RuntimeError, match="after authority"):
        db.breach_decree_dossier(state, dossier_id)

    assert state.metrics["皇威"] == before
    assert db.conn.execute("SELECT value FROM metrics WHERE key='皇威'").fetchone()[0] == before
    assert _cost_events(db, dossier_id) == []


def test_force_rejects_missing_or_stale_judge_reactions_before_any_cost(game):
    db, state, _ = game
    dossier_id = _dossier(db, state)
    db.apply_dossier_promulgation(
        state, dossier_id, "rejected", blocked_layer="six_offices", reason="封驳",
    )
    authority = state.metrics["皇威"]

    with pytest.raises(ValueError, match="当前回合.*affected_parties"):
        db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert state.metrics["皇威"] == authority
    assert _cost_events(db, dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"


def test_force_rejects_malformed_judge_reactions_before_any_cost(game):
    db, state, _ = game
    dossier_id = _dossier(db, state)
    db.apply_dossier_verdicts(state, [_verdict(dossier_id)])
    db.conn.execute(
        "UPDATE decree_dossier_decisions SET affected_parties_json='{}' "
        "WHERE dossier_id=? AND rescript_action=''",
        (dossier_id,),
    )
    authority = state.metrics["皇威"]

    with pytest.raises(ValueError, match="当前回合.*affected_parties"):
        db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert state.metrics["皇威"] == authority
    assert _cost_events(db, dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"


def test_force_rejects_old_only_judge_reactions_atomically(game):
    db, state, _ = game
    dossier_id = _dossier(db, state)
    db.apply_dossier_verdicts(state, [_verdict(dossier_id)])
    db.record_dossier_decision(dossier_id, "hold")
    state.turn += 1
    db.conn.execute("UPDATE game_state SET turn=? WHERE id=1", (state.turn,))
    db.record_dossier_decision(dossier_id, "rejected", blocked_layer="six_offices")
    authority = state.metrics["皇威"]

    with pytest.raises(ValueError, match="当前回合.*affected_parties"):
        db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert state.metrics["皇威"] == authority
    assert _cost_events(db, dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"


def test_commit_false_breach_rolls_back_with_later_cancellation_failure(game, monkeypatch):
    db, state, _ = game
    dossier_id = _dossier(db, state)
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    issue_id = db.insert_issue(state, kind="initiative", title="清丈", origin_kind="decree",
                               origin_ref=f"dossier:{dossier_id}", cancellable="decree")
    before = state.metrics["皇威"]
    monkeypatch.setattr(db, "cancel_issue", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("later")))
    with pytest.raises(RuntimeError, match="later"):
        with atomic(db):
            issues.apply_issue_tracker_output(db, state, {"cancels": [{"issue_id": issue_id}]})
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    assert _cost_events(db, dossier_id) == []
    # DB truth rolled back; caller reload owns the in-memory mirror.
    assert db.conn.execute("SELECT value FROM metrics WHERE key='皇威'").fetchone()[0] == before


def test_active_commitment_can_breach_closed_issued_dossier_but_not_never_issued(game):
    db, state, _ = game
    issued = _dossier(db, state)
    db.apply_dossier_promulgation(state, issued, "promulgated")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed',closed_turn=?,interruption_reason='旧结案' WHERE id=?",
        (state.turn, issued),
    )
    db.conn.commit()
    closed_turn = db.get_decree_dossier(issued)["closed_turn"]
    active = db.insert_issue(state, kind="initiative", title="旧诺", origin_kind="decree",
                             origin_ref=f"dossier:{issued}", cancellable="decree", commitment_kind="funding")
    never = _dossier(db, state)
    db.record_dossier_decision(never, "rejected")
    db.record_dossier_decision(never, "withdrawn")
    excluded = db.insert_issue(state, kind="initiative", title="未发之旨", origin_kind="decree",
                               origin_ref=f"dossier:{never}", cancellable="decree", commitment_kind="funding")

    issues.apply_issue_tracker_output(db, state, {"cancels": [{"issue_id": active}]})
    with pytest.raises(ValueError, match="canonical origin 非法"):
        issues.apply_issue_tracker_output(db, state, {"cancels": [{"issue_id": excluded}]})

    assert any(x["cost_kind"] == "breach" for x in _cost_events(db, issued))
    assert db.get_decree_dossier(issued)["closed_turn"] == closed_turn
    assert _cost_events(db, never) == []


def test_breach_charges_authority_ministers_and_related_factions_once(game):
    db, state, _ = game
    roster = [
        {"character_id": "徐光启", "tier": "主办", "role": "总理"},
        {"character_id": "毕自严", "tier": "协办", "role": "核账"},
        {"character_id": "倪元璐", "tier": "主办", "role": "清丈", "delegator_id": "徐光启"},
        {"character_id": "黄道周", "tier": "协办", "role": "清丈", "delegator_id": "毕自严"},
        {"character_id": "王承恩", "tier": "知情", "role": "知情"},
    ]
    dossier_id = _dossier(db, state, roster=roster)
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    authority = state.metrics["皇威"]
    assert db.breach_decree_dossier(state, dossier_id, reason="撤回成命") is True
    assert db.breach_decree_dossier(state, dossier_id, reason="重复撤回") is False
    assert state.metrics["皇威"] == max(0, authority - 5)
    edges = db.get_relation_edge_events(event_kind="辜负")
    assert {e["target"] for e in edges if e["origin"].startswith(f"dossier:{dossier_id}:breach")} == {
        "倪元璐", "徐光启", "毕自严",
    }
    assert not {"黄道周", "王承恩", "曹化淳"} & {e["target"] for e in edges}
    faction_targets = {e["target_id"] for e in _cost_events(db, dossier_id) if e["target_kind"] == "faction"}
    assert faction_targets == {"东林", "皇党", "西学"}
