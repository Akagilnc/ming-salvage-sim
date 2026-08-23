import json

from ming_sim.covert_levy import (
    ENTRY_KIND, PROHIBITION_ACTION, active_prohibition_dossier,
    army_pay_fact_for_dossier, settle_exposure_from_canonical_actions,
    write_exposure_todos,
)
from ming_sim.decree import project_dossiers_for_simulator
from ming_sim.issues import apply_score_extraction
from ming_sim.due_review import audience_todo_lane, build_due_review_input, list_due_review_scenes
from ming_sim.simulation import EMPTY_EXTRACTION, MODULE_FIELDS, build_extractor_shared_context
from ming_sim.beat_orchestration import assemble_beat_inputs, BEAT_OPEN
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from types import SimpleNamespace


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


def test_natural_prohibition_binds_only_current_case_and_is_night_approved(game, monkeypatch):
    db, state, _ = game
    first, _, first_army, actor = _bound_case(db, state)
    second, _, _, _ = _bound_case(db, state)
    _exposed_todo(db, state, monkeypatch, first)
    _exposed_todo(db, state, monkeypatch, second)
    db.conn.execute("UPDATE armies SET arrears=5 WHERE id=?", (first_army,))
    candidates = candidates_from_classifier_payload(
        [{"kind": "prohibit_covert_levy"}], soft=False,
    )
    ctx = MaterializeCtx(
        session=SimpleNamespace(db=db, state=state),
        character=SimpleNamespace(name=actor),
        player_message="此等借饷扰民之举，即刻禁绝。", reply="臣领旨。",
        message_text="此等借饷扰民之举，即刻禁绝。", explicit_prefixed=False,
        has_directive=False, pend_for_minister=[], out={}, intent=None,
        intent_kind="none", llm_config=None, intent_candidates=candidates,
    )
    run_materialize_pipeline(ctx)
    pending = db.conn.execute(
        "SELECT payload_json,night_approved FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()
    import json
    payload = json.loads(pending["payload_json"])
    assert payload["dossier_action_type"] == PROHIBITION_ACTION
    assert payload["target_kind"] == "dossier" and payload["target_id"] == str(first)
    assert pending["night_approved"] == 1
    assert ctx.out["suppress_confirmation_cue"] is True


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


def _exposed_todo(db, state, monkeypatch, did):
    db.conn.execute(
        "UPDATE decree_dossiers SET promulgation_decision='promulgated' WHERE id=?", (did,)
    )
    db.record_dossier_progress(did, state.turn, "有成", "军饷已有着落", commit=False)
    db.record_dossier_execution(did, "transformed", "暗中摊派", state.turn, close=True, commit=False)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    db.conn.execute(
        "INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) "
        "VALUES (?,?, '稽核','查账')", (did, did),
    )
    assert write_exposure_todos(db, state) == 1


def test_dispositions_consume_only_real_canonical_complete_legs(game, monkeypatch):
    db, state, content = game
    did, _, army_id, executor = _bound_case(db, state)
    _exposed_todo(db, state, monkeypatch, did)
    origin = f"dossier:{did}"
    other = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name<>? LIMIT 1", (executor,)
    ).fetchone()[0]

    # 查办：关系代价单独成功仍不结算；人物腿也真实成功后才结算。
    partial = apply_score_extraction(db, state, {"relation_edge_events": [{
        "来源引用": origin, "施动者": executor, "受动者": [other],
        "类目": "结怨", "语境": "查办暗渠触动同僚",
    }]}, content, None, dossier_ids_at_input={did})
    assert partial["relation_edge_event_resolutions"]
    assert not partial["relation_edge_event_resolutions"][0].get("rejected")
    assert settle_exposure_from_canonical_actions(db, state, partial) == 0
    complete = apply_score_extraction(db, state, {"人物变更": [{
        "origin_ref": origin, "name": executor, "动作": "处置", "status": "dismissed",
    }]}, content, None, dossier_ids_at_input={did})
    complete["relation_edge_event_resolutions"] = partial["relation_edge_event_resolutions"]
    assert complete["applied_person_changes"]
    assert settle_exposure_from_canonical_actions(db, state, complete) == 1


def _promulgated_prohibition(db, state, exposed_id):
    prohibition_id = db.create_decree_dossier(
        state, action_type=PROHIBITION_ACTION, decree_text="严禁借饷摊派于民",
        target_kind="dossier", target_id=exposed_id,
        executor_kind="character", executor_id="王承恩",
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed', promulgation_decision='promulgated' WHERE id=?",
        (prohibition_id,),
    )
    return prohibition_id


def test_tacit_and_prohibition_use_real_canonical_identity_and_are_idempotent(game, monkeypatch):
    db, state, content = game
    did, _, army_id, _ = _bound_case(db, state)
    _exposed_todo(db, state, monkeypatch, did)
    origin = f"dossier:{did}"
    key = next(iter(db.get_fiscal_config()))
    db.conn.execute("UPDATE armies SET arrears=10 WHERE id=?", (army_id,))

    # An unrelated ordinary fiscal receipt must not impersonate the terminal order.
    unrelated = apply_score_extraction(db, state, {"fiscal_changes": [{
        "key": key, "delta": 1, "origin_ref": origin, "beyond_intent": False,
    }]}, content, None)
    assert unrelated["fiscal_changes"] and not unrelated["fiscal_changes"][0].get("rejected")
    assert settle_exposure_from_canonical_actions(db, state, unrelated) == 0
    prohibition_id = _promulgated_prohibition(db, state, did)
    assert active_prohibition_dossier(db, did)["id"] == prohibition_id
    assert settle_exposure_from_canonical_actions(db, state, {}) == 1
    assert settle_exposure_from_canonical_actions(db, state, {}) == 0
    scene = list_due_review_scenes(db, state)[0]
    assert scene["decision"] == "禁摊派" and scene["shortfall_reopened"] is True
    assert scene["available_dispositions"] == []
    beat = assemble_beat_inputs(db, state, beat_kind=BEAT_OPEN)
    assert beat.audience_scenes
    reminder = json.loads(beat.audience_scenes[0])
    assert reminder["decision"] == "禁摊派"
    assert reminder["army_pay_fact"]["arrears"] == 10.0
    assert reminder["available_dispositions"] == []
    assert {
        "criterion_text", "channels", "fork", "gap_text", "statement_text",
        "origin_context", "scene_text",
    }.isdisjoint(reminder)

    # Reuse the same fixture for tacit permission: both canonical legs are required.
    did2, _, _, _ = _bound_case(db, state)
    _exposed_todo(db, state, monkeypatch, did2)
    origin2 = f"dossier:{did2}"
    tacit = apply_score_extraction(db, state, {
        "population_transfers": [{
            "source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 1,
            "reason": "摊派", "origin_ref": origin2,
        }],
        "fiscal_changes": [{
            "key": key, "delta": 1, "origin_ref": origin2, "beyond_intent": True,
        }],
    }, content, None, dossier_ids_at_input={did2})
    assert tacit["population_transfers"] and tacit["fiscal_changes"]
    assert settle_exposure_from_canonical_actions(db, state, {
        **tacit, "fiscal_changes": [],
    }) == 0
    assert settle_exposure_from_canonical_actions(db, state, tacit) == 1


def test_prohibition_consumes_immediately_when_arrears_are_already_zero(game, monkeypatch):
    db, state, _ = game
    did, _, army_id, _ = _bound_case(db, state)
    _exposed_todo(db, state, monkeypatch, did)
    db.conn.execute("UPDATE armies SET arrears=0 WHERE id=?", (army_id,))
    _promulgated_prohibition(db, state, did)

    assert settle_exposure_from_canonical_actions(db, state, {}) == 1
    assert db.list_next_audience_todos(status="pending") == []
    assert assemble_beat_inputs(db, state, beat_kind=BEAT_OPEN).audience_scenes == ()


def test_prohibition_reminder_is_consumed_after_later_payoff(game, monkeypatch):
    db, state, _ = game
    did, _, army_id, _ = _bound_case(db, state)
    _exposed_todo(db, state, monkeypatch, did)
    db.conn.execute("UPDATE armies SET arrears=6 WHERE id=?", (army_id,))
    _promulgated_prohibition(db, state, did)

    assert settle_exposure_from_canonical_actions(db, state, {}) == 1
    assert assemble_beat_inputs(db, state, beat_kind=BEAT_OPEN).audience_scenes
    db.conn.execute("UPDATE armies SET arrears=0 WHERE id=?", (army_id,))
    assert settle_exposure_from_canonical_actions(db, state, {}) == 1
    assert db.list_next_audience_todos(status="pending") == []
    assert assemble_beat_inputs(db, state, beat_kind=BEAT_OPEN).audience_scenes == ()


def test_prohibition_blocks_every_covert_write_but_preserves_ordinary_legs(game):
    db, state, content = game
    did, _, army_id, _ = _bound_case(db, state)
    other_did, _, _, _ = _bound_case(db, state)
    origin, other_origin = f"dossier:{did}", f"dossier:{other_did}"
    key = next(iter(db.get_fiscal_config()))
    setup = apply_score_extraction(db, state, {"fiscal_creates": [
        {"key": "待禁裁项", "account": "国库", "direction": "income", "init_value": 2,
         "origin_ref": origin, "beyond_intent": True},
        {"key": "普通裁项", "account": "国库", "direction": "income", "init_value": 2,
         "origin_ref": origin},
    ], "fiscal_changes": [
        {"key": key, "delta": 1, "origin_ref": origin, "beyond_intent": True},
    ]}, content, None, dossier_ids_at_input={did})
    assert all(not item.get("rejected") for item in setup["fiscal_creates"])
    historical_rows = list(db.list_fiscal_effects_for_dossier(did))
    db.conn.execute("UPDATE armies SET arrears=8 WHERE id=?", (army_id,))
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES "
        "('__army_pay_source_cutover',0,'meta','test') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    _promulgated_prohibition(db, state, did)

    result = apply_score_extraction(db, state, {
        "fiscal_removes": [
            {"key": "待禁裁项", "origin_ref": origin, "beyond_intent": True},
            {"key": "普通裁项", "origin_ref": origin, "reason": "摊派"},
        ],
        "fiscal_creates": [
            {"key": "待禁新项", "account": "国库", "direction": "income", "init_value": 2,
             "origin_ref": origin, "beyond_intent": True},
            {"key": "普通新项", "account": "国库", "direction": "income", "init_value": 2,
             "origin_ref": origin, "reason": "摊派"},
        ],
        "fiscal_changes": [
            {"key": key, "delta": 1, "origin_ref": origin, "beyond_intent": True},
            {"key": key, "delta": 1, "origin_ref": other_origin, "beyond_intent": True},
            {"key": key, "delta": 1, "origin_ref": origin, "reason": "摊派"},
        ],
        "economy_moves": [
            {"account": "国库", "delta": 1, "origin_ref": origin, "beyond_intent": True},
            {"account": "国库", "delta": 1, "origin_ref": other_origin, "beyond_intent": True},
            {"account": "国库", "delta": 1, "origin_ref": origin, "reason": "摊派"},
            {"account": "国库", "delta": -2, "purpose": "补饷", "target_kind": "army",
             "target_id": army_id, "origin_ref": origin},
        ],
        "population_transfers": [
            {"source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 1,
             "reason": "摊派", "origin_ref": origin},
            {"source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 1,
             "reason": "加派", "origin_ref": origin},
        ],
    }, content, None, dossier_ids_at_input={did, other_did})

    for lane in ("fiscal_removes", "fiscal_creates", "fiscal_changes"):
        assert result[lane][0].get("category") == "forbidden_effect", (lane, result[lane])
    assert result["economy_moves_rejections"][0]["category"] == "forbidden_effect"
    assert all(not item.get("rejected") for item in result["fiscal_changes"][1:])
    assert len(result["economy_moves"]) == 3
    assert not result["fiscal_removes"][1].get("rejected")
    assert not result["fiscal_creates"][1].get("rejected")
    assert result["population_transfers_rejections"][0]["category"] == "forbidden_effect"
    assert len(result["population_transfers"]) == 1
    assert db.get_fiscal_config().get("待禁裁项_base") == 2
    assert db.get_fiscal_config().get("待禁新项_base") is None
    current_rows = {
        (row["effect_kind"], row["id"]): row
        for row in db.list_fiscal_effects_for_dossier(did)
    }
    assert all(current_rows[(row["effect_kind"], row["id"])] == row for row in historical_rows)
    assert db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()[0] == 6


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
