"""faction_delta / class_delta 两段迁入逐项拒收契约（ADR 0008 决定 1，#14/#63）。

原先 `db.adjust_factions`/`adjust_classes` 对查无此派系/阶级名 `if not row: continue`
零痕迹静默丢（#63 死法 3、#14 模式 C），`_apply_*_dict` 对非整数值也 `continue` 静默跳
（#14 模式 A）。改为：未知名 → missing_ref 逐项拒收、坏值 → invalid_enum 逐项拒收，
好项照落、坏一项不带走整批；合法扁平 int / 0 增量仍照旧不误拒。

经 driver.run_settle 端到端驱动（公共接口，与 test_power_section_rejections.py 同风格）。
"""

from __future__ import annotations

from driver import run_settle


def _rejection_rows(db, turn, section):
    return db.conn.execute(
        "SELECT section, reason, category, source FROM rejection_reports"
        " WHERE turn=? AND section=? ORDER BY id", (turn, section)
    ).fetchall()


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


def test_unknown_faction_rejected_good_item_lands(game):
    """faction_delta 引用未入库派系 → 该项 missing_ref 逐项拒收留痕（不再静默 continue），
    同信封里合法派系的改动照常落库——坏一项不带走整批（ADR 决定 1）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)
    before = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "faction_delta": {"查无此派系": {"satisfaction": 5}, good: {"satisfaction": 7}},
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "faction_delta")
    assert len(rows) == 1, rows
    assert rows[0][2] == "missing_ref"
    assert rows[0][1]  # 人读原因非空
    after = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]
    assert after != before, "好项（合法派系）应照常落库"


def test_unknown_class_rejected_good_item_lands(game):
    """class_delta 引用未入库阶级 → missing_ref 逐项拒收留痕，合法阶级照落。"""
    db, state, content = game
    turn = state.turn
    good = _valid_class_key(db)

    run_settle(db, state, content, {
        "class_delta": {
            "查无此阶级": {"satisfaction": 5},
            good: {"satisfaction": 6},
        },
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "class_delta")
    assert len(rows) == 1, rows
    assert rows[0][2] == "missing_ref"
    assert rows[0][1]


def test_illegal_faction_value_rejected(game):
    """faction_delta 合法派系但 satisfaction 值非整数 → invalid_enum 逐项拒收留痕。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)

    run_settle(db, state, content, {
        "faction_delta": {good: {"satisfaction": "abc"}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, "faction_delta")
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows
    assert rows[0][1]


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

    assert _rejection_rows(db, turn, "faction_delta") == []
    after = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]
    assert after == max(0, before - 5)


def test_zero_delta_faction_not_rejected(game):
    """0 增量是合法 no-op，不当拒收（不误报）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)

    run_settle(db, state, content, {
        "faction_delta": {good: 0},
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "faction_delta") == []
