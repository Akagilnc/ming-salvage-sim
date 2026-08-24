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

from tests.section_rejection_helpers import prepare_then_settle as _run_settle
from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows


def run_settle(db, state, content, extracted, **kwargs):
    """These rejection tests model canonical spontaneous extractor envelopes."""
    for section in ("region_delta", "army_delta"):
        for item in (extracted.get(section) or {}).values():
            if isinstance(item, dict):
                item.setdefault("origin_ref", "盘面自发")
    for item in extracted.get("new_armies") or []:
        if isinstance(item, dict):
            item.setdefault("origin_ref", "盘面自发")
    return _run_settle(db, state, content, extracted, **kwargs)


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
    assert "controlled_by" in reason
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
    rows = [r for r in _rejection_rows(db, turn) if r[0] == "created_armies"]
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


def test_issue_path_tolerates_previously_skipped_cases(game):
    """国策结案路对「历史上 print-skip」的三案(army 非法字段等)不升级为崩月
    ——S2 把它们改成拒收记录后,_raise_on_rejected 不得把历史可活的脏数据
    变成新的中断路(cmr S2 r1 claude P2:「维持原行为」当真)。好字段照落。"""
    import ming_sim.issues as I

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


def test_issue_path_still_strict_for_historically_fatal(read_game):
    """历史上就 raise 的类别(查无此军)在国策结案路保持严格(pin)。"""
    import ming_sim.issues as I

    db, state, _ = read_game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "army_delta": {"查无此军xyz": {"morale": 2}},
        }, "局势#测试结案")


def test_nondict_new_army_item_recorded_not_silent(read_game):
    """new_armies 非 dict 项不再静默 continue——留拒收记录(issue 路容忍不升级,
    历史即静默;season 路本就被 validate_delta_shape 挡在 S6)(cmr S2 r1 P3)。"""
    db, state, _ = read_game
    created = db.create_armies_from_extraction(state, ["不是dict的项"], actor="测试")
    rej = [c for c in created if c.get("rejected")]
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"


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
    rows = _rejection_rows(db, turn, "created_armies")
    assert len(rows) == 1


def test_issue_path_tolerated_rejections_reach_reports(game):
    """issue 结案路的容忍拒收项不得蒸发——经 issue_summary.entity_rejections 落
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
        tags=[], ongoing_effects={}, cancellable="decree", cancel_cost={},
        effect_on_resolve={"army_delta": {aid: {"morale": 1, "士气大振": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
    )
    db.conn.commit()

    run_settle(db, state, content, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "issue_summary.entity_rejections")
    assert len(rows) == 1
    assert "士气大振" in rows[0][1] or "非法字段" in rows[0][1]


def test_inertia_natural_resolution_tolerated_rejection_no_crash(game):
    """inertia 自然推到 100 结案的 issue,其 effect 含容忍类脏项(army 非法字段)
    → 不得崩(tlog 留痕路在 issues.py 没 import 即 NameError 崩月,
    cmr S2 r3 claude P1)。好字段照落。"""
    import ming_sim.issues as I

    db, state, content = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]
    before = db.conn.execute("SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试惯性结案留痕", origin_kind="decree",
        origin_ref="", bar_value=99, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=5, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, cancellable="decree", cancel_cost={},
        effect_on_resolve={"army_delta": {aid: {"morale": 1, "士气大振": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
    )
    db.conn.commit()

    I.apply_issue_inertia_and_ongoing(db, state, touched_ids=set())  # 不抛

    row = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row[0] == "resolved"
    after = db.conn.execute("SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()[0]
    assert after == min(100, before + 1)  # 好字段照落


def test_float_bool_army_delta_tolerated_on_issue_path(read_game):
    """army_delta 的 float/bool 叶在改前是静默套用(int(3.7)=3 照落)=历史可活
    ——issue 路不得升级为崩月;None/字符串历史就 raise,保持严格
    (cmr S2 r3,2/2:「仅限历史上本就 raise 的类别」当真)。"""
    import ming_sim.issues as I

    db, state, _ = read_game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]

    # float/bool:容忍(不抛,拒收留痕,不套用)
    I._apply_issue_entities(db, state, {
        "army_delta": {aid: {"morale": 3.7}},
    }, "局势#测试结案")  # 不抛

    # None:历史 int(None) TypeError → raise,保持严格
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "army_delta": {aid: {"morale": None}},
        }, "局势#测试结案")


def test_required_field_historical_strictness_on_issue_path(game):
    """#173 PR2 后建军唯一必填=manpower（维护费退役、不再必填）。issue 结案路对「历史
    可活」项容忍、对「历史致命」项保持严格 raise——谓词只看 manpower（原 cmr S2 r4 的
    「混合成因」防护随维护费退役而单字段化：缺 maintenance 不再是致命成因）。"""
    import ming_sim.issues as I

    db, state, content = game
    # manpower=float（历史 int(3.7)=3 静默套用=可活）+ 缺 maintenance（PR2 后不再必填）→ 容忍不抛
    I._apply_issue_entities(db, state, {
        "new_armies": [{"id": "req_a", "name": "需填军甲", "owner_power": "ming",
                        "manpower": 3.7, **_pay_source()}],
    }, "局势#测试结案")  # 不抛
    # manpower=串:历史 int("三千") ValueError → 致命 → raise（维护费在场与否不影响）
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "req_b", "name": "需填军乙", "owner_power": "ming",
                            "manpower": "三千"}],
        }, "局势#测试结案")
    # manpower 缺键:历史 KeyError → 致命 → raise
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "req_c", "name": "需填军丙", "owner_power": "ming"}],
        }, "局势#测试结案")
    # 合法 manpower、缺 maintenance:PR2 核心——维护费退役后建军照样成立 → 容忍不抛
    I._apply_issue_entities(db, state, {
        "new_armies": [{"id": "req_d", "name": "需填军丁", "owner_power": "ming",
                        "manpower": 5000, **_pay_source()}],
    }, "局势#测试结案")  # 不抛
