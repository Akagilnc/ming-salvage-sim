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


def test_ordinary_entity_log_families_persist_origin_at_write_seam(game):
    db, state, content = game
    region_id = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    army_id = db.conn.execute("SELECT id FROM armies WHERE manpower > 0 LIMIT 1").fetchone()[0]
    power_id = db.conn.execute("SELECT id FROM powers WHERE id <> 'ming' LIMIT 1").fetchone()[0]
    person = db.conn.execute("SELECT name FROM characters LIMIT 1").fetchone()[0]

    issue_engine.apply_score_extraction(db, state, {
        "region_delta": {region_id: {"public_support": 1, "origin_ref": SPONTANEOUS}},
        "army_delta": {army_id: {"morale": 1, "origin_ref": SPONTANEOUS}},
        "power_updates": {power_id: {"leverage": 1, "origin_ref": SPONTANEOUS}},
        "人物变更": [{"name": person, "动作": "评定", "loyalty": 1,
                    "origin_ref": SPONTANEOUS}],
    }, content=content)

    for table in ("region_logs", "army_logs", "power_logs", "person_logs"):
        row = db.conn.execute(f"SELECT origin_ref FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None and row["origin_ref"] == SPONTANEOUS
