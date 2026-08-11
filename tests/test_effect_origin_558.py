import shutil
import sqlite3

from ming_sim import issues as issue_engine
from ming_sim.db import GameDB


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


def test_issue_close_effects_inherit_parent_canonical_origin(game):
    db, state, content = game
    dossier_id = _promulgated_policy(db, state)
    origin = f"dossier:{dossier_id}"
    region_id = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="父案卷来源贯穿",
        origin_kind="decree",
        origin_ref=origin,
        effect_on_resolve={
            "economy": [{"account": "国库", "delta": -1, "category": "父案卷支出"}],
            "buildings": [{
                "action": "create", "region_id": region_id, "name": "父案卷工坊",
                "category": "科技",
            }],
            "region_delta": {region_id: {"public_support": 1}},
        },
    )

    result = issue_engine.apply_score_extraction(
        db, state,
        {"close_issues": [{"issue_id": issue_id, "reason": "resolved"}]},
        content=content,
    )

    close = result["issue_summary"]["closes"][0]
    assert close["building_ops"][0]["name"] == "父案卷工坊"
    assert db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE category='父案卷支出'"
    ).fetchone()["origin_ref"] == origin
    assert db.conn.execute(
        "SELECT origin_ref FROM building_logs WHERE building_id=?",
        (close["building_ops"][0]["building_id"],),
    ).fetchone()["origin_ref"] == origin
    assert db.conn.execute(
        "SELECT origin_ref FROM region_logs WHERE region_id=? ORDER BY id DESC LIMIT 1",
        (region_id,),
    ).fetchone()["origin_ref"] == origin


def test_same_issue_row_inertia_and_ongoing_reuse_parent_canonical_origin(game):
    db, state, content = game
    dossier_id = _promulgated_policy(db, state)
    origin = f"dossier:{dossier_id}"
    region_id = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="惯性与持续效果同月落账",
        origin_kind="decree",
        origin_ref=origin,
        bar_value=50,
        inertia=1,
        ongoing_effects={
            "economy": [{"account": "国库", "delta": -2, "category": "同月持续支出"}],
            "region_delta": {region_id: {"public_support": 1}},
        },
    )

    issue_engine.apply_issue_inertia_and_ongoing(db, state)

    row = db.conn.execute("SELECT bar_value, status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert (row["bar_value"], row["status"]) == (51, "active")
    assert db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE category='同月持续支出' ORDER BY id DESC LIMIT 1"
    ).fetchone()["origin_ref"] == origin
    assert db.conn.execute(
        "SELECT origin_ref FROM region_logs WHERE region_id=? ORDER BY id DESC LIMIT 1",
        (region_id,),
    ).fetchone()["origin_ref"] == origin


def test_fiscal_remove_keeps_durable_origin_tombstone(game):
    db, state, content = game
    dossier_id = _promulgated_policy(db, state)
    origin = f"dossier:{dossier_id}"
    db.create_fiscal_item("待裁月费", "国库", "expense", "待裁月费", 4,
                          origin_ref=origin)

    result = issue_engine.apply_score_extraction(db, state, {
        "fiscal_removes": [{"key": "待裁月费", "reason": "奉旨裁撤", "origin_ref": origin}],
    }, content=content)

    assert result["fiscal_removes"][0]["key"] == "待裁月费_base"
    assert db.conn.execute("SELECT 1 FROM fiscal_config WHERE key LIKE '待裁月费%'").fetchone() is None
    rows = db.conn.execute(
        "SELECT key, origin_ref, reason FROM fiscal_config_tombstones WHERE origin_ref=? ORDER BY key",
        (origin,),
    ).fetchall()
    assert [(r["key"], r["origin_ref"], r["reason"]) for r in rows] == [
        ("待裁月费_base", origin, "奉旨裁撤"),
        ("待裁月费_rate", origin, "奉旨裁撤"),
    ]


def test_legacy_economy_ledger_origin_backfill_uses_real_dossier_only(game, tmp_path):
    db, state, content = game
    valid_id = _promulgated_policy(db, state)
    legacy_path = tmp_path / "legacy-origin.db"
    db.conn.commit()
    shutil.copy2(db.path, legacy_path)
    conn = sqlite3.connect(legacy_path)
    conn.execute("ALTER TABLE economy_ledger DROP COLUMN origin_ref")
    conn.execute(
        "INSERT INTO economy_ledger (turn,year,period,account,delta,balance_after,category,reason,dossier_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (state.turn, state.year, state.period, "国库", -1, 0, "旧账", "有效案卷", valid_id),
    )
    conn.execute(
        "INSERT INTO economy_ledger (turn,year,period,account,delta,balance_after,category,reason,dossier_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (state.turn, state.year, state.period, "国库", -1, 0, "旧账", "悬空案卷", valid_id + 9999),
    )
    conn.commit()
    conn.close()

    migrated = GameDB(str(legacy_path), content)
    try:
        rows = migrated.conn.execute(
            "SELECT reason, origin_ref FROM economy_ledger WHERE reason IN ('有效案卷','悬空案卷') ORDER BY reason"
        ).fetchall()
        assert {r["reason"]: r["origin_ref"] for r in rows} == {
            "有效案卷": f"dossier:{valid_id}", "悬空案卷": "",
        }
    finally:
        migrated.close()


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


def test_power_backlash_from_allegiance_change_inherits_canonical_origin(game):
    db, state, content = game
    dossier_id = _promulgated_policy(db, state)
    origin_ref = f"dossier:{dossier_id}"
    person_row = db.conn.execute(
        "SELECT name, power_id FROM characters "
        "WHERE power_id <> 'ming' AND status='active' LIMIT 1"
    ).fetchone()
    assert person_row is not None
    person, old_power = person_row["name"], person_row["power_id"]

    result = issue_engine.apply_score_extraction(db, state, {
        "人物变更": [{
            "name": person, "动作": "易主", "new_power": "ming",
            "方式": "主动归附", "反噬": {old_power: {"leverage": -1}},
            "reason": "奉旨招抚后归附", "origin_ref": origin_ref,
        }],
    }, content=content)

    assert result["applied_person_changes"][0]["origin_ref"] == origin_ref
    power_log = db.conn.execute(
        "SELECT origin_ref FROM power_logs WHERE power_id=? ORDER BY id DESC LIMIT 1",
        (old_power,),
    ).fetchone()
    assert power_log is not None
    assert power_log["origin_ref"] == origin_ref


def test_missing_origins_are_rejected_at_entity_write_seams_without_logs(game):
    db, state, content = game
    region = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    army = db.conn.execute("SELECT id FROM armies WHERE manpower > 0 LIMIT 1").fetchone()[0]
    power = db.conn.execute("SELECT id FROM powers WHERE id <> 'ming' LIMIT 1").fetchone()[0]
    person = db.conn.execute("SELECT name FROM characters LIMIT 1").fetchone()[0]
    before = {
        table: db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("region_logs", "army_logs", "power_logs", "person_logs")
    }

    result = issue_engine.apply_score_extraction(db, state, {
        "region_delta": {region: {"public_support": 1}},
        "army_delta": {army: {"morale": 1}},
        "power_updates": {power: {"leverage": 1}},
        "人物变更": [{"name": person, "动作": "评定", "loyalty": 1}],
    }, content=content)

    assert result["region_changes"][0]["category"] == "missing_origin_ref"
    assert result["army_changes"][0]["category"] == "missing_origin_ref"
    assert result["power_changes"][0]["category"] == "missing_origin_ref"
    assert result["applied_person_changes"][0]["category"] == "missing_origin_ref"
    for table, count in before.items():
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count


def test_entity_origin_gate_does_not_replace_reference_shape_or_noop_classification(game):
    db, state, content = game
    region_id = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    before_logs = db.conn.execute("SELECT COUNT(*) FROM region_logs").fetchone()[0]

    result = issue_engine.apply_score_extraction(db, state, {
        "region_delta": {
            "not-a-region": {"unrest": 2},
            region_id: {"unrest": 0},
        },
        "new_armies": [{
            "id": "bad-origin-preflight", "name": "坏军", "owner_power": "ming",
            "manpower": 100, "morale": "高",
        }],
    }, content=content)

    assert result["region_changes"][0]["category"] == "missing_ref"
    assert result["created_armies"][0]["category"] == "invalid_enum"
    assert db.conn.execute("SELECT COUNT(*) FROM region_logs").fetchone()[0] == before_logs


def test_zero_manpower_origin_gate_matches_actual_arrears_writeoff(game):
    db, state, content = game
    row = db.conn.execute("SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()
    army_id = row["id"]
    db.conn.execute(
        "UPDATE armies SET manpower=0, arrears=5, province_pay_arrears=3, central_pay_arrears=2 WHERE id=?",
        (army_id,),
    )
    db.conn.execute(
        "INSERT OR REPLACE INTO fiscal_config (key,value,kind,note) VALUES "
        "('__army_pay_source_cutover',0,'meta','test legacy no-op')"
    )

    legacy_noop = issue_engine.apply_score_extraction(
        db, state, {"army_delta": {army_id: {"manpower": 0}}}, content=content
    )
    assert legacy_noop["army_changes"] == []
    assert db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()[0] == 5

    db.conn.execute(
        "UPDATE fiscal_config SET value=1 WHERE key='__army_pay_source_cutover'"
    )
    db.conn.execute("UPDATE armies SET owner_power='houjin' WHERE id=?", (army_id,))
    non_ming_noop = issue_engine.apply_score_extraction(
        db, state, {"army_delta": {army_id: {"manpower": 0}}}, content=content
    )
    assert non_ming_noop["army_changes"] == []
    assert db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()[0] == 5

    db.conn.execute("UPDATE armies SET owner_power='ming' WHERE id=?", (army_id,))
    writeoff = issue_engine.apply_score_extraction(
        db, state, {"army_delta": {army_id: {"manpower": 0}}}, content=content
    )
    assert writeoff["army_changes"][0]["category"] == "missing_origin_ref"
    assert db.conn.execute("SELECT arrears FROM armies WHERE id=?", (army_id,)).fetchone()[0] == 5

    valid_writeoff = issue_engine.apply_score_extraction(
        db, state,
        {"army_delta": {army_id: {"manpower": 0, "origin_ref": SPONTANEOUS}}},
        content=content,
    )
    assert valid_writeoff["army_changes"] == []
    arrears = db.conn.execute(
        "SELECT arrears, province_pay_arrears, central_pay_arrears FROM armies WHERE id=?",
        (army_id,),
    ).fetchone()
    assert tuple(arrears) == (0, 0, 0)
    log = db.conn.execute(
        "SELECT old_value, new_value, origin_ref FROM army_logs "
        "WHERE army_id=? AND field='arrears' ORDER BY id DESC LIMIT 1",
        (army_id,),
    ).fetchone()
    assert tuple(log) == ("5.0", "0.0", SPONTANEOUS)


def test_army_pay_source_classifies_before_origin_gate_and_never_writes_without_origin(game):
    db, state, content = game
    row = db.conn.execute(
        "SELECT * FROM armies WHERE owner_power='ming' AND is_tusi=0 AND self_funded_pay=0 LIMIT 1"
    ).fetchone()
    assert row is not None
    before = dict(row)
    before_logs = db.conn.execute("SELECT COUNT(*) FROM army_logs").fetchone()[0]

    invalid = issue_engine.apply_score_extraction(db, state, {
        "army_delta": {row["id"]: {"pay_source_region": "not-a-region"}},
    }, content=content)
    assert invalid["army_changes"][0]["category"] == "invalid_enum"

    proposed_province = 0.6 if float(row["province_pay_share"]) != 0.6 else 0.7
    missing = issue_engine.apply_score_extraction(db, state, {
        "army_delta": {row["id"]: {
            "province_pay_share": proposed_province,
            "central_pay_share": 1 - proposed_province,
        }},
    }, content=content)
    assert missing["army_changes"][0]["category"] == "missing_origin_ref"
    after = db.conn.execute("SELECT * FROM armies WHERE id=?", (row["id"],)).fetchone()
    for field in ("pay_source_region", "province_pay_share", "central_pay_share"):
        assert after[field] == before[field]
    assert db.conn.execute("SELECT COUNT(*) FROM army_logs").fetchone()[0] == before_logs
