from __future__ import annotations
"""faction_delta / class_delta 两段逐项拒收契约及不同输入形状（ADR 0008 决定 1，#14/#63）。

原先 `db.adjust_factions`/`adjust_classes` 对查无此派系/阶级名 `if not row: continue`
零痕迹静默丢（#63 死法 3、#14 模式 C），`_apply_*_dict` 对非整数值也 `continue` 静默跳
（#14 模式 A）。改为：未知名 → missing_ref 逐项拒收、坏值（含 bool/float）→ invalid_enum
逐项拒收，好项照落、坏一项不带走整批；faction 合法扁平 int / 0 增量不误拒，
class 则只收嵌套字段 dict、扁平 int 逐项拒收。

经现役原子声明入口验证逐项拒收。
"""


import pytest

from tests.section_rejection_helpers import run_declaration as run_settle
from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows

FACTION_REJ_SECTION = "faction_delta"
CLASS_REJ_SECTION = "class_delta"


def _valid_faction(db):
    row = db.conn.execute("SELECT name FROM factions LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一个派系"
    return row[0]


def _valid_class_key(db):
    """取一个合法阶级 key（name 或 name@region_id），供「好项照落」对照。"""
    row = db.conn.execute(
        "SELECT name, region_id FROM classes LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一个阶级"
    name, region_id = row[0], row[1]
    return f"{name}@{region_id}" if region_id else name


def _class_satisfaction(db, key):
    name, region_id = (key.split("@", 1) + [""])[:2] if "@" in key else (key, "")
    return db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name=? AND region_id=?",
        (name.strip(), region_id.strip())).fetchone()[0]


@pytest.mark.parametrize("delta_key,section,table,key_expr,field,values", [
    (*entity, values)
    for entity in (
        ("class_delta", "class_delta", "classes", "name || '@' || region_id", "satisfaction"),
        ("faction_delta", "faction_delta", "factions", "name", "satisfaction"),
    )
    for values in ({"satisfaction": "abc"}, {"satisfaction": 3.7, "leverage": True})
] + [
    ("power_updates", "power_changes", "powers", "id", "military_strength",
     {"leverage": 3.7, "military_strength": True}),
])
def test_illegal_group_values_leave_row_unchanged(game, delta_key, section, table, key_expr, field, values):
    db, state, content = game
    from ming_sim.decree import pre_settle
    pre_settle(state, db, content=content)
    key, *before = db.conn.execute(
        f"SELECT {key_expr}, {field}, leverage FROM {table} WHERE {key_expr} != 'ming' LIMIT 1"
    ).fetchone()
    origin = {"origin_ref": "盘面自发"} if delta_key == "power_updates" else {}
    run_settle(db, state, content, {delta_key: {key: {**values, **origin}}})
    rows = _rejection_rows(db, state.turn, section)
    assert len(rows) == len(values)
    assert all(row["category"] == "invalid_enum" and row["reason"] for row in rows)
    assert list(db.conn.execute(
        f"SELECT {field}, leverage FROM {table} WHERE {key_expr}=?", (key,)
    ).fetchone()) == before


def test_valid_flat_int_faction_not_rejected(game):
    """合法扁平 int 格式 {派系: -5} 不误拒（extractor prompt 允许），且照常落库。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)
    before = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "faction_delta": {good: -5},
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, FACTION_REJ_SECTION) == []
    after = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]
    assert after == max(0, before - 5)


def test_flat_class_delta_rejected_while_nested_sibling_lands(game):
    """#564：同一真实结算信封内，扁平坏项不静默丢，也不带走嵌套好项。"""
    db, state, content = game
    turn = state.turn
    good = _valid_class_key(db)
    before = _class_satisfaction(db, good)
    assert 0 < before < 100, "开局阶级满意度需留有增量断言空间"

    run_settle(db, state, content, {
        "class_delta": {
            "扁平坏项": -4,
            good: {"satisfaction": 6},
        },
    }, narrative="x", decree_text="y")

    invalid_enum_rows = [
        row for row in _rejection_rows(db, turn, CLASS_REJ_SECTION)
        if row["category"] == "invalid_enum"
    ]
    assert len(invalid_enum_rows) == 1, invalid_enum_rows
    assert _class_satisfaction(db, good) == before + 6


def test_zero_delta_faction_not_rejected(game):
    """0 增量是合法 no-op，不当拒收（不误报）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)

    run_settle(db, state, content, {
        "faction_delta": {good: 0},
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, FACTION_REJ_SECTION) == []


def test_issue_effect_faction_rejection_reaches_reports(game):
    """局势 effect_on_resolve 里的 factions 引用未知派系 → 拒收经 issue_summary.rejected 落
    rejection_reports，不蒸发（与 test_issue_path_tolerated_rejections_reach_reports 同契约，
    cmr r2 codex：issue 路派系拒收原被 bare 调用丢弃，#14/#63）。"""
    db, state, content = game
    turn = state.turn
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试派系拒收留痕", origin_kind="decree",
        origin_ref="", bar_value=50, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=0, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={},
        effect_on_resolve={"factions": {"查无此派系": {"satisfaction": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
        cancellable="decree",
    )
    db.conn.commit()

    run_settle(db, state, content, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "issue_summary")
    rows = [r for r in rows if r[2] == "missing_ref"]
    assert len(rows) == 1, rows
    assert rows[0][1]  # reason 非空；不锁自由措辞
