"""#564 强颁与毁约的确定性代价轨（ADR 0056）。"""
import json


def _dossier(db, state, *, mode="ordinary", roster=None):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text="清丈畿辅",
        target_kind="issue", target_id="land-survey",
        payload={"mode": mode}, participants=roster or [],
    )


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
    events = db.list_decree_cost_events(dossier_id)
    assert {(x["cost_kind"], x["target_kind"], x["target_id"]) for x in events} == {
        ("authority", "metric", "皇威"), ("satisfaction", "class", "士绅"),
        ("satisfaction", "faction", "东林"), ("stigma", "dossier", str(dossier_id)),
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
    assert {x["cost_kind"] for x in db.list_decree_cost_events(dossier_id)} == {"satisfaction", "stigma"}
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    assert state.metrics["皇威"] == max(0, authority - 5)
    assert len(db.list_decree_cost_events(dossier_id)) == 4


def test_costs_are_idempotent_and_survive_restore(game):
    db, state, content = game
    dossier_id = _dossier(db, state, mode="midzhi")
    verdict = _verdict(dossier_id)
    db.apply_dossier_verdicts(state, [verdict])
    db.record_dossier_decision(dossier_id, "hold")
    state.turn += 1
    db.conn.execute("UPDATE game_state SET turn=? WHERE id=1", (state.turn,))
    db.apply_dossier_verdicts(state, [verdict])
    assert len(db.list_decree_cost_events(dossier_id)) == 3
    path = db.path
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        assert len(restored.list_decree_cost_events(dossier_id)) == 3
    finally:
        restored.close()


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
    faction_targets = {e["target_id"] for e in db.list_decree_cost_events(dossier_id) if e["target_kind"] == "faction"}
    assert faction_targets == {"东林", "皇党", "西学"}
