"""#1899 财政真源：声明写口 → pre_settle → 省税、起运与国库实账。

亲裁与重开复用 test_levy_petition_month_chain_1891 的真实月链贯穿案。
这里不再保留退役的选项代批、自动结局桩或未终态反复改判测试。
"""
import json

import pytest

from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim import decree as decree_mod
from ming_sim import issues


def _settle(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id=?", (region_id,)).fetchone()
    return json.loads(row["fiscal"])["settle"]


def _at(game, year, period, turn):
    db, state, content = game
    issues.bind_content(content)
    state.year, state.period, state.turn = year, period, turn
    db.save_state(state)
    return db, state


def _abolish(db, state, turn, stem="辽饷", *, zeroing=False):
    state.turn = turn
    item = {"key": f"{stem}_rate", "origin_ref": "盘面自发", "reason": "罢征"}
    field = "fiscal_changes" if zeroing else "fiscal_removes"
    if zeroing:
        item["delta"] = -100
    dispatch_declaration(db, state, {"effects": [{field: [item]}]})


def _settle_month(game, turn):
    db, state, content = game
    state.turn, state.turn_phase = turn, ""
    decree_mod.pre_settle(state, db, content=content)
    return db, state


def _remittance(db, turn, category="起运"):
    row = db.conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS total FROM economy_ledger "
        "WHERE account='国库' AND purpose IS NULL AND category=? AND turn=?",
        (category, turn),
    ).fetchone()
    return float(row["total"])


@pytest.mark.parametrize("zeroing", [False, True])
def test_abolished_liao_levy_stops_collection_next_month(game, zeroing):
    db, state = _at(game, 1631, 6, 10)
    before = _settle(db)
    seed = before["p"]["三饷应征"]
    assert seed > 0
    _abolish(db, state, 10, zeroing=zeroing)
    _settle_month(game, 11)
    for row in db.conn.execute("SELECT fiscal FROM regions"):
        settle = json.loads(row["fiscal"]).get("settle")
        if settle:
            assert settle["p"]["三饷应征"] == 0
            assert settle["p"]["起运定额"] == pytest.approx(settle["_meta"]["正赋起运基线"])
    assert _settle(db)["_meta"]["辽饷九厘基线"] == pytest.approx(seed)
    _settle_month(game, 12)
    assert _settle(db)["p"]["三饷应征"] == 0
    assert db.event_terminal_state("liao_levy_rise_1631") is None


@pytest.mark.parametrize("land_derived", [False, True])
def test_abolished_tian_fu_zeroes_regular_assessment(game, land_derived):
    db, state = _at(game, 1627, 10, 1)
    original = _settle(db)["p"]["正赋应征"]
    if land_derived:
        # 正赋既可由应征额给定，也可由田亩×亩额派生。
        fiscal = json.loads(db.conn.execute(
            "SELECT fiscal FROM regions WHERE id='shaanxi'",
        ).fetchone()["fiscal"])
        fiscal["settle"]["p"]["正赋应征"] = None
        fiscal["settle"]["p"]["正赋亩额"] = 0.001
        db.conn.execute("UPDATE regions SET fiscal=? WHERE id='shaanxi'", (json.dumps(fiscal),))
        db.conn.commit()
    _abolish(db, state, 1, stem="田赋")
    _settle_month(game, 2)
    after = _settle(db)
    assert after["p"]["正赋应征"] == 0
    assert after["p"]["三饷应征"] > 0
    _settle_month(game, 3)
    assert _settle(db)["p"]["正赋应征"] == 0
    dispatch_declaration(db, state, {"effects": [{"fiscal_creates": [{
        "key": "田赋", "account": "国库", "direction": "income", "init_value": 68,
        "display": "田赋", "origin_ref": "盘面自发", "reason": "复征",
    }]}]})
    _settle_month(game, 4)
    restored = _settle(db)
    assert restored["p"]["正赋应征"] == (None if land_derived else original)
    assert "正赋应征基线" not in restored["_meta"]


def test_abolition_moves_real_persisted_treasury_ledger(game):
    db, state = _at(game, 1627, 10, 1)
    _settle_month(game, 1)
    baseline = _remittance(db, 1)
    assert baseline > 0
    for stem in ("辽饷", "田赋"):
        _abolish(db, state, 2, stem=stem)
    _at(game, 1627, 11, 2)
    _settle_month(game, 2)
    assert _remittance(db, 2) == 0
    for stem, value in (("田赋", 68), ("辽饷", 43)):
        dispatch_declaration(db, state, {"effects": [{"fiscal_creates": [{
            "key": stem, "account": "国库", "direction": "income",
            "init_value": value, "display": stem, "origin_ref": "盘面自发", "reason": "复征",
        }]}]})
    _at(game, 1627, 12, 3)
    _settle_month(game, 3)
    assert _remittance(db, 3) == pytest.approx(baseline, rel=0.2)


@pytest.mark.parametrize(
    ("stem", "category", "seed_base", "init_value"),
    [(stem, stem, base, value) for stem, base in (("盐税", 23), ("商税", 7))
     for value in (0, base, base * 2)]
    + [("田赋", "起运", 68, 0), ("辽饷", "起运", 43, 43), ("辽饷", "起运", 43, 86)],
)
def test_recreated_dynamic_tax_moves_real_persisted_ledger(game, stem, category, seed_base, init_value):
    """重立声明额度仍只由省级路径消费；不重复中央收入。"""
    db, state = _at(game, 1628, 1, 10)
    _settle_month(game, 10)
    baseline = _remittance(db, 10, category)
    assert baseline > 0
    _abolish(db, state, 11, stem=stem)
    if stem == "田赋":
        _abolish(db, state, 11, stem="辽饷")
    _settle_month(game, 11)
    if stem != "辽饷":
        assert _remittance(db, 11, category) == 0
    dispatch_declaration(db, state, {"effects": [{"fiscal_creates": [{
        "key": stem, "account": "国库", "direction": "income", "init_value": init_value,
        "display": stem, "origin_ref": "盘面自发", "reason": "复征",
    }]}]})
    _settle_month(game, 12)
    if stem == "辽饷":
        settle = _settle(db)
        assert settle["p"]["三饷应征"] == pytest.approx(
            settle["_meta"]["辽饷九厘基线"] * init_value / seed_base,
        )
        assert _remittance(db, 12) > 0
    elif init_value == 0:
        assert _remittance(db, 12, category) == 0
    else:
        assert _remittance(db, 12, category) == pytest.approx(
            baseline * init_value / seed_base, rel=1e-9, abs=1,
        )
