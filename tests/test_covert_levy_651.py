import pytest

from ming_sim.issues import apply_score_extraction
from ming_sim.covert_levy import (
    ENTRY_KIND,
    apply_structured_decisions,
    build_covert_levy_candidates,
    materialize_structured_verdicts,
    write_exposure_todos,
)


def _bound_case(db, state):
    army = db.conn.execute(
        "SELECT id,manpower,salary_rate FROM armies WHERE manpower>0 AND salary_rate>0 LIMIT 1"
    ).fetchone()
    did = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="整饬边军",
        target_kind="army", target_id=army["id"],
    )
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,))
    db.conn.execute(
        "INSERT INTO issues(kind,title,origin_ref,origin_turn,commitment_kind) VALUES ('差务','边军事',?,?, 'promise')",
        (f"dossier:{did}", state.turn),
    )
    pay = float(army["manpower"]) * float(army["salary_rate"]) / 10000.0
    db.conn.execute("UPDATE armies SET arrears=? WHERE id=?", (pay * 3, army["id"]))
    return did, str(army["id"]), pay


def test_candidate_is_bound_to_concrete_dossier_army_and_three_real_months(game):
    db, state, _ = game
    did, army_id, pay = _bound_case(db, state)
    candidates = build_covert_levy_candidates(db)
    assert candidates == [pytest.approx({
        "dossier_id": did, "army_id": army_id, "arrears": pay * 3,
        "monthly_pay": pay, "suspended_months": 3.0,
    })]
    db.conn.execute("UPDATE armies SET arrears=? WHERE id=?", (pay * 2.99, army_id))
    assert build_covert_levy_candidates(db) == []


def test_structured_verdict_splits_report_from_canonical_actual_effects(game):
    db, state, _ = game
    did, _, _ = _bound_case(db, state)
    extracted = {"covert_levy_verdicts": [{
        "dossier_id": did, "formed": True,
        "report": {"progress_band": "有成", "memorial_text": "军饷已有着落"},
        "economy_move": {"account": "内库", "delta": 2, "category": "地方输纳", "reason": "解饷"},
        "population_transfer": {"source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 1},
    }]}
    materialize_structured_verdicts(db, state, extracted)
    assert db.list_dossier_progress(did)[-1]["memorial_text"] == "军饷已有着落"
    assert extracted["economy_moves"][0]["beyond_intent"] is True
    assert extracted["economy_moves"][0]["origin_ref"] == f"dossier:{did}"
    assert extracted["population_transfers"][0]["reason"] == "摊派"
    assert extracted["population_transfers"][0]["origin_ref"] == f"dossier:{did}"
    applied = apply_score_extraction(db, state, extracted, content=None, registry=None)
    assert not applied["population_transfers_rejections"]
    assert applied["population_transfers"][0]["reason"] == "摊派"


def test_exposure_requires_fork_and_real_channel_then_decision_consumes_exact_case(game, monkeypatch):
    db, state, _ = game
    did, _, _ = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    assert write_exposure_todos(db, state) == 0  # fork alone is not disclosure
    db.conn.execute(
        "INSERT INTO decree_dossier_links(source_dossier_id,target_dossier_id,relation_type,note) VALUES (?,?, '稽核','查账')",
        (did, did),
    )
    assert write_exposure_todos(db, state) == 1
    assert write_exposure_todos(db, state) == 0
    todo = db.list_next_audience_todos(status="pending")[0]
    assert todo["entry_kind"] == ENTRY_KIND
    assert todo["payload_json"]["dossier_id"] == did
    assert todo["payload_json"]["channels"] == ["稽核"]

    apply_structured_decisions(db, state, {"covert_levy_decisions": [
        {"dossier_id": did, "decision": "禁摊派"}
    ]})
    assert not db.list_next_audience_todos(status="pending")
    consumed = db.list_next_audience_todos(status="consumed")[0]
    assert consumed["payload_json"]["decision"] == "禁摊派"
    with pytest.raises(ValueError, match="无待裁"):
        apply_structured_decisions(db, state, {"covert_levy_decisions": [
            {"dossier_id": did, "decision": "默许"}
        ]})
