from __future__ import annotations
import pytest
from ming_sim.settlement import SettlementContext, settle_delta
from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows, run_declaration
"""PR2-S1(ADR 0008 决定 1,#91)——两个整段吞 section 迁入逐项拒收契约。

section 5 power_updates、section 9b character_power_changes：原先 `try: db.apply_*()
except Exception: print [WARN]` 整段吞——连代码异常都被吞掉(违 ADR 0005/决定 1)。
改为:LLM 脏数据(未知 power id/未知人物/字段非法)逐项拒收留痕,好项照落;
代码异常(KeyError/AttributeError 等)原样上抛，原子分派回滚整批。

从现役 pre_settle 与 dispatch_declaration 入口验证逐项拒收。
"""




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
