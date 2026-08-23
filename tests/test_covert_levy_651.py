from ming_sim.covert_levy import (
    ENTRY_KIND, army_pay_fact_for_dossier,
    settle_exposure_from_canonical_actions, write_exposure_todos,
)
from ming_sim.decree import project_dossiers_for_simulator
from ming_sim.due_review import audience_todo_lane, build_due_review_input, list_due_review_scenes
from ming_sim.simulation import EMPTY_EXTRACTION, MODULE_FIELDS, build_extractor_shared_context
from ming_sim.beat_orchestration import assemble_beat_inputs, BEAT_OPEN


def _bound_case(db, state):
    army = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    executor = db.conn.execute("SELECT name FROM characters WHERE status='active' LIMIT 1").fetchone()[0]
    did = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="整饬边军",
        target_kind="army", target_id=army["id"], executor_kind="character", executor_id=executor,
    )
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,))
    cur = db.conn.execute(
        "INSERT INTO issues(kind,title,origin_ref,origin_turn,commitment_kind) VALUES ('差务','边军事',?,?, 'promise')",
        (f"dossier:{did}", state.turn),
    )
    return did, int(cur.lastrowid), str(army["id"]), str(executor)


def test_pay_fact_uses_monthly_durable_counter_and_no_new_extractor_wrapper(game):
    db, state, _ = game
    did, _, army_id, _ = _bound_case(db, state)
    db.conn.execute(
        "UPDATE armies SET arrears=7, consecutive_pay_shortfall_months=2 WHERE id=?", (army_id,)
    )
    assert army_pay_fact_for_dossier(db, did) == {
        "army_id": army_id, "arrears": 7.0, "consecutive_pay_shortfall_months": 2,
    }
    assert "covert_levy_verdicts" not in EMPTY_EXTRACTION
    assert "covert_levy_decisions" not in EMPTY_EXTRACTION
    assert all("covert_levy_verdicts" not in fields and "covert_levy_decisions" not in fields
               for fields in MODULE_FIELDS.values())


def test_exposure_uses_single_dispatcher_and_projects_exact_case(game, monkeypatch):
    db, state, _ = game
    did, issue_id, _, executor = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    db.conn.execute(
        "INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) VALUES (?,?, '稽核','查账')",
        (did, did),
    )
    assert write_exposure_todos(db, state) == 1
    todo = db.list_next_audience_todos(status="pending")[0]
    assert audience_todo_lane(ENTRY_KIND) == "covert_levy"
    scene = list_due_review_scenes(db, state)[0]
    assert scene["kind"] == ENTRY_KIND
    assert scene["dossier_id"] == did and scene["executor_id"] == executor
    assert scene["channels"] == ["稽核"]
    assert scene["scene_text"] == ""  # audience LLM receives facts, not a fixed memorial
    beat = assemble_beat_inputs(db, state, beat_kind=BEAT_OPEN)
    assert beat.audience_scenes and f'"dossier_id": {did}' in beat.audience_scenes[0]
    assert build_due_review_input(db, todo)["commitment_ref"] == issue_id


def test_pay_fact_reaches_both_production_judge_inputs(game):
    db, state, _ = game
    did, _, army_id, _ = _bound_case(db, state)
    db.conn.execute(
        "UPDATE armies SET arrears=9, consecutive_pay_shortfall_months=3 WHERE id=?", (army_id,)
    )
    rows = [dict(r) for r in db.list_decree_dossiers_for_simulation(state.turn)]
    simulator = project_dossiers_for_simulator(rows, db, state)
    sim_row = next(row for row in simulator if row["id"] == did)
    assert sim_row["army_pay_fact"]["consecutive_pay_shortfall_months"] == 3
    issues = build_extractor_shared_context(
        db, state, "", "", module="issues", decree_dossiers=simulator,
    )
    issue_row = next(row for row in issues["decree_dossiers"] if row["id"] == did)
    assert issue_row["army_pay_fact"] == sim_row["army_pay_fact"]
    internal = build_extractor_shared_context(
        db, state, "", "", module="internal", decree_dossiers=simulator,
    )
    internal_row = next(row for row in internal["decree_dossiers"] if row["id"] == did)
    assert internal_row["army_pay_fact"] == sim_row["army_pay_fact"]


def test_rejected_canonical_results_neither_consume_nor_create_channel(game, monkeypatch):
    db, state, _ = game
    did, _, _, _ = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    db.conn.execute(
        "INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) "
        "VALUES (?,?, '稽核','查账')", (did, did),
    )
    assert write_exposure_todos(db, state, {}) == 1
    rejected = {
        "dossier_executions": [{"rejected": True, "item": {"dossier_id": did, "outcome": "failed"}}],
        "population_transfers": [{"rejected": True, "origin_ref": f"dossier:{did}", "reason": "摊派"}],
    }
    assert settle_exposure_from_canonical_actions(db, state, rejected) == 0
    assert db.list_next_audience_todos(status="pending")
    # With no audit/denunciation, a rejected transfer cannot manufacture unrest exposure.
    db.conn.execute("DELETE FROM next_audience_todos")
    db.conn.execute("DELETE FROM decree_dossier_links")
    assert write_exposure_todos(db, state, rejected) == 0


def test_covert_consumer_requires_real_beyond_intent_effect_without_narrowing_generic_fork(game):
    db, state, _ = game
    did, _, _, _ = _bound_case(db, state)
    db.record_dossier_progress(did, state.turn, "有成", "饷事已有眉目", commit=False)
    db.record_dossier_execution(did, "transformed", "暗中摊派", state.turn, close=False, commit=False)
    assert db.read_dossier_fork_state(did)["fork"] is True  # shared #622/#627 contract
    db.conn.execute(
        "INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) "
        "VALUES (?,?, '稽核','查账')", (did, did),
    )
    assert write_exposure_todos(db, state) == 0  # #651 additionally requires actual effect


def test_dispositions_require_their_complete_canonical_consequence(game, monkeypatch):
    db, state, _ = game
    did, _, _, executor = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    db.conn.execute("INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) VALUES (?,?, '稽核','查账')", (did, did))
    assert write_exposure_todos(db, state) == 1
    origin = f"dossier:{did}"
    # A transfer alone is not tacit permission: the same case needs a durable beyond-intent leg.
    assert settle_exposure_from_canonical_actions(db, state, {"population_transfers": [
        {"origin_ref": origin, "reason": "摊派"}]}) == 0
    assert db.list_next_audience_todos(status="pending")
    # Investigation needs both a disposition of the case actor and its relationship/event cost.
    assert settle_exposure_from_canonical_actions(db, state, {"applied_person_changes": [
        {"name": executor, "动作": "处置"}]}) == 0
    assert settle_exposure_from_canonical_actions(db, state, {
        "applied_person_changes": [{"name": executor, "动作": "处置"}],
        "relation_edge_events": [{"source": executor, "target": "朝臣",
                                  "origin": f"{origin}:relation:结怨|round:{state.turn}"}],
    }) == 1


def test_prohibition_reopens_shortfall_once_without_reoffering_dispositions(game, monkeypatch):
    db, state, _ = game
    did, _, _, _ = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    db.conn.execute(
        "INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) "
        "VALUES (?,?, '稽核','查账')", (did, did),
    )
    assert write_exposure_todos(db, state) == 1
    applied = {"dossier_executions": [{"dossier_id": did, "outcome": "failed"}]}
    assert settle_exposure_from_canonical_actions(db, state, applied) == 1
    assert settle_exposure_from_canonical_actions(db, state, applied) == 0
    scene = list_due_review_scenes(db, state)[0]
    assert scene["decision"] == "禁摊派"
    assert scene["shortfall_reopened"] is True
    assert scene["available_dispositions"] == []


def test_population_transfer_is_the_self_grown_unrest_channel(game, monkeypatch):
    db, state, _ = game
    did, _, _, _ = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    extracted = {"population_transfers": [{
        "origin_ref": f"dossier:{did}", "reason": "摊派", "source": "农民@shaanxi",
        "target": "流民@shaanxi", "amount": 1,
    }]}
    assert write_exposure_todos(db, state, extracted) == 1
    todo = db.list_next_audience_todos(status="pending")[0]
    assert todo["payload_json"]["channels"] == ["民变自长"]
