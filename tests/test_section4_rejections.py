"""PR2-S2(ADR 0008 决定 1,#91)——section 4 三条裸奔路迁入逐项拒收契约。

section 4 的 create_armies_from_extraction(new_armies)、apply_region_deltas
(region_delta)、apply_army_deltas(army_delta):原先脏项在 db 方法内要么直接
raise(坏一项崩整月,#63「崩整批」死法)、要么 print 静默跳。改为:LLM 脏数据
(查无此地/此军/字段非法/值不可解析)逐项拒收留痕,好项照落;代码异常(bug 类)
仍原样上抛并回滚原子分派。clamp 语义(region cannon city_level×8、army
cannon cap 12、firearm 0-100)保持——clamp 不是拒收,clamp 后照落。

从现役 pre_settle 与 dispatch_declaration 入口验证逐项拒收。
"""

from __future__ import annotations

from ming_sim.applier import Provenance

import pytest

from tests.section_rejection_helpers import rejection_rows as _rejection_rows, run_declaration


def run_settle(db, state, content, extracted, **kwargs):
    """These rejection tests model canonical spontaneous extractor envelopes."""
    for section in ("region_delta", "army_delta"):
        for item in (extracted.get(section) or {}).values():
            if isinstance(item, dict):
                item.setdefault("origin_ref", "盘面自发")
    for item in extracted.get("new_armies") or []:
        if isinstance(item, dict):
            item.setdefault("origin_ref", "盘面自发")
    return run_declaration(db, state, content, extracted)


def _a_region(db):
    """取一个开局在册地区 id,供「好项照落」对照。"""
    row = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert row is not None
    return row[0]


def _an_army(db):
    row = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    assert row is not None
    return row[0]


def _pay_source():
    return {
        "pay_source_region": "shaanxi",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }


# ---- 实体逐项拒收公共主干 ----

@pytest.mark.parametrize("delta_key,section,table,key_expr,where,good_field,bad_field,bad_target,bad_value,category", [
    (*entity, target, value, category)
    for entity in (
        ("region_delta", "region_changes", "regions", "id", "1", "public_support", "unrest"),
        ("army_delta", "army_changes", "armies", "id", "1", "morale", "training"),
        ("power_updates", "power_changes", "powers", "id", "id != 'ming'", "leverage", "military_strength"),
        ("faction_delta", "faction_delta", "factions", "name", "1", "satisfaction", "leverage"),
        ("class_delta", "class_delta", "classes", "name || '@' || region_id", "1", "satisfaction", "leverage"),
    )
    for target, value, category in (
        ("missing", 3, "missing_ref"), ("field", 3, "invalid_enum"),
        ("value", None, "invalid_enum"), ("value", "三成", "invalid_enum"),
        ("value", 3.7, "invalid_enum"), ("value", True, "invalid_enum"),
    )
    if target == "missing" or entity[0] in ("region_delta", "army_delta")
    or (entity[0] == "power_updates" and (target == "field" or value in (None, "三成")))
])
def test_entity_delta_rejection_keeps_valid_sibling(
    game, delta_key, section, table, key_expr, where, good_field, bad_field,
    bad_target, bad_value, category,
):
    """Mixed entity deltas share one dispatch and persisted-refusal contract."""
    db, state, content = game
    from ming_sim.decree import pre_settle
    pre_settle(state, db, content=content)
    if bad_target == "value":
        good_field, bad_field = bad_field, good_field
    key, before, bad_before = db.conn.execute(
        f"SELECT {key_expr}, {good_field}, {bad_field} FROM {table} WHERE {where} LIMIT 1"
    ).fetchone()
    origin = {} if delta_key in ("faction_delta", "class_delta") else {"origin_ref": "盘面自发"}
    good = {good_field: 2, **origin}
    if bad_target == "missing":
        delta = {"查无此实体": {bad_field: bad_value, **origin}, key: good}
        category = "hallucinated_id" if delta_key == "power_updates" else category
    else:
        delta = {key: {**good, "查无此字段" if bad_target == "field" else bad_field: bad_value}}
    run_declaration(db, state, content, {delta_key: delta})
    rows = _rejection_rows(db, state.turn, section)
    assert len(rows) == 1
    assert rows[0]["category"] == category
    assert rows[0]["reason"]
    after, bad_after = db.conn.execute(
        f"SELECT {good_field}, {bad_field} FROM {table} WHERE {key_expr}=?", (key,)
    ).fetchone()
    assert after == min(100, before + 2)
    assert bad_after == bad_before


@pytest.mark.parametrize("bad_controller", [None, "", "   ", "null", " NULL ", "not_a_real_power"])
def test_region_controlled_by_rejects_non_power_id_and_preserves_region(game, bad_controller):
    """region_delta.controlled_by 不是普通 text：必须是 powers.id 里真实、非空 power id。
    None/空白/null 文本/未知 id 都逐项拒收留痕，且不改地区控制权。"""
    db, state, content = game
    turn = state.turn
    good = _a_region(db)
    before = db.conn.execute(
        "SELECT controlled_by FROM regions WHERE id=?", (good,)
    ).fetchone()[0]

    run_settle(db, state, content, {
        "region_delta": {good: {"controlled_by": bad_controller}},
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "region_changes")
    assert len(rows) == 1
    _, reason, category, _ = rows[0]
    assert category == "invalid_enum"
    after = db.conn.execute(
        "SELECT controlled_by FROM regions WHERE id=?", (good,)
    ).fetchone()[0]
    assert after == before


def test_region_controlled_by_accepts_existing_power_ids_and_restore_hook(game):
    """合法 powers.id 仍可落库；非 ming→ming 收复时原 on_restore 覆盖逻辑仍触发。"""
    db, state, content = game
    rid = "jianzhou"
    region = db.conn.execute(
        "SELECT id, public_support FROM regions WHERE id=?", (rid,)
    ).fetchone()
    assert region is not None
    before_support = int(region["public_support"])
    turn = state.turn

    run_settle(db, state, content, {
        "region_delta": {rid: {"controlled_by": "ming"}},
    }, narrative="x", decree_text="y")

    row = db.conn.execute(
        "SELECT controlled_by, public_support FROM regions WHERE id=?", (rid,)
    ).fetchone()
    assert row["controlled_by"] == "ming"
    assert int(row["public_support"]) != before_support  # on_restore 覆盖仍生效
    log_fields = [
        r[0] for r in db.conn.execute(
            "SELECT field FROM region_logs WHERE turn=? AND region_id=? ORDER BY id",
            (turn, rid),
        ).fetchall()
    ]
    assert "controlled_by" in log_fields
    assert "public_support" in log_fields


def test_region_controlled_by_mixed_invalid_and_valid_siblings_apply(game):
    """坏 controlled_by 只拒该字段，不阻断同地区好字段和同批其它地区合法控制权变更。"""
    db, state, content = game
    turn = state.turn
    good = _a_region(db)
    other = db.conn.execute(
        "SELECT id FROM regions WHERE id <> ? LIMIT 1", (good,)
    ).fetchone()[0]
    before_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id=?", (good,)
    ).fetchone()[0]

    run_settle(db, state, content, {
        "region_delta": {
            good: {"controlled_by": "not_a_real_power", "unrest": 2},
            other: {"controlled_by": "houjin"},
        },
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "region_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    after_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id=?", (good,)
    ).fetchone()[0]
    other_controller = db.conn.execute(
        "SELECT controlled_by FROM regions WHERE id=?", (other,)
    ).fetchone()[0]
    assert after_unrest != before_unrest
    assert other_controller == "houjin"


# ---- army_delta：查无此军 ----


# ---- new_armies：建军脏项 ----

def _valid_power_id(db):
    row = db.conn.execute(
        "SELECT id FROM powers WHERE id != 'ming' LIMIT 1").fetchone()
    assert row is not None
    return row[0]


def test_unknown_owner_power_army_rejected_good_builds(game):
    """new_armies owner_power 不在 powers 表 → 原 raise ValueError 崩整月,改为逐项
    拒收留痕(hallucinated_id),同信封里合法 owner 的新军照建(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good_owner = _valid_power_id(db)

    run_settle(db, state, content, {
        "new_armies": [
            {"id": "ghost_corps", "name": "幽灵营", "owner_power": "查无此势力",
             "manpower": 5000, "maintenance_per_turn": 3},
            {"id": "good_corps_s2", "name": "新立营", "owner_power": good_owner,
             "manpower": 4000, "maintenance_per_turn": 2},
        ],
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    assert rows[0][2] == "hallucinated_id"
    assert rows[0][1]
    # 好项照建
    built = db.conn.execute(
        "SELECT id FROM armies WHERE id='good_corps_s2'").fetchone()
    assert built is not None
    # 坏项没落
    ghost = db.conn.execute(
        "SELECT id FROM armies WHERE id='ghost_corps'").fetchone()
    assert ghost is None


def test_army_missing_manpower_rejected_good_builds(game):
    """new_armies 缺/非法 manpower（#173 PR2 后唯一必填，维护费退役）→ 原 raise
    ValueError 崩整月,改为逐项拒收留痕(invalid_enum),同信封好军照建(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good_owner = _valid_power_id(db)

    run_settle(db, state, content, {
        "new_armies": [
            {"id": "halfbuilt_corps", "name": "半成营", "owner_power": good_owner,
             "manpower": "三千"},  # 非法 manpower + 缺 maintenance
            {"id": "good_corps_s2b", "name": "齐备营", "owner_power": good_owner,
             "manpower": 4000, "maintenance_per_turn": 2},
        ],
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    assert db.conn.execute(
        "SELECT id FROM armies WHERE id='good_corps_s2b'").fetchone() is not None
    assert db.conn.execute(
        "SELECT id FROM armies WHERE id='halfbuilt_corps'").fetchone() is None


def test_duplicate_army_without_manpower_rejected(game):
    """new_armies 命中已有 id/name 但无 manpower 增量 → 原 print 静默跳,改为逐项
    拒收留痕(invalid_enum,扩军无量=无意义项)(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    dup_id, dup_name = db.conn.execute(
        "SELECT id, name FROM armies LIMIT 1").fetchone()

    run_settle(db, state, content, {
        "new_armies": [{"id": dup_id, "name": dup_name, "owner_power": "ming"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]


# ---- 代码异常(bug 类,非脏数据)→ 原样上抛，原子分派回滚整批 ----

@pytest.mark.parametrize("method,section,table,field,error", [
    ("apply_region_deltas", "region_delta", "regions", "public_support", AttributeError),
    ("apply_army_deltas", "army_delta", "armies", "morale", KeyError),
    ("apply_power_deltas", "power_updates", "powers", "leverage", AttributeError),
    ("create_armies_from_extraction", "new_armies", "powers", None, AttributeError),
])
def test_entity_write_exception_aborts_dispatch(game, monkeypatch, method, section, table, field, error):
    db, state, content = game
    key = db.conn.execute(f"SELECT id FROM {table} WHERE id != 'ming' LIMIT 1").fetchone()[0]
    fault = error("entity write fault")

    def _boom(self, *args, **kwargs):
        raise fault

    monkeypatch.setattr(type(db), method, _boom)
    item = {key: {field: 2, "origin_ref": "盘面自发"}} if field else [
        {"id": "x_corps", "owner_power": key, "manpower": 1000,
         "maintenance_per_turn": 1, "origin_ref": "盘面自发"},
    ]
    with pytest.raises(error) as raised:
        run_declaration(db, state, content, {section: item})
    assert raised.value is fault


# ---- clamp 语义(P2 铁律):clamp 不是拒收,clamp 后照落 ----

def test_army_cannon_over_cap_clamps_not_rejected(game):
    """army cannon_equipment 超 cap 12 → clamp 后照落,不算拒收(P2 铁律保持)。"""
    db, state, content = game
    turn = state.turn
    good = _an_army(db)
    db.conn.execute("UPDATE armies SET cannon_equipment=0 WHERE id=?", (good,))
    db.conn.commit()

    run_settle(db, state, content, {
        "army_delta": {good: {"cannon_equipment": 99}},  # 远超 cap 12
    }, narrative="x", decree_text="y")

    # clamp 不是拒收
    rows = _rejection_rows(db, turn, "army_changes")
    assert rows == []
    after = db.conn.execute(
        "SELECT cannon_equipment FROM armies WHERE id=?", (good,)).fetchone()[0]
    assert after == 12  # clamp 后照落


def test_region_cannon_over_cap_clamps_not_rejected(game):
    """region cannon 超 cap city_level×8 → clamp 后照落,不算拒收(P2 铁律保持)。"""
    db, state, content = game
    turn = state.turn
    row = db.conn.execute(
        "SELECT id, city_level FROM regions WHERE city_level >= 1 LIMIT 1").fetchone()
    rid, city_level = row[0], row[1]
    cap = city_level * 8
    db.conn.execute("UPDATE regions SET cannon=0 WHERE id=?", (rid,))
    db.conn.commit()

    run_settle(db, state, content, {
        "region_delta": {rid: {"cannon": cap + 50}},  # 远超 cap
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "region_changes")
    assert rows == []
    after = db.conn.execute(
        "SELECT cannon FROM regions WHERE id=?", (rid,)).fetchone()[0]
    assert after == cap  # clamp 后照落,不超城防上限


def test_army_firearm_over_100_clamps_not_rejected(game):
    """army firearm_equipment 超 100 → clamp 后照落,不算拒收(P2 铁律 0-100 保持)。"""
    db, state, content = game
    turn = state.turn
    good = _an_army(db)
    db.conn.execute("UPDATE armies SET firearm_equipment=50 WHERE id=?", (good,))
    db.conn.commit()

    run_settle(db, state, content, {
        "army_delta": {good: {"firearm_equipment": 999}},  # 远超 100
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "army_changes")
    assert rows == []
    after = db.conn.execute(
        "SELECT firearm_equipment FROM armies WHERE id=?", (good,)).fetchone()[0]
    assert after == 100  # clamp 后照落


def test_duplicate_army_noninteger_manpower_rejected(game):
    """new_armies 命中已有 id 但 manpower 非整数 → 原 print 静默跳,改为逐项
    拒收留痕(invalid_enum)(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    dup_id, dup_name = db.conn.execute(
        "SELECT id, name FROM armies LIMIT 1").fetchone()

    run_settle(db, state, content, {
        "new_armies": [
            {"id": dup_id, "name": dup_name, "owner_power": "ming", "manpower": "若干"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]


# ───────────────────────── cmr S2 r1 修复回归 ─────────────────────────

@pytest.mark.parametrize("bad", [None, "数十门", 3.7, True])
def test_dirty_region_cannon_value_rejected_not_abort(game, bad):
    """cannon 分支 dispatch 在脏值守门之前,裸 int(value)——脏炮值崩整月+bool/float
    静默拟真(cmr S2 r1,3票 P1)。改逐项拒收;同地区好字段照落。"""
    db, state, content = game
    turn = state.turn
    rid = _a_region(db)

    run_settle(db, state, content, {
        "region_delta": {rid: {"cannon": bad, "public_support": 2}},
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "region_changes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    # 好字段照落
    log = db.conn.execute(
        "SELECT COUNT(*) FROM region_logs WHERE region_id=? AND field='public_support' AND turn=?",
        (rid, turn)).fetchone()[0]
    assert log == 1


def test_dirty_optional_army_field_rejects_item(game):
    """new_armies 可选数值字段在场但脏(morale '高'→静默 50)= 伪造军备——
    在场即须合法,拒该项留痕;缺省才走默认(cmr S2 r1 codex P1)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "new_armies": [{"id": "dirty_morale_army", "name": "脏士气军", "owner_power": "ming",
                        "manpower": 5000, "maintenance_per_turn": 2, "morale": "高"}],
    }, narrative="x", decree_text="y")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM armies WHERE id='dirty_morale_army'").fetchone()[0] == 0
    rows = [r for r in _rejection_rows(db, turn) if r[0] == "army_changes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"


def test_absent_optional_army_fields_use_defaults(game):
    """缺省可选字段照走默认(50/0)——「在场即须合法」不影响缺省路(pin)。"""
    db, state, content = game

    run_settle(db, state, content, {
        "new_armies": [{"id": "default_army_ok", "name": "默认军", "owner_power": "ming",
                        "manpower": 5000, "maintenance_per_turn": 2, **_pay_source()}],
    }, narrative="x", decree_text="y")

    row = db.conn.execute(
        "SELECT morale, cannon_equipment FROM armies WHERE id='default_army_ok'").fetchone()
    assert row is not None
    assert row[0] == 50 and row[1] == 0


def test_nondict_new_army_item_recorded_not_silent(read_game):
    """new_armies 非 dict 项不再静默 continue——留拒收记录(issue 路容忍不升级,
    历史即静默;season 路本就被 validate_delta_shape 挡在 S6)(cmr S2 r1 P3)。"""
    db, state, _ = read_game
    created, created_rejections = db.create_armies_from_extraction(state, ["不是dict的项"], actor="测试", source=Provenance.system_simulation)
    assert len(created_rejections) == 1
    assert created_rejections[0].category == "invalid_enum"


@pytest.mark.parametrize("field,bad", [("equipment", "精良"), ("mobility", "快"), ("loyalty", "高")])
def test_all_score_fields_guarded_on_creation(game, field, bad):
    """守门集从 ARMY_SCORE_FIELDS 派生——硬列 6 字段漏 equipment/mobility/loyalty,
    脏值仍静默 50(cmr S2 r2,2/2;集中化:字段表变了守门自动跟)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "new_armies": [{"id": f"guard_{field}_army", "name": f"守门{field}军",
                        "owner_power": "ming", "manpower": 5000,
                        "maintenance_per_turn": 2, field: bad}],
    }, narrative="x", decree_text="y")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM armies WHERE id=?", (f"guard_{field}_army",)
    ).fetchone()[0] == 0
    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1


def test_issue_path_tolerated_rejections_reach_reports(game):
    """issue 结案路的容忍拒收项不得蒸发——经 issue_summary 落
    rejection_reports(改前是 print,改后曾比 print 更静默=违「容忍+留痕」,
    cmr S2 r2,2/2)。"""
    import json as _json

    db, state, content = game
    turn = state.turn
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试容忍留痕", origin_kind="decree",
        origin_ref="", bar_value=50, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=0, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, cancellable="decree",
        effect_on_resolve={
            "army_delta": {aid: {"morale": 1, "士气大振": 9, "loyalty": True, "mobility": 3.7, "equipment": None}, "查无此军xyz": {"morale": 2}},
            "new_armies": [
                {"id": "req_a", "name": "需填军甲", "owner_power": "ming", "manpower": 3.7},
                {"id": "req_b", "name": "需填军乙", "owner_power": "ming", "manpower": "三千"},
                {"id": "req_c", "name": "需填军丙", "owner_power": "ming"},
                {"id": "req_d", "name": "需填军丁", "owner_power": "ming", "manpower": 5000, **_pay_source()},
            ],
        },
        effect_on_fail={}, resolve_condition="", fail_condition="",
    )
    db.conn.commit()
    before = db.conn.execute("SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]

    run_settle(db, state, content, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "issue_summary")
    assert {r[2] for r in rows} == {"invalid_enum", "missing_ref"}
    stored = db.conn.execute("SELECT item_json FROM rejection_reports WHERE turn=? AND section='issue_summary' AND category='missing_ref'", (turn,)).fetchone()
    assert _json.loads(stored[0])["army_id"] == "查无此军xyz"
    refused_items = [_json.loads(r[0]) for r in db.conn.execute("SELECT item_json FROM rejection_reports WHERE turn=? AND section='issue_summary'", (turn,))]
    assert {r.get("id") for r in refused_items if "id" in r} == {"req_a", "req_b", "req_c"}
    assert {r.get("field") for r in refused_items if r.get("army_id") == aid} == {"士气大振", "loyalty", "mobility", "equipment"}
    assert db.conn.execute("SELECT manpower FROM armies WHERE id='req_d'").fetchone()[0] == 5000
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()[0] == "resolved"
    assert db.conn.execute("SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0] == min(100, before + 1)


def test_inertia_natural_resolution_tolerated_rejection_no_crash(game):
    """inertia 自然推到 100 结案的 issue,其 effect 含容忍类脏项(army 非法字段)
    → 不得崩(tlog 留痕路在 issues.py 没 import 即 NameError 崩月,
    cmr S2 r3 claude P1)。好字段照落。"""
    import ming_sim.entities.issue.effects as I

    db, state, content = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]
    before = db.conn.execute("SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试惯性结案留痕", origin_kind="decree",
        origin_ref="", bar_value=99, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=5, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, cancellable="decree",
        effect_on_resolve={"army_delta": {aid: {"morale": 1, "士气大振": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
    )
    db.conn.commit()

    from ming_sim.situation_drift import apply_situation_monthly_drift
    apply_situation_monthly_drift(db, state)  # 不抛

    row = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row[0] == "resolved"
    after = db.conn.execute("SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]
    assert after == min(100, before + 1)  # 好字段照落

# --- ported from claude/1812-w4 (issue-path tolerance; skip obsolete formatter mix) ---

def test_issue_path_tolerates_previously_skipped_cases(game):
    """国策结案路对「历史上 print-skip」的三案(army 非法字段等)不升级为崩月
    ——S2 把它们改成拒收记录后,_raise_on_rejected 不得把历史可活的脏数据
    变成新的中断路(cmr S2 r1 claude P2:「维持原行为」当真)。好字段照落。"""
    import ming_sim.entities.issue.effects as I

    db, state, content = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]

    I._apply_issue_entities(db, state, {
        "army_delta": {aid: {"morale": 2, "士气大振": 1}},  # 非法字段,历史 print-skip
    }, "局势#测试结案")  # 不抛

    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]
    assert after == min(100, before + 2)  # 好字段照落
