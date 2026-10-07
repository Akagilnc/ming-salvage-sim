"""#662（[#477 S14]）：灾害／兵灾驱动入池——流民池的天灾与兵祸入口。

canonical＝ADR 0087 + #662 票庭判词（run 01a02d40-244d-7e4c-8386-5af682d584a2）施工边界：
- 发生与量级判定＝LLM 软判吃既有盘面（region 天灾/人祸字段、military_pressure 定性档、
  活跃局势 issue）及阶级余额与人口单位；代码侧只守物理不变量，禁引擎侧自动触发（无双驱动）；
- origin 分立＝reason 枚举「灾害」／「兵灾」（落库字段即 reason，无第二 origin 字段）；
- 与加派/摊派入口合流同一本账：同一 classes 省级行池＋同一原语，下游只认账不认来源；
主测缝＝apply_score_extraction 的人口守恒落账。
"""

from __future__ import annotations

from test_population_transfers_649 import (
    DISPLACED_SHAANXI,
    FARMER_SHAANXI,
    _conservation_oracle,
    _global_population,
    _pop,
    _snap,
    _transfer,
)

import pytest

from ming_sim.issues import apply_score_extraction


@pytest.fixture
def disaster_shaanxi(game):
    """陕西挂显式灾情事实（真源＝regions.natural_disaster 字段）。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE regions SET natural_disaster='大旱蝗灾' WHERE id='shaanxi'"
    )
    db.conn.commit()
    return db, state, content


@pytest.fixture
def war_shaanxi(game):
    """陕西挂显式兵祸事实（人祸字段＋军事高压档）。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE regions SET human_disaster='战事过境焚掠', military_pressure=90 "
        "WHERE id='shaanxi'"
    )
    db.conn.commit()
    return db, state, content


# ── 灾害入池：有灾入（正测）──────────────────────────────────────────────

def test_disaster_and_war_amounts_above_old_caps_land_and_conserve(war_shaanxi):
    """具体量级由 extractor 软判；超过旧固定比例但未超过实时源余额时照常守恒落账。"""
    db, state, content = war_shaanxi
    garrison_before = _pop(db, "军户", "shaanxi")
    disaster_amount = FARMER_SHAANXI * 6 // 100
    war_amount = garrison_before * 11 // 100
    total_before = _global_population(db)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=disaster_amount, reason="灾害"),
            _transfer(source="军户@shaanxi", target="流民@shaanxi",
                      amount=war_amount, reason="兵灾"),
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - disaster_amount
    assert _pop(db, "军户", "shaanxi") == garrison_before - war_amount
    assert _pop(db, "流民", "shaanxi") == (
        DISPLACED_SHAANXI + disaster_amount + war_amount
    )
    assert _global_population(db) == total_before


# ── 守恒与 mutation：沿 S2 断言族扩展（复用 #649 oracle，不另立机制）─────────

def test_disaster_and_war_sequential_batches_conserve(war_shaanxi):
    """真实 applier 分批灾害+兵灾落账后，两侧精确 ±amount 且全局守恒。"""
    db, state, content = war_shaanxi
    garrison_before = _pop(db, "军户", "shaanxi")

    def _apply_and_verify(reason, src_cls, amount):
        before = _snap(db)
        applied = apply_score_extraction(db, state, {
            "population_transfers": [
                _transfer(source=f"{src_cls}@shaanxi", target="流民@shaanxi",
                          amount=amount, reason=reason),
            ],
        }, content, None)
        assert not applied["population_transfers_rejections"]
        rec = applied["population_transfers"][0]
        after = _snap(db)
        _conservation_oracle(before, after, [rec])
        return after

    _apply_and_verify("灾害", "农民", 30000)
    _apply_and_verify("兵灾", "军户", 20000)
    assert garrison_before - _pop(db, "军户", "shaanxi") == 20000





# ── AC5 拆一：restore 只读 DB 无损接续（灾害/兵灾落账后重开存档）─────────────



# ── AC5 拆二：与加派/摊派入口合流同一本账（下游只认账不认来源）────────────────

def test_same_batch_multi_origin_merges_into_single_pool_account(disaster_shaanxi):
    """同一批 加派+摊派+灾害 落账后：流民@shaanxi 单行累加入池总量；
    各入口共用同一 classes 行池＋同一原语——下游读池总量，不按来源分账。"""
    db, state, content = disaster_shaanxi
    total_before = _global_population(db)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=1000, reason="加派"),   # S3 明渠入口（同一本账）
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=2000, reason="摊派"),   # S4 暗渠入口（同一本账）
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=4000, reason="灾害"),   # 本票天灾入口
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert len(applied["population_transfers"]) == 3
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + 7000  # 单行合流
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - 7000
    assert _global_population(db) == total_before  # 全局守恒不变式
