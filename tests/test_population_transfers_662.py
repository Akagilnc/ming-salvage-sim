"""#662（[#477 S14]）：灾害／兵灾驱动入池——流民池的天灾与兵祸入口。

canonical＝ADR 0087 + #662 票庭判词（run 01a02d40-244d-7e4c-8386-5af682d584a2）施工边界：
- 发生与量级判定＝LLM 软判吃既有盘面（region 天灾/人祸字段、military_pressure 定性档、
  活跃局势 issue）；代码侧只做量级口径 clamp＋守恒记账，禁引擎侧自动触发（无双驱动）；
- origin 分立＝reason 枚举「灾害」／「兵灾」（落库字段即 reason，无第二 origin 字段）；
- 与加派/摊派入口合流同一本账：同一 classes 省级行池＋同一原语，下游只认账不认来源；
- 邸报/召对定性回响走既有 effect_brief／classes_brief 特征面（P4 零数值）。
主测缝＝S2 同缝：apply_score_extraction / settle_with_delta / effect_brief /
prompt 契约文本 / GameDB 重开接续。mutation oracle 复用 #649 家族，不另立机制。
"""

from __future__ import annotations

from test_population_transfers_649 import (
    DISPLACED_SHAANXI,
    FARMER_SHAANXI,
    _conservation_oracle,
    _global_population,
    _make_legacy_db,
    _pop,
    _snap,
    _transfer,
)

import pytest

from ming_sim.db import GameDB, POPULATION_UNIT_WAN
from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.memories import effect_brief

# 量级口径（施工契约，史实尺度）：单条记录上限＝本批结算前源阶级省级行余额 × 万分比。
# 灾荒月度驱离在低个位数百分比量级；兵祸过境冲击更烈，放宽一档。
DISASTER_CAP_BPS = 500   # 灾害 ≤ 5%
WAR_CAP_BPS = 1000       # 兵灾 ≤ 10%


def _cap(balance: int, bps: int) -> int:
    return balance * bps // 10000


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


# ── 灾害入池：有灾入（正测）＋量级口径双向边界 ──────────────────────────────

def test_disaster_entry_lands_with_region_disaster_fact(disaster_shaanxi):
    """灾情事实满足口径＋LLM 申报灾害转移 → 按省守恒落账（origin 标＝reason 枚举）。"""
    db, state, content = disaster_shaanxi
    total_before = _global_population(db)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=30000, reason="灾害"),
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    rec = applied["population_transfers"][0]
    assert rec["reason"] == "灾害"
    assert rec["origin_ref"] == "盘面自发"
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - 30000
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + 30000
    assert _global_population(db) == total_before  # 守恒


def test_disaster_magnitude_clamp_two_way_boundary(disaster_shaanxi):
    """口径 clamp 双向：amount＝上限（floor(源余额×5%)）落账；上限+1 整项拒收、
    两腿分毫不动。"""
    db, state, content = disaster_shaanxi
    cap = _cap(FARMER_SHAANXI, DISASTER_CAP_BPS)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=cap + 1, reason="灾害"),
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=cap, reason="灾害"),
        ],
    }, content, None)
    rejections = applied["population_transfers_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["category"] == "invalid_enum"
    assert "量级口径" in rejections[0]["reason"]
    recs = applied["population_transfers"]
    assert len(recs) == 1 and recs[0]["amount"] == cap
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - cap
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + cap


def test_disaster_and_war_caps_share_opening_balance_not_live_order(disaster_shaanxi):
    """同源灾害 5% 与兵灾 10% 都按 extractor 所见的结算前快照验票；前项落账后
    不得缩小后项口径，否则合法批会随数组顺序改变接受结果。"""
    db, state, content = disaster_shaanxi
    disaster_cap = _cap(FARMER_SHAANXI, DISASTER_CAP_BPS)
    war_cap = _cap(FARMER_SHAANXI, WAR_CAP_BPS)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=disaster_cap, reason="灾害"),
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=war_cap, reason="兵灾"),
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert [r["amount"] for r in applied["population_transfers"]] == [
        disaster_cap, war_cap,
    ]
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - disaster_cap - war_cap


def test_disaster_clamp_unit_agnostic(content, tmp_path):
    """clamp 按源余额比例计算、与存档刻度无关：legacy 万口径档同样吃 5% 上限。"""
    path = str(tmp_path / "legacy662.db")
    db = _make_legacy_db(content, path)
    try:
        assert db.population_unit == POPULATION_UNIT_WAN
        legacy_farmers = _pop(db, "农民", "shaanxi")
        cap = _cap(legacy_farmers, DISASTER_CAP_BPS)
        applied = apply_score_extraction(db, db.load_state(), {
            "population_transfers": [
                _transfer(source="农民@shaanxi", target="流民@shaanxi",
                          amount=cap + 1, reason="灾害"),
            ],
        }, content, None)
        assert len(applied["population_transfers_rejections"]) == 1
        assert "量级口径" in applied["population_transfers_rejections"][0]["reason"]
        assert _pop(db, "农民", "shaanxi") == legacy_farmers
    finally:
        db.close()


# ── 兵灾入池：农民/军户双腿 ＋ 口径 ──────────────────────────────────────────

def test_war_entry_lands_farmer_and_garrison_legs(war_shaanxi):
    """兵祸事实满足口径 → 农民腿与军户腿各自守恒落账（origin 标＝reason 兵灾）。"""
    db, state, content = war_shaanxi
    garrison_before = _pop(db, "军户", "shaanxi")
    total_before = _global_population(db)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=20000, reason="兵灾"),
            _transfer(source="军户@shaanxi", target="流民@shaanxi",
                      amount=5000, reason="兵灾"),
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert [r["reason"] for r in applied["population_transfers"]] == ["兵灾", "兵灾"]
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - 20000
    assert _pop(db, "军户", "shaanxi") == garrison_before - 5000
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + 25000
    assert _global_population(db) == total_before


def test_war_magnitude_clamp_garrison_leg(war_shaanxi):
    """军户腿同样吃兵灾口径：超 floor(军户余额×10%) 整项拒收；农民腿合法项照落。"""
    db, state, content = war_shaanxi
    garrison = _pop(db, "军户", "shaanxi")
    cap = _cap(garrison, WAR_CAP_BPS)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="军户@shaanxi", target="流民@shaanxi",
                      amount=cap + 1, reason="兵灾"),
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=1000, reason="兵灾"),
        ],
    }, content, None)
    rejections = applied["population_transfers_rejections"]
    assert len(rejections) == 1 and "量级口径" in rejections[0]["reason"]
    assert _pop(db, "军户", "shaanxi") == garrison  # 拒收项两腿不动
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - 1000


# ── 双向边界·反测：无灾不入——事实本身永不自发移人（禁引擎侧自动触发）───────

def test_no_engine_autotransfer_from_disaster_or_war_facts(game):
    """即使 region 挂满灾情/兵祸事实，extractor 未申报 population_transfers 段时
    人口分毫不动——读事实→判发生＝LLM 软判，代码侧无第二套自动触发（判词①）。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE regions SET natural_disaster='大旱蝗灾', "
        "human_disaster='战事过境焚掠', military_pressure=95 WHERE id='shaanxi'"
    )
    db.conn.commit()
    before = _snap(db)
    applied = apply_score_extraction(db, state, {
        "metric_delta": {"民心": -1},  # 同批只有非人口 section
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert applied["population_transfers"] == []
    for key, want in before.items():
        assert _pop(db, *key) == want, f"{key}: 无申报记录时被引擎改动（自动触发违规）"


# ── 守恒与 mutation：沿 S2 断言族扩展（复用 #649 oracle，不另立机制）─────────

def test_mutation_oracle_bites_disaster_war_mutations(war_shaanxi):
    """真实 applier 跑灾害+兵灾批 → oracle 正对照不炸；凭空造人/单侧写/出阵方向
    三类变异逐一注入观测面必被咬（#649 test_mutation_oracle 家族同法）。"""
    db, state, content = war_shaanxi
    garrison_before = _pop(db, "军户", "shaanxi")

    def _apply_and_verify(reason, src_cls, amount):
        """单条记录一批：oracle 契约＝每笔成功记录两侧精确 ±amount，故每批一条、
        快照各取前后（同池多记录时按 #649 家族逐批验证，不改 oracle）。"""
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
        _conservation_oracle(before, after, [rec])  # 正对照
        return before, after, rec

    before1, after1, rec_disaster = _apply_and_verify("灾害", "农民", 30000)
    _, _, rec_war = _apply_and_verify("兵灾", "军户", 20000)
    assert garrison_before - _pop(db, "军户", "shaanxi") == 20000

    record = {"source": "农民@shaanxi", "target": "流民@shaanxi",
              "amount": 30000, "reason": "灾害"}
    # ① 凭空造人：目标腿多加、源腿未减
    m1 = dict(after1)
    m1[("流民", "shaanxi")] += 1000
    with pytest.raises(AssertionError):
        _conservation_oracle(before1, m1, [rec_disaster])
    # ② 单侧写：只有源腿减（灾害批前快照上只动农民）
    m2 = dict(before1)
    m2[("农民", "shaanxi")] -= 30000
    with pytest.raises(AssertionError):
        _conservation_oracle(before1, m2, [rec_disaster])
    # ③ 出阵方向：账面实际动的是农民→士绅，却申报农民→流民
    m3 = dict(after1)
    m3[("流民", "shaanxi")] -= 30000
    m3[("士绅", "shaanxi")] += 30000
    with pytest.raises(AssertionError):
        _conservation_oracle(before1, m3, [record])


# ── 邸报/召对定性回响：effect_brief 事实摘要带 reason；玩家面 classes_brief 定性零数值 ──

def test_effect_brief_disaster_war_causal_echo():
    """转移摘要随 reason 定性回响（供章节记忆/叙事特征包长出邸报/召对因果句，
    P7）：灾害/兵灾各出「某省某阶级流失 N 口为流民（原因）」措辞。"""
    brief = effect_brief({"population_transfers": [
        {"source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 30000,
         "reason": "灾害", "region_id": "shaanxi", "region_name": "陕西",
         "population_unit": "人"},
        {"source": "军户@shaanxi", "target": "流民@shaanxi", "amount": 20000,
         "reason": "兵灾", "region_id": "shaanxi", "region_name": "陕西",
         "population_unit": "人"},
    ]})
    assert "陕西农民流失30000口为流民（灾害）" in brief
    assert "陕西军户流失20000口为流民（兵灾）" in brief


def test_classes_brief_audience_carries_displaced_pool_qualitatively(game):
    """P4 零数值：皇帝可感混合调用的 classes_brief 含流民定性档（band 词表），
    不含流民池裸数——回响由 LLM 从定性特征长出，非数字直排。"""
    db, state, content = game
    apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=30000, reason="灾害"),
        ],
    }, content, None)
    brief = db.class_report(audience=True)
    assert "流民" in brief and "势力极弱" in brief  # 定性档词表，非裸数
    assert str(_pop(db, "流民", "shaanxi")) not in brief  # 池余额不进皇帝可见面


# ── AC5 拆一：restore 只读 DB 无损接续（灾害/兵灾落账后重开存档）─────────────

def test_restore_after_disaster_war_settlement_lossless(game):
    """任意月份结算后重开存档：灾害/兵灾转移后的流民池与农民/军户余额从 classes
    真源无损接续，turn_extractions 留痕完整——零重放零记忆（P1）。"""
    db, state, content = game
    garrison_before = _pop(db, "军户", "shaanxi")
    before_turn = state.turn
    settle_with_delta(state, db, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi",
                      amount=20000, reason="灾害"),
            _transfer(source="军户@shaanxi", target="流民@shaanxi",
                      amount=10000, reason="兵灾"),
        ],
    }, before_turn=before_turn, content=content)
    farmer_after = _pop(db, "农民", "shaanxi")
    pool_after = _pop(db, "流民", "shaanxi")
    db.close()

    reopened = GameDB(db.path, content)
    try:
        restored = reopened.load_state()
        assert restored.turn == before_turn + 1
        # 只读 DB 接续（独立断言，判词五·非 blocking 备注）
        assert _pop(reopened, "流民", "shaanxi") == pool_after
        assert _pop(reopened, "农民", "shaanxi") == farmer_after
        assert _pop(reopened, "军户", "shaanxi") == garrison_before - 10000
        ext = reopened.get_turn_extraction(before_turn)
        recs = ext["extractor_output"]["population_transfers"]
        assert sorted(r["reason"] for r in recs) == ["兵灾", "灾害"]
    finally:
        reopened.close()


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


# ── 契约单真源：prompt 教「有灾入/无灾不入」事实支撑＋量级口径 ────────────────

def test_prompts_teach_disaster_war_grounding_and_magnitude_cap():
    """两份 prompt 的 人口转移 契约必须教：①灾害/兵灾须有该省盘面事实支撑
    （天灾/人祸字段或军事高压/局势 issue）、无此事实不得申报；②量级口径上限
    （灾害≤5%、兵灾≤10%）——LLM 软判的判定依据与 clamp 边界同纸交付。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, must in (
        ("content/prompts/score_extractor_internal.md",
         ("无此事实", "灾害", "兵灾", "量级口径")),
        ("content/prompts/score_extractor_shared.md", ("量级口径",)),
    ):
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        line = next((ln for ln in text.splitlines() if "人口转移" in ln and "原因" in ln), "")
        assert line, f"{rel}: 缺 人口转移 契约行"
        for token in must:
            assert token in line, f"{rel}: 人口转移 行未教 {token!r}：{line!r}"


def test_season_simulator_must_emit_extractable_displacement_decision():
    """真实生产链先由 simulator 判自然后果；它必须产出省、来源阶级、确定人数与原因，
    而非指望只翻译月度新旨意的 extractor 从背景事实自行发明转移。"""
    from pathlib import Path
    prompt = (Path(__file__).parents[1] / "content/prompts/season_simulator.md").read_text(
        encoding="utf-8"
    )
    section = prompt.split("**灾害／兵灾流民后果**：", 1)[1].split("### 军事", 1)[0]
    for token in ("regions", "无对应事实不得", "来源阶级", "确定人数", "灾害", "兵灾", "守恒转移"):
        assert token in section
