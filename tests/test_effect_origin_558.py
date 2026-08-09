from ming_sim import issues as issue_engine


SPONTANEOUS = "盘面自发"


def _promulgated_policy(db, state):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="兴修水利",
        target_kind="issue", target_id="origin-558",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")
    return dossier_id


def test_decree_driven_effect_without_any_origin_is_rejected(game):
    db, state, content = game
    _promulgated_policy(db, state)
    before = state.metrics["国库"]

    result = issue_engine.apply_score_extraction(db, state, {
        "economy_moves": [{
            "account": "国库", "delta": -7, "category": "无源支出",
        }],
    }, content=content)

    assert state.metrics["国库"] == before
    assert result["economy_moves_rejections"][0]["category"] == "missing_origin_ref"


def test_effect_origins_round_trip_and_missing_origin_is_rejected(game):
    db, state, content = game
    dossier_id = _promulgated_policy(db, state)
    before = state.metrics["国库"]

    result = issue_engine.apply_score_extraction(db, state, {
        "economy_moves": [
            {"account": "国库", "delta": -3, "category": "奉旨修渠",
             "origin_ref": f"dossier:{dossier_id}"},
            {"account": "国库", "delta": 2, "category": "市易自旺",
             "origin_ref": SPONTANEOUS},
            {"account": "国库", "delta": -7, "category": "无源支出"},
        ],
        "fiscal_creates": [{
            "key": "河工月费", "account": "国库", "direction": "expense",
            "init_value": 4, "origin_ref": f"dossier:{dossier_id}",
        }],
    }, content=content)

    assert state.metrics["国库"] == before - 1
    assert result["economy_moves_rejections"][0]["category"] == "missing_origin_ref"
    assert db.list_economy_moves_for_dossier(dossier_id)[0]["origin_ref"] == f"dossier:{dossier_id}"
    fiscal = db.list_fiscal_effects_for_dossier(dossier_id)
    assert {row["key"] for row in fiscal} == {"河工月费_base", "河工月费_rate"}
    assert {row["origin_ref"] for row in fiscal} == {f"dossier:{dossier_id}"}
    assert all(row["dossier_id"] is None for row in db.list_economy_moves_for_dossier(dossier_id))


def test_fabricated_origin_is_rejected_even_without_a_dossier(game):
    db, state, content = game
    before = state.metrics["国库"]

    result = issue_engine.apply_score_extraction(db, state, {
        "economy_moves": [{
            "account": "国库", "delta": -2, "category": "伪来源",
            "origin_ref": "fabricated:9",
        }],
        "fiscal_creates": [{
            "key": "伪科目", "account": "国库", "direction": "expense",
            "init_value": 2, "origin_ref": "fabricated:9",
        }],
    }, content=content)

    assert state.metrics["国库"] == before
    assert result["economy_moves_rejections"][0]["category"] == "invalid_origin_ref"
    assert result["fiscal_creates"][0]["category"] == "invalid_origin_ref"
    assert db.conn.execute("SELECT 1 FROM fiscal_config WHERE key LIKE '伪科目%'").fetchone() is None
