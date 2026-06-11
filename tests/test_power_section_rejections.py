"""PR2-S1(ADR 0008 决定 1,#91)——两个整段吞 section 迁入逐项拒收契约。

section 5 power_updates、section 9b character_power_changes：原先 `try: db.apply_*()
except Exception: print [WARN]` 整段吞——连代码异常都被吞掉(违 ADR 0005/决定 1)。
改为:LLM 脏数据(未知 power id/未知人物/字段非法)逐项拒收留痕,好项照落;
代码异常(KeyError/AttributeError 等)上抛到 settle 层回滚整批。

经 driver.run_settle 端到端驱动(公共接口,与 test_rejection_wiring.py 同风格)。
"""

from __future__ import annotations

import pytest

from driver import run_settle


def _rejection_rows(db, turn):
    return db.conn.execute(
        "SELECT section, reason, category, source FROM rejection_reports"
        " WHERE turn=? ORDER BY id", (turn,)
    ).fetchall()


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

def test_unknown_person_power_change_rejected_good_lands(game):
    """character_power_changes 引用查无此人 → 逐项拒收留痕(不再 print 静默跳);
    同信封里合法人物易主照落——坏一项不带走整批(ADR 决定 1)。"""
    db, state, content = game
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


def test_character_power_changes_code_exception_aborts_settlement(game, monkeypatch):
    """apply_character_power_changes 内代码异常 → 上抛 SettlementAbort 回滚整批,
    绝不被原 try/except 吞掉(ADR 0005/决定 1)。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    good_power = _valid_power_id(db)
    real = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' LIMIT 1").fetchone()[0]

    def _boom(self, *a, **k):
        raise KeyError("code bug in apply_character_power_changes")
    monkeypatch.setattr(type(db), "apply_character_power_changes", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "character_power_changes": [
                {"name": real, "new_power": good_power, "reason": "叛"}],
        }, narrative="x", decree_text="y")


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
