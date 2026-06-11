"""PR2-S2(ADR 0008 决定 1,#91)——section 4 三条裸奔路迁入逐项拒收契约。

section 4 的 create_armies_from_extraction(new_armies)、apply_region_deltas
(region_delta)、apply_army_deltas(army_delta):原先脏项在 db 方法内要么直接
raise(坏一项崩整月,#63「崩整批」死法)、要么 print 静默跳。改为:LLM 脏数据
(查无此地/此军/字段非法/值不可解析)逐项拒收留痕,好项照落;代码异常(bug 类)
仍上抛 SettlementAbort 回滚整批。clamp 语义(region cannon city_level×8、army
cannon cap 12、firearm 0-100)保持——clamp 不是拒收,clamp 后照落。

经 driver.run_settle 端到端驱动(公共接口,与 test_power_section_rejections.py 同风格)。
"""

from __future__ import annotations

import pytest

from driver import run_settle


def _rejection_rows(db, turn, section=None):
    rows = db.conn.execute(
        "SELECT section, reason, category, source FROM rejection_reports"
        " WHERE turn=? ORDER BY id", (turn,)
    ).fetchall()
    if section is not None:
        rows = [r for r in rows if r[0] == section]
    return rows


def _a_region(db):
    """取一个开局在册地区 id,供「好项照落」对照。"""
    row = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert row is not None
    return row[0]


def _an_army(db):
    row = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    assert row is not None
    return row[0]


# ---- region_delta：查无此地 ----

def test_unknown_region_rejected_good_item_lands(game):
    """region_delta 引用未入库地区 → 该项逐项拒收留痕(不再 print 静默跳),
    同信封里合法地区的改动照常落库——坏一项不带走整批(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _a_region(db)
    before = db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "region_delta": {
            "查无此地郡": {"public_support": 3},
            good: {"public_support": 2},
        },
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "region_changes")
    assert len(rows) == 1
    _, reason, category, _ = rows[0]
    assert reason  # 人读原因非空
    assert category == "missing_ref"
    after = db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 好项照落


def test_illegal_region_field_rejected_sibling_lands(game):
    """region_delta 字段超出白名单 → 原 raise LLMContractError 崩整月,改为逐项
    拒收留痕(invalid_enum),同地区的合法字段照落(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _a_region(db)
    before = db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "region_delta": {good: {"public_support": 2, "查无此字段": 9}},
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "region_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]  # reason 非空
    after = db.conn.execute(
        "SELECT public_support FROM regions WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 兄弟好字段照落


@pytest.mark.parametrize("bad_value", [None, "三成", 3.7, True])
def test_dirty_region_value_rejected_sibling_lands(game, bad_value):
    """region_delta 白名单字段的脏叶子值(null/字符串/float/bool)= LLM 脏数据,
    裸 int(value) 会让一个脏值崩整月——改为逐项拒收(invalid_enum)。bool 是 int
    子类、float 静默截断,都不是 prompt 要的整数 delta,显式拒(对称 S1)。
    兄弟好字段照落。"""
    db, state, content = game
    turn = state.turn
    good = _a_region(db)
    before = db.conn.execute(
        "SELECT unrest FROM regions WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "region_delta": {good: {"public_support": bad_value, "unrest": 2}},
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "region_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    after = db.conn.execute(
        "SELECT unrest FROM regions WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 兄弟好字段照落


# ---- army_delta：查无此军 ----

def test_unknown_army_rejected_good_item_lands(game):
    """army_delta 引用未入库军队 → 原 raise ValueError 崩整月,改为逐项拒收留痕
    (missing_ref),同信封里合法军队的改动照落——坏一项不带走整批(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _an_army(db)
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "army_delta": {
            "查无此军营": {"morale": 3},
            good: {"morale": 2},
        },
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    _, reason, category, _ = rows[0]
    assert reason
    assert category == "missing_ref"
    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 好项照落


def test_illegal_army_field_rejected_sibling_lands(game):
    """army_delta 引用非法字段 → 原 print 静默跳,改为逐项拒收留痕(invalid_enum),
    同军队的合法字段照落(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _an_army(db)
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "army_delta": {good: {"morale": 2, "查无此字段": 9}},
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 兄弟好字段照落


@pytest.mark.parametrize("bad_value", [None, "几成", 3.7, True])
def test_dirty_army_value_rejected_sibling_lands(game, bad_value):
    """army_delta 数值字段的脏叶子值(null/字符串/float/bool)→ 逐项拒收(invalid_enum),
    不让裸 int(value) 崩整月;兄弟好字段照落(对称 S1/region)。"""
    db, state, content = game
    turn = state.turn
    good = _an_army(db)
    before = db.conn.execute(
        "SELECT training FROM armies WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "army_delta": {good: {"morale": bad_value, "training": 2}},
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "army_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    after = db.conn.execute(
        "SELECT training FROM armies WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 兄弟好字段照落


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

    rows = _rejection_rows(db, turn, "created_armies")
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
    """new_armies 缺/非法 manpower 或 maintenance_per_turn → 原 raise ValueError
    崩整月,改为逐项拒收留痕(invalid_enum),同信封好军照建(ADR 决定 1)。"""
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

    rows = _rejection_rows(db, turn, "created_armies")
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

    rows = _rejection_rows(db, turn, "created_armies")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]


# ---- 代码异常(bug 类,非脏数据)→ 上抛 SettlementAbort 回滚整批 ----

def test_region_deltas_code_exception_aborts_settlement(game, monkeypatch):
    """apply_region_deltas 内代码异常(bug 类)→ 上抛 SettlementAbort 回滚整批,
    绝不被吞(ADR 0005/决定 1)。"""
    from ming_sim.exceptions import SettlementAbort
    db, state, content = game
    good = _a_region(db)

    def _boom(self, *a, **k):
        raise AttributeError("code bug in apply_region_deltas")
    monkeypatch.setattr(type(db), "apply_region_deltas", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "region_delta": {good: {"public_support": 2}},
        }, narrative="x", decree_text="y")


def test_army_deltas_code_exception_aborts_settlement(game, monkeypatch):
    """apply_army_deltas 内代码异常 → 上抛 SettlementAbort 回滚整批,绝不被吞。"""
    from ming_sim.exceptions import SettlementAbort
    db, state, content = game
    good = _an_army(db)

    def _boom(self, *a, **k):
        raise KeyError("code bug in apply_army_deltas")
    monkeypatch.setattr(type(db), "apply_army_deltas", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "army_delta": {good: {"morale": 2}},
        }, narrative="x", decree_text="y")


def test_create_armies_code_exception_aborts_settlement(game, monkeypatch):
    """create_armies_from_extraction 内代码异常 → 上抛 SettlementAbort 回滚整批,绝不被吞。"""
    from ming_sim.exceptions import SettlementAbort
    db, state, content = game
    good_owner = _valid_power_id(db)

    def _boom(self, *a, **k):
        raise AttributeError("code bug in create_armies_from_extraction")
    monkeypatch.setattr(type(db), "create_armies_from_extraction", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "new_armies": [{"id": "x_corps", "owner_power": good_owner,
                            "manpower": 1000, "maintenance_per_turn": 1}],
        }, narrative="x", decree_text="y")


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


def test_region_army_formatters_skip_rejected_items():
    """report.format_region_changes / format_army_changes 遇到同列拒收项(无
    delta/label/region/army 键)不得 KeyError——拒收项不是盘面变化,只渲染 applied 项;
    全拒收时回落「未见变化」(S2 迁契约副作用守门,对称 S1)。"""
    from ming_sim.report import format_region_changes, format_army_changes

    out_r = format_region_changes([
        {"region_id": "查无此地", "rejected": True, "category": "missing_ref",
         "reason": "查无此地"},
        {"region": "山东", "field": "public_support", "label": "民心",
         "old": 50, "new": 52, "delta": 2, "reason": "推演"},
    ])
    assert "山东" in out_r and "查无此地" not in out_r

    out_a = format_army_changes([
        {"army_id": "查无此军", "rejected": True, "category": "missing_ref",
         "reason": "查无此军"},
        {"army": "京营", "field": "morale", "label": "士气",
         "old": 16, "new": 18, "delta": 2, "reason": "推演"},
    ])
    assert "京营" in out_a and "查无此军" not in out_a

    only_rej_r = format_region_changes([
        {"rejected": True, "category": "invalid_enum", "reason": "字段非法"}])
    assert "未见明确地区盘面变化" in only_rej_r
    only_rej_a = format_army_changes([
        {"rejected": True, "category": "invalid_enum", "reason": "字段非法"}])
    assert "未见明确军队盘面变化" in only_rej_a


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

    rows = _rejection_rows(db, turn, "created_armies")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
