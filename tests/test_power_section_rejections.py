"""PR2-S1(ADR 0008 决定 1,#91)——两个整段吞 section 迁入逐项拒收契约。

section 5 power_updates、section 9b character_power_changes：原先 `try: db.apply_*()
except Exception: print [WARN]` 整段吞——连代码异常都被吞掉(违 ADR 0005/决定 1)。
改为:LLM 脏数据(未知 power id/未知人物/字段非法)逐项拒收留痕,好项照落;
代码异常(KeyError/AttributeError 等)上抛到 settle 层回滚整批。

经 driver.run_settle 端到端驱动(公共接口,与 test_rejection_wiring.py 同风格)。
"""

from __future__ import annotations

import pytest

from driver import run_settle as _run_settle
from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows


def run_settle(db, state, content, extracted, **kwargs):
    """These rejection tests model canonical spontaneous extractor envelopes."""
    for item in (extracted.get("power_updates") or {}).values():
        if isinstance(item, dict):
            item.setdefault("origin_ref", "盘面自发")
    return _run_settle(db, state, content, extracted, **kwargs)


def _valid_power_id(db):
    """取一个非 ming 的合法 power id,供「好项照落」对照。"""
    row = db.conn.execute(
        "SELECT id FROM powers WHERE id != 'ming' LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一个非明势力"
    return row[0]


def test_unknown_power_id_rejected_good_item_lands(game):
    """power_updates 引用未入库势力 → 该项逐项拒收留痕(不再 print 静默跳),
    同信封里合法势力的改动照常落库——坏一项不带走整批(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _valid_power_id(db)
    before = db.conn.execute(
        "SELECT leverage FROM powers WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "power_updates": {
            "查无此势力": {"leverage": 5},
            good: {"leverage": 3},
        },
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "power_changes"]
    assert len(rows) == 1
    section, reason, category, source = rows[0]
    assert reason  # 人读原因非空
    assert category == "hallucinated_id"
    # 好项照落:坏项被拒不带走整批
    after = db.conn.execute(
        "SELECT leverage FROM powers WHERE id=?", (good,)).fetchone()[0]
    assert after != before


def test_illegal_power_field_rejected(game):
    """power_updates 字段超出白名单(只许 威望/实力/经济)→ 逐项拒收留痕,
    同势力的合法字段照落(ADR 决定 1 逐项拒收)。"""
    db, state, content = game
    turn = state.turn
    good = _valid_power_id(db)

    run_settle(db, state, content, {
        "power_updates": {good: {"leverage": 4, "城防": 9}},  # 城防 非白名单
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn)
            if r[0] == "power_changes" and r[2] == "invalid_enum"]
    assert len(rows) == 1
    assert rows[0][1]  # reason 非空


def test_power_deltas_code_exception_aborts_settlement(game, monkeypatch):
    """apply_power_deltas 内代码异常(bug 类,非脏数据)→ 上抛 SettlementAbort 回滚整批,
    绝不被原 try/except 吞掉(ADR 0005/决定 1)。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    good = _valid_power_id(db)

    def _boom(self, *a, **k):
        raise AttributeError("code bug in apply_power_deltas")
    monkeypatch.setattr(type(db), "apply_power_deltas", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "power_updates": {good: {"leverage": 3}},
        }, narrative="x", decree_text="y")


# ---- section 9b: character_power_changes(人物易主) ----

def test_unknown_person_power_change_rejected_good_lands(saved_game):
    """character_power_changes 引用查无此人 → 逐项拒收留痕(不再 print 静默跳);
    同信封里合法人物易主照落——坏一项不带走整批(ADR 决定 1)。
    用 saved_game：依赖玩过存档的特定人物易主基线，fresh seed 不复现（#5）。"""
    db, state, content = saved_game
    turn = state.turn
    good_power = _valid_power_id(db)
    # 取一个开局在册的大明大臣作「好项」(易主到 good_power)
    real = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' LIMIT 1").fetchone()[0]

    run_settle(db, state, content, {
        "character_power_changes": [
            {"name": "查无此人辛", "new_power": good_power, "reason": "降"},
            {"name": real, "new_power": good_power, "reason": "叛"},
        ],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "character_power_changes"]
    assert len(rows) == 1
    assert rows[0][1]  # reason 非空
    assert rows[0][2] == "missing_ref"
    # 好项照落
    after = db.conn.execute(
        "SELECT power_id FROM characters WHERE name=?", (real,)).fetchone()[0]
    assert after == good_power


def test_canonical_person_power_writer_code_exception_is_fail_loud(game, monkeypatch):
    """Canonical 人物变更 writer 的代码异常必须上抛；legacy aliases 不再有第二写路。"""
    db, state, content = game
    target_power = _valid_power_id(db)
    name = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()[0]

    def _boom(self, *args, **kwargs):
        raise KeyError("canonical person power writer bug")

    monkeypatch.setattr(type(db), "apply_character_power_changes", _boom)
    with pytest.raises(KeyError, match="canonical person power writer bug"):
        import ming_sim.issues as issues
        issues.apply_score_extraction(db, state, {
            "人物变更": [{
                "name": name, "动作": "易主", "方式": "主动投敌", "反噬": {},
                "new_power": target_power, "reason": "叛", "origin_ref": "盘面自发",
            }],
        }, content=content)


def test_power_change_formatter_skips_rejected_items():
    """report.format_power_changes 遇到同列的拒收项(无 delta/label 键)不得 KeyError——
    拒收项不是盘面变化,只渲染 applied 项;全拒收时回落「未见变化」(S1 迁契约副作用守门)。"""
    from ming_sim.report import format_power_changes

    out = format_power_changes([
        {"rejected": True, "category": "hallucinated_id", "reason": "查无此势力"},
        {"power": "后金", "label": "威望", "old": 50, "new": 53, "delta": 3, "reason": "推演"},
    ])
    assert "后金" in out and "查无此势力" not in out

    only_rejected = format_power_changes([
        {"rejected": True, "category": "invalid_enum", "reason": "字段非法"}])
    assert "未见明确势力盘面变化" in only_rejected


def test_dirty_power_value_rejected_sibling_field_lands(game):
    """白名单字段的脏值(null/"3成")= LLM 脏数据,逐项拒收——validate_delta_shape
    只验容器、明文容忍 null 叶,裸 int(value) 会让一个脏值崩整月(cmr S1 r1,2/2)。
    同一势力的兄弟好字段照落。"""
    db, state, content = game
    turn = state.turn
    good = _valid_power_id(db)
    before = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "power_updates": {
            good: {"leverage": None, "military_strength": 3},  # null 脏值 + 兄弟好字段
        },
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "power_changes"]
    assert len(rows) == 1
    _, reason, category, _ = rows[0]
    assert category == "invalid_enum"
    assert reason
    after = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id=?", (good,)).fetchone()[0]
    assert after != before  # 兄弟好字段照落


def test_dirty_power_value_string_rejected(game):
    """字符串脏值("三成")同路拒收,不 SettlementAbort。"""
    db, state, content = game
    turn = state.turn
    good = _valid_power_id(db)

    run_settle(db, state, content, {
        "power_updates": {good: {"leverage": "三成"}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "power_changes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"


def test_ming_power_update_rejected_with_trace(game):
    """power_updates 写 ming = prompt 明文禁止的脏数据 → 逐项拒收留痕,
    不再 print 静默跳(cmr S1 r2,2/2——迁了 section 却留一条 print 路不一致)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "power_updates": {"ming": {"leverage": 5}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "power_changes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert "ming" in rows[0][1] or "大明" in rows[0][1]


def test_float_and_bool_power_values_rejected(game):
    """float(3.7→3 静默截断)与 bool(True→1 静默拟真)叶子值绕过 int() 异常路
    ——一律拒收,prompt 要求整数 delta(cmr S1 r2 codex)。"""
    db, state, content = game
    turn = state.turn
    good = _valid_power_id(db)
    before = db.conn.execute(
        "SELECT leverage FROM powers WHERE id=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "power_updates": {good: {"leverage": 3.7, "military_strength": True}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "power_changes"]
    assert len(rows) == 2
    assert all(r[2] == "invalid_enum" for r in rows)
    after = db.conn.execute(
        "SELECT leverage FROM powers WHERE id=?", (good,)).fetchone()[0]
    assert after == before  # 3.7 没有被截断成 3 落库


def test_reason_carrier_aliases_not_recorded_as_rejection(game):
    """last_action/近动 是函数自己消费的 reason 载体键——不得同时被记成
    invalid_enum 拒收(假阳行污染分析账本,cmr S1 r2 claude)。"""
    db, state, content = game
    turn = state.turn
    good = _valid_power_id(db)

    run_settle(db, state, content, {
        "power_updates": {good: {"leverage": 3, "近动": "联姻蒙古", "last_action": "遣使"}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "power_changes"]
    assert rows == []  # 零假阳


def test_all_reason_aliases_consumed_as_reason(game):
    """近况/最近行动 与 近动/last_action 同为别名——被跳过就必须也被消费成
    应用变更的 reason,不得回落「势力推演」(cmr S1 r3 codex)。"""
    db, state, content = game
    good = _valid_power_id(db)

    run_settle(db, state, content, {
        "power_updates": {good: {"leverage": 3, "近况": "联姻蒙古"}},
    }, narrative="x", decree_text="y")

    row = db.conn.execute(
        "SELECT reason FROM power_logs WHERE power_id=? ORDER BY id DESC LIMIT 1",
        (good,)).fetchone()
    assert row is not None
    assert row[0] == "联姻蒙古"
