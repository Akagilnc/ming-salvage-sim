"""PR2-S1(ADR 0008 决定 1,#91)——两个整段吞 section 迁入逐项拒收契约。

section 5 power_updates、section 9b character_power_changes：原先 `try: db.apply_*()
except Exception: print [WARN]` 整段吞——连代码异常都被吞掉(违 ADR 0005/决定 1)。
改为:LLM 脏数据(未知 power id/未知人物/字段非法)逐项拒收留痕,好项照落;
代码异常(KeyError/AttributeError 等)原样上抛，原子分派回滚整批。

从现役 pre_settle 与 dispatch_declaration 入口验证逐项拒收。
"""

from __future__ import annotations

import pytest
from ming_sim.settlement import SettlementContext, settle_delta

from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows, run_declaration

def run_settle(db, state, content, extracted, **kwargs):
    """These rejection tests model canonical spontaneous extractor envelopes."""
    for item in (extracted.get("power_updates") or {}).values():
        if isinstance(item, dict):
            item.setdefault("origin_ref", "盘面自发")
    return run_declaration(db, state, content, extracted)

def _valid_power_id(db):
    """取一个非 ming 的合法 power id,供「好项照落」对照。"""
    row = db.conn.execute(
        "SELECT id FROM powers WHERE id != 'ming' LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一个非明势力"
    return row[0]


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
        settle_delta(state, db, {
            "人物变更": [{
                "name": name, "动作": "易主", "方式": "主动投敌", "反噬": {},
                "new_power": target_power, "reason": "叛", "origin_ref": "盘面自发",
            }],
        }, SettlementContext(content=content))
    assert ei.value is fault


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
    assert rows[0][1]


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
