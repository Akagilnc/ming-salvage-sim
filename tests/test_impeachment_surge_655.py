"""#655 弹劾潮当前切片：动态候选适配器与 transformed 真源腿。

Confirmed seams: build_simulator_payload candidate_events; apply_issue_tracker_output new_issues.
"""
import json

import ming_sim.agents as agents_mod
from ming_sim.db import GameDB
from ming_sim.issues import apply_issue_tracker_output, gather_impeachment_surge_candidates, issue_to_payload
from ming_sim.models import LLMConfig
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload


def _candidate_world(db, state):
    chars = db.conn.execute(
        "SELECT name,faction FROM characters WHERE status='active' AND COALESCE(faction,'')<>'' ORDER BY name"
    ).fetchall()
    owner = next(row for row in chars if row["faction"])
    did = db.create_decree_dossier(
        state, action_type="policy", decree_text="清丈", target_kind="issue", target_id="land",
        executor_kind="character", executor_id=owner["name"],
        participants=[{"character_id": owner["name"], "tier": "主办"}],
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed',execution_outcome='transformed',closed_turn=? WHERE id=?",
        (state.turn, did),
    )
    db.conn.execute(
        "UPDATE factions SET leverage=60 WHERE name<>?", (owner["faction"],),
    )
    db.conn.commit()
    return did, str(owner["name"]), str(owner["faction"])


def test_transformed_fact_is_projected_as_namespaced_candidate(game):
    db, state = game[:2]
    did, owner, owner_faction = _candidate_world(db, state)

    candidates = gather_impeachment_surge_candidates(state, db)
    assert candidates
    item = candidates[0]
    assert item["id"].startswith("impeachment_surge:commitment:")
    assert item["origin_ref"] == f"commitment:{did}:deformation_exposure"
    assert item["source_kind"] == "deformation_exposure"
    assert item["occurred_turn"] == state.turn
    assert item["participant_ids"] == [owner]
    assert item["responsible_person_ids"] == [owner]
    assert owner_faction in item["responsible_faction_ids"]
    assert item["faction_persona"]["character_personas"]
    payload = build_simulator_payload(state, db, "", "")
    assert item not in payload["candidate_events"]
    assert all(not str(event["id"]).startswith("impeachment_surge:") for event in payload["candidate_events"])
    issues_context = build_extractor_shared_context(db, state, "", "", module="issues")
    assert item in issues_context["candidate_events"]
    assert "impeachment_surge_candidates" not in issues_context
    facts = db.build_faction_denunciation_facts()
    assert all(int(row["dossier_id"]) != did for row in facts["forked_dossiers"])


def test_production_issues_agent_carries_dynamic_source_contract_to_apply(game, content, monkeypatch):
    db, state = game[:2]
    did, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    agents_mod.bind_content(content)
    monkeypatch.setattr(agents_mod, "_llm_for_role", lambda config, role: config)
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *args, **kwargs: object())
    monkeypatch.setattr(agents_mod, "tlog", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents_mod, "Agent", lambda **kwargs: kwargs)

    agent = agents_mod.create_score_extractor_module_agent(
        LLMConfig(api_key="test", base_url="https://example.invalid/v1", model="test"),
        object(),
        module="issues",
    )
    instructions = "\n".join(agent["instructions"])
    assert 'origin_kind:"impeachment_surge"' in instructions
    assert "依据 `faction_persona` 自主决定是否发难；不输出即不发难" in instructions
    assert "`title` 与 `stage_text` 由角色自由生成" in instructions
    assert "`eligible_target_ids`" in instructions
    assert "只允许两个来源" not in instructions

    output = {"new_issues": [{
        "origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
        "faction_hint": candidate["faction_id"],
        "target_roster": [owner],
        "title": "御史自拟弹章", "stage_text": "清丈案牵连渐明。",
    }]}
    accepted = apply_issue_tracker_output(db, state, output)["new_issues"][0]
    assert accepted["rejected"] is False
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (accepted["issue_id"],)).fetchone()
    assert row["origin_ref"] == f"commitment:{did}:deformation_exposure"
    assert row["title"] == "御史自拟弹章"
    assert row["stage_text"] == "清丈案牵连渐明。"
    assert row["bar_good_meaning"] == ""
    assert row["bar_bad_meaning"] == ""


def test_apply_accepts_only_current_candidate_closed_target_and_free_text(game):
    db, state = game[:2]
    did, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    output = {"new_issues": [{
        "origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
        "faction_hint": candidate["faction_id"],
        "target_roster": [owner],
        "title": "  自由题名  ", "stage_text": "原样案情。",
    }]}
    result = apply_issue_tracker_output(db, state, output)
    accepted = result["new_issues"][0]
    assert accepted["rejected"] is False
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (accepted["issue_id"],)).fetchone()
    assert row["origin_ref"] == f"commitment:{did}:deformation_exposure"
    assert row["title"] == "  自由题名  "
    assert row["stage_text"] == "原样案情。"

    duplicate = apply_issue_tracker_output(db, state, output)["new_issues"][0]
    assert duplicate["rejected"] is True


def test_dynamic_apply_rejects_blank_title_wrong_faction_and_outside_target(game):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    base = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"],
            "target_roster": [owner],
            "title": "题", "stage_text": "情"}
    bad = [dict(base, title="  "), dict(base, faction_hint="伪派"),
           dict(base, target_roster=["不存在"])]
    result = apply_issue_tracker_output(db, state, {"new_issues": bad})["new_issues"]
    assert all(item["rejected"] for item in result)
    assert db.conn.execute("SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'").fetchone()[0] == 0


def test_dynamic_targets_are_roleless_deduplicated_without_participant_roles(game):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    base = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"], "title": "合法题名", "stage_text": "合法案情"}

    result = apply_issue_tracker_output(db, state, {"new_issues": [
        dict(base, target_roster=[{"character_id": owner, "tier": "主办"}]),
        dict(base, target_roster=[owner, owner]),
    ]})["new_issues"]

    assert result[0]["rejected"] is True
    assert result[1]["rejected"] is False
    row = db.conn.execute(
        "SELECT participants,participant_roster,target_roster FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()
    assert json.loads(row["participants"]) == []
    assert json.loads(row["participant_roster"]) == []
    assert json.loads(row["target_roster"]) == [owner]
    knowledge = db.conn.execute(
        "SELECT participant_roster FROM character_knowledge_sources WHERE source_id=?",
        (f"issue:{result[1]['issue_id']}",),
    ).fetchone()
    assert json.loads(knowledge["participant_roster"]) == []


def test_dynamic_apply_deduplicates_same_candidate_within_input_snapshot(game):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    item = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"], "target_roster": [owner],
            "title": "同批弹章", "stage_text": "同一候选重复输出"}

    result = apply_issue_tracker_output(
        db, state, {"new_issues": [item, item]},
        impeachment_surge_candidates_at_input=[candidate],
    )["new_issues"]

    assert result[0]["rejected"] is False
    assert result[1]["rejected"] is True
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()[0] == 1


def test_target_roster_survives_generic_issue_restore(game, content):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    item = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"], "target_roster": [owner],
            "title": "恢复标靶", "stage_text": "关库后仍可读"}
    issue_id = apply_issue_tracker_output(
        db, state, {"new_issues": [item]},
        impeachment_surge_candidates_at_input=[candidate],
    )["new_issues"][0]["issue_id"]
    path = db.conn.execute("PRAGMA database_list").fetchone()[2]
    db.close()

    restored = GameDB(path, content)
    try:
        row = restored.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        payload = issue_to_payload(row, [])
        assert payload["target_roster"] == [owner]
        assert json.loads(row["participants"]) == []
        assert json.loads(row["participant_roster"]) == []
    finally:
        restored.close()


def test_dynamic_apply_rejects_non_text_free_fields_without_coercion(game):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    base = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"],
            "target_roster": [owner],
            "title": "题", "stage_text": "情"}

    result = apply_issue_tracker_output(db, state, {"new_issues": [
        dict(base, title={"bad": "shape"}),
        dict(base, stage_text=["bad"]),
    ]})["new_issues"]

    assert all(item["rejected"] for item in result)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()[0] == 0


def test_leverage_boundary_and_authoritative_input_snapshot(game):
    db, state = game[:2]
    _, owner, owner_faction = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    db.conn.execute("UPDATE factions SET leverage=59 WHERE name=?", (candidate["faction_id"],))
    db.conn.commit()
    assert candidate["id"] not in {c["id"] for c in gather_impeachment_surge_candidates(state, db)}
    db.conn.execute("UPDATE factions SET leverage=60 WHERE name=?", (candidate["faction_id"],))
    db.conn.commit()
    item = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"],
            "target_roster": [owner],
            "title": "发难", "stage_text": "案情"}
    rejected = apply_issue_tracker_output(
        db, state, {"new_issues": [item]}, candidate_event_ids_at_input=set(),
        candidate_event_ids_authoritative=True,
        impeachment_surge_candidates_at_input=[],
    )["new_issues"][0]
    assert rejected["rejected"] is True
    assert "输入快照" in rejected["reason"]

    accepted = apply_issue_tracker_output(
        db, state, {"new_issues": [item]}, candidate_event_ids_at_input=set(),
        candidate_event_ids_authoritative=True,
        impeachment_surge_candidates_at_input=[candidate],
    )["new_issues"][0]
    assert accepted["rejected"] is False


def test_transformed_candidate_fails_closed_outside_window_or_without_liability(game):
    db, state = game[:2]
    did, _, _ = _candidate_world(db, state)
    db.conn.execute("UPDATE decree_dossiers SET closed_turn=? WHERE id=?", (state.turn - 2, did))
    db.conn.commit()
    assert gather_impeachment_surge_candidates(state, db) == []
    db.conn.execute("UPDATE decree_dossiers SET closed_turn=?,participant_roster='[]' WHERE id=?", (state.turn, did))
    db.conn.commit()
    assert gather_impeachment_surge_candidates(state, db) == []
