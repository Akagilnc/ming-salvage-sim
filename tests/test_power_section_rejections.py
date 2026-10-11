"""PR2-S1(ADR 0008 决定 1,#91)——两个整段吞 section 迁入逐项拒收契约。

section 5 power_updates、section 9b character_power_changes：原先 `try: db.apply_*()
except Exception: print [WARN]` 整段吞——连代码异常都被吞掉(违 ADR 0005/决定 1)。
改为:LLM 脏数据(未知 power id/未知人物/字段非法)逐项拒收留痕,好项照落;
代码异常(KeyError/AttributeError 等)原样上抛，原子分派回滚整批。

从现役 pre_settle 与 dispatch_declaration 入口验证逐项拒收。
"""

from __future__ import annotations


import pytest

from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows, run_declaration
from tests.readback_helpers import non_ming_power_id as _valid_power_id

def run_settle(db, state, content, extracted, **kwargs):
    """These rejection tests model canonical spontaneous extractor envelopes."""
    for item in (extracted.get("power_updates") or {}).values():
        if isinstance(item, dict):
            item.setdefault("origin_ref", "盘面自发")
    return run_declaration(db, state, content, extracted)

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
    """apply_power_deltas 内代码异常原样上抛，原子分派回滚整批。
    来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""

    db, state, content = game
    good = _valid_power_id(db)

    fault = AttributeError("code bug in apply_power_deltas")

    def _boom(self, *a, **k):
        raise fault

    monkeypatch.setattr(type(db), "apply_power_deltas", _boom)

    with pytest.raises(AttributeError) as ei:
        run_settle(db, state, content, {
            "power_updates": {good: {"leverage": 3}},
        }, narrative="x", decree_text="y")
    assert ei.value is fault

# ---- section 9b: character_power_changes(人物易主) ----

def test_canonical_person_power_writer_code_exception_is_fail_loud(game, monkeypatch):
    """Canonical 人物变更 writer 的代码异常必须上抛；legacy aliases 不再有第二写路。
    来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, content = game
    target_power = _valid_power_id(db)
    name = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()[0]

    fault = KeyError("canonical person power writer bug")

    def _boom(self, *args, **kwargs):
        raise fault

    monkeypatch.setattr(type(db), "apply_character_power_changes", _boom)
    with pytest.raises(KeyError) as ei:
        import ming_sim.issues as issues
        issues.apply_score_extraction(db, state, {
            "人物变更": [{
                "name": name, "动作": "易主", "方式": "主动投敌", "反噬": {},
                "new_power": target_power, "reason": "叛", "origin_ref": "盘面自发",
            }],
        }, content=content)
    assert ei.value is fault
