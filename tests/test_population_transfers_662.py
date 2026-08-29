"""#662（[#477 S14]）：灾害／兵灾驱动入池——流民池的天灾与兵祸入口。

canonical＝ADR 0087 + #662 票庭判词（run 01a02d40-244d-7e4c-8386-5af682d584a2）施工边界：
- 发生与量级判定＝LLM 软判吃既有盘面（region 天灾/人祸字段、military_pressure 定性档、
  活跃局势 issue）及阶级余额与人口单位；代码侧只守物理不变量，禁引擎侧自动触发（无双驱动）；
- origin 分立＝reason 枚举「灾害」／「兵灾」（落库字段即 reason，无第二 origin 字段）；
- 与加派/摊派入口合流同一本账：同一 classes 省级行池＋同一原语，下游只认账不认来源；
- 邸报/召对定性回响走既有 effect_brief／classes_brief 特征面（P4 零数值）。
主测缝＝S2 同缝：apply_score_extraction / settle_with_delta / effect_brief /
prompt 契约文本 / GameDB 重开接续。mutation oracle 复用 #649 家族，不另立机制。
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

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

from ming_sim.db import GameDB
from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.memories import effect_brief
from ming_sim.agents import build_simulator_context
from ming_sim.models import CourtContext
from ming_sim.registry import build_character_knowledge_brief
from ming_sim.simulation import (
    EXTRACTION_MODULES,
    build_extractor_shared_context,
    extract_scores_by_modules_with_agno,
    simulate_season_with_payload,
)

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


class _ExtractorAgent:
    def __init__(self, response):
        self.response = response

    def run(self, _prompt):
        return SimpleNamespace(content=self.response)


class _SimulatorAgent(_ExtractorAgent):
    """不接受 stream 参数，令真实 simulator runner 走其普通 run 兼容支路。"""


def _module_response(module, transfers):
    payload = {
        "internal": {"metric_delta": {}, "economy_moves": [], "fiscal_changes": [],
                     "fiscal_creates": [], "fiscal_removes": [], "faction_delta": {},
                     "class_delta": {}, "population_transfers": transfers, "region_delta": {}},
        "military_external": {"army_delta": {}, "new_armies": [], "power_updates": {}, "world_advance": {}},
        "issues": {"issue_advances": [], "new_issues": [], "事件结局": {}, "cancels": [], "close_issues": []},
        "personnel_secret": {"人物变更": [], "secret_order_updates": [], "emperor_fate": None},
        "relations": {"relation_edge_events": []},
    }[module]
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize("fact_sql,reason,source,amount", [
    ("UPDATE regions SET natural_disaster='大旱蝗灾' WHERE id='shaanxi'", "灾害", "农民@shaanxi", 30000),
    ("UPDATE regions SET human_disaster='战事过境焚掠', military_pressure=90 WHERE id='shaanxi'", "兵灾", "军户@shaanxi", 5000),
])
def test_disaster_war_real_payload_extractor_settlement_and_echo(
    game, fact_sql, reason, source, amount
):
    """只 fake LLM 返回；真实 payload→模块抽取→settle→报告/玩家面回读。"""
    db, state, content = game
    db.conn.execute(fact_sql)
    db.conn.commit()
    before_turn = state.turn
    qualitative = f"陕西{source.split('@')[0]}因{reason}离乡，流民渐多"
    narrative, simulator_payload = simulate_season_with_payload(
        _SimulatorAgent(qualitative), state, db, "", ""
    )
    assert narrative == qualitative
    assert "class_population_balances" not in simulator_payload
    rendered = build_simulator_context(simulator_payload)
    assert "class_population_balances" not in rendered
    assert str(FARMER_SHAANXI) not in rendered
    context = build_extractor_shared_context(db, state, narrative, "", module="internal")
    balances = context["class_population_balances"]
    assert balances["cols"] == ["class_region", "population", "population_unit"]
    assert any(row[:2] == ["农民@shaanxi", FARMER_SHAANXI] for row in balances["rows"])
    assert context["turn"]["turn"] == before_turn

    transfer = _transfer(source=source, target="流民@shaanxi", amount=amount, reason=reason)
    agents = {m: _ExtractorAgent(_module_response(m, [transfer] if m == "internal" else []))
              for m in EXTRACTION_MODULES}
    extracted, extractor_output, extractor_input = extract_scores_by_modules_with_agno(
        agents, db, state, context["narrative"], parallel=False
    )
    report = settle_with_delta(
        state, db, extracted, before_turn=before_turn, content=content,
        narrative=context["narrative"], extractor_input=extractor_input,
        extractor_output=extractor_output,
    )
    assert reason in effect_brief(extracted)
    assert "流民" in db.class_report(audience=True)
    assert reason in report
    minister = next(iter(content.characters.values()))
    audience = build_character_knowledge_brief(
        minister, CourtContext(state=state, db=db)
    )
    assert reason in audience
    assert "流民" in audience
    assert str(_pop(db, *source.split("@"))) not in audience
    assert str(_pop(db, "流民", "shaanxi")) not in audience
    saved = db.get_turn_extraction(before_turn)["extractor_output"]["population_transfers"]
    assert saved[0]["reason"] == reason


def test_no_disaster_war_fact_real_simulation_and_extraction_declares_nothing(game):
    """无事实反例也走真实 simulator/extractor 接缝：定性叙事不造灾，档房不申报，DB 不动。"""
    db, state, _content = game
    before = _snap(db)
    narrative, payload = simulate_season_with_payload(
        _SimulatorAgent("本月各省安靖，无灾无兵祸，百姓安土。"), state, db, "", ""
    )
    context = build_extractor_shared_context(db, state, narrative, "", module="internal")
    agents = {m: _ExtractorAgent(_module_response(m, [])) for m in EXTRACTION_MODULES}
    extracted, _, _ = extract_scores_by_modules_with_agno(
        agents, db, state, context["narrative"], parallel=False
    )
    assert "class_population_balances" not in payload
    assert extracted["population_transfers"] == []
    assert _snap(db) == before


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


# ── 契约单真源：prompt 教「有灾入/无灾不入」事实支撑 ────────────────────────

def test_prompts_keep_displacement_fact_and_soft_quantity_contracts():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def prompt(name):
        with open(os.path.join(root, "content/prompts", name), encoding="utf-8") as fh:
            return fh.read()

    simulator = prompt("season_simulator.md")
    assert "无对应事实不得臆造流民" in simulator
    assert "不得确定人数或推算人口比例" in simulator

    for name in ("score_extractor_internal.md", "score_extractor_shared.md"):
        extractor = prompt(name)
        assert "class_population_balances" in extractor
        assert "population_unit" in extractor
        assert "不设固定比例或累计 cap" in extractor
