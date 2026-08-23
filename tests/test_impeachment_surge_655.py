"""#655 弹劾潮当前切片：动态候选适配器与 transformed 真源腿。

Confirmed seams: build_simulator_payload candidate_events; apply_issue_tracker_output new_issues.
"""
import json

import ming_sim.agents as agents_mod
from ming_sim.issues import apply_issue_tracker_output, gather_impeachment_surge_candidates
from ming_sim.models import LLMConfig
from ming_sim.simulation import build_simulator_payload


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
    assert item in build_simulator_payload(state, db, "", "")["candidate_events"]


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
        "participant_roster": [{"character_id": owner, "tier": "主办"}],
        "title": "御史自拟弹章", "stage_text": "清丈案牵连渐明。",
    }]}
    accepted = apply_issue_tracker_output(db, state, output)["new_issues"][0]
    assert accepted["rejected"] is False
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (accepted["issue_id"],)).fetchone()
    assert row["origin_ref"] == f"commitment:{did}:deformation_exposure"
    assert row["title"] == "御史自拟弹章"
    assert row["stage_text"] == "清丈案牵连渐明。"


def test_apply_accepts_only_current_candidate_closed_target_and_free_text(game):
    db, state = game[:2]
    did, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    output = {"new_issues": [{
        "origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
        "faction_hint": candidate["faction_id"],
        "participant_roster": [{"character_id": owner, "tier": "主办"}],
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
            "participant_roster": [{"character_id": owner, "tier": "主办"}],
            "title": "题", "stage_text": "情"}
    bad = [dict(base, title="  "), dict(base, faction_hint="伪派"),
           dict(base, participant_roster=[{"character_id": "不存在", "tier": "主办"}])]
    result = apply_issue_tracker_output(db, state, {"new_issues": bad})["new_issues"]
    assert all(item["rejected"] for item in result)
    assert db.conn.execute("SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'").fetchone()[0] == 0


def test_dynamic_apply_rejects_invalid_roster_fields_without_losing_valid_sibling(game):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    delegator = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? ORDER BY name LIMIT 1", (owner,)
    ).fetchone()["name"]
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    base = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"],
            "participant_roster": [{"character_id": owner, "tier": "主办"}],
            "title": "  合法题名  ", "stage_text": "合法案情"}
    valid_roster = [{"character_id": owner, "tier": "主办",
                     "role": "具疏弹劾", "delegator_id": delegator}]

    result = apply_issue_tracker_output(db, state, {"new_issues": [
        dict(base, participant_roster=[{"character_id": owner, "tier": "首犯"}]),
        dict(base, participant_roster=[{"character_id": owner, "tier": "主办",
                                        "role": {"bad": "shape"}}]),
        dict(base, participant_roster=[{"character_id": owner, "tier": "主办",
                                        "delegator_id": ["bad"]}]),
        dict(base, participant_roster=[{"character_id": owner, "tier": "主办",
                                        "delegator_id": "不存在"}]),
        dict(base, participant_roster=valid_roster),
    ]})["new_issues"]

    assert all(item["rejected"] is True for item in result[:4])
    assert result[4]["rejected"] is False
    row = db.conn.execute(
        "SELECT title,stage_text,participant_roster FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()
    assert (row["title"], row["stage_text"]) == ("  合法题名  ", "合法案情")
    assert json.loads(row["participant_roster"]) == valid_roster


def test_dynamic_apply_rejects_non_text_free_fields_without_coercion(game):
    db, state = game[:2]
    _, owner, _ = _candidate_world(db, state)
    candidate = gather_impeachment_surge_candidates(state, db)[0]
    base = {"origin_kind": "impeachment_surge", "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"],
            "participant_roster": [{"character_id": owner, "tier": "主办"}],
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
            "participant_roster": [{"character_id": owner, "tier": "主办"}],
            "title": "发难", "stage_text": "案情"}
    rejected = apply_issue_tracker_output(
        db, state, {"new_issues": [item]}, candidate_event_ids_at_input=set(),
        candidate_event_ids_authoritative=True,
    )["new_issues"][0]
    assert rejected["rejected"] is True
    assert "输入快照" in rejected["reason"]


def test_transformed_candidate_fails_closed_outside_window_or_without_liability(game):
    db, state = game[:2]
    did, _, _ = _candidate_world(db, state)
    db.conn.execute("UPDATE decree_dossiers SET closed_turn=? WHERE id=?", (state.turn - 2, did))
    db.conn.commit()
    assert gather_impeachment_surge_candidates(state, db) == []
    db.conn.execute("UPDATE decree_dossiers SET closed_turn=?,participant_roster='[]' WHERE id=?", (state.turn, did))
    db.conn.commit()
    assert gather_impeachment_surge_candidates(state, db) == []
