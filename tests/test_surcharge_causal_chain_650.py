"""#650（[#477 S3]）：明渠加派 e2e 因果链。

canonical＝ADR 0089（明渠）＋0087（人口守恒转移）＋#650 票面（庭判 run
01a02d46 通过）。因果五环：皇帝下旨加派 → 逐省累积账当回合落库（P1）→
结算按账机械驱动农民→流民入池（量级 clamp，0087 applier 机械转移）→
邸报/召对输入侧事实回响（ADR 0143：只断 effect_brief 事实平面，不钉散文）
→ 停加派/蠲免后入池止（出口回流归 S5 #652）。

主测缝（PRD Testing Decisions 预定）：apply_score_extraction / settle_with_delta /
apply_historical_fiscal_rates（饷率 effect 通道）——只测外部行为，不打内部桩。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS, POPULATION_UNIT_WAN
from ming_sim.decree import settle_with_delta
from ming_sim.exceptions import SettlementAbort
from ming_sim.issues import apply_historical_fiscal_rates, apply_score_extraction
import ming_sim.issues as issues
from ming_sim.memories import effect_brief
import ming_sim.memories as memories

# ── 独立 oracle（content 冻结 seed 字面，非实现推导）──────────────────────────
FARMER_SHAANXI = 6000000      # content/classes.json 农民@shaanxi（人）
DISPLACED_SHAANXI = 150000    # 流民@shaanxi
SHAANXI_SUPPORT = 32          # content/regions.json 陕西 public_support seed
LIAO_SEED_SHAANXI = 2929.20151 * 0.009 / 12.0  # 辽饷九厘基线（万两/月）

# 明渠折算口径（票面 AC2「确定性可断言」；常数真源=ming_sim/constants.py）：
#   入池(人) = 加派基线(万两) × 折率 × (100 − 民心)/100


def _pop(db: GameDB, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def _settle_payload(db: GameDB, region_id: str) -> dict:
    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id=?", (region_id,)
    ).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _decree(db: GameDB, state, region_id="shaanxi", monthly_amount=10.0, **kw):
    if "origin_ref" not in kw:
        dossier_id = db.create_decree_dossier(
            state, action_type="policy", decree_text=f"{region_id}加派",
            target_kind="region", target_id=region_id,
        )
        db.record_dossier_decision(dossier_id, "promulgated")
        kw["origin_ref"] = f"dossier:{dossier_id}"
    item = {"region_id": region_id, "monthly_amount": monthly_amount}
    item.update(kw)
    return item


def _expected_inflow_persons(base_wan: float, support: int) -> int:
    from ming_sim.constants import LEVY_DISPLACEMENT_RATE
    return int(round(base_wan * LEVY_DISPLACEMENT_RATE * (100 - support) / 100.0))


# ── AC1：加派旨当回合落逐省累积账；无旨不入账 ─────────────────────────────────

def test_surcharge_prompt_and_schema_only_teach_effect_eligible_dossiers():
    """加派专属来源契约不得继承其它 delta section 的自然演化哨兵。"""
    root = Path(__file__).parents[1]
    prompt = (root / "content/prompts/score_extractor_shared.md").read_text(encoding="utf-8")
    schema = (root / "docs/DELTA_SCHEMA.md").read_text(encoding="utf-8")
    prompt_row = next(line for line in prompt.splitlines() if line.startswith("| `加派` |"))
    surcharge_section = schema.split("### `surcharge_decrees`", 1)[1].split("### `region_delta`", 1)[0]

    for contract in (prompt_row, surcharge_section):
        assert "dossier:<正整数>" in contract
        assert "效果资格" in contract
        assert "不得使用 `盘面自发`" in contract


def test_decree_lands_accumulated_ledger_same_turn(game):
    """一道加派旨 → settle._meta 加派基线当回合累加落库（P1）；p 三饷应征未被本段直改。"""
    db, state, content = game
    before = _settle_payload(db, "shaanxi")
    assert "_meta" not in before or before["_meta"].get("加派基线") is None

    applied = apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=10.0)],
    }, content, None)
    assert not applied["surcharge_decrees_rejections"]
    rec = applied["surcharge_decrees"][0]
    assert rec["region_id"] == "shaanxi"
    assert rec["monthly_amount"] == 10.0
    assert not rec.get("rejected")

    meta = _settle_payload(db, "shaanxi")["_meta"]
    assert meta["加派基线"] == pytest.approx(10.0)
    assert "加派基线源" not in meta


def test_no_decree_no_ledger_entry(game):
    """无旨不入账：空段结算后加派基线不动（开局档无此键仍无此键）。"""
    db, state, content = game
    applied = apply_score_extraction(db, state, {"surcharge_decrees": []}, content, None)
    assert not applied["surcharge_decrees_rejections"]
    meta = _settle_payload(db, "shaanxi").get("_meta") or {}
    assert meta.get("加派基线") is None


def test_repeated_decrees_accumulate_and_negative_stops(game):
    """多道旨逐月累加；负额（停征/蠲免）减账且钳制 ≥0。"""
    db, state, content = game
    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=8.0), _decree(db, state,monthly_amount=10.0),
                              _decree(db, state,region_id="henan", monthly_amount=5.0)],
    }, content, None)
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(18.0)
    assert _settle_payload(db, "henan")["_meta"]["加派基线"] == pytest.approx(5.0)

    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=-5.0)],
    }, content, None)
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(13.0)

    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=-99.0)],  # 蠲免全停
    }, content, None)
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(0.0)


def test_decree_bad_items_rejected_individually(game):
    """坏项逐项拒收留痕、好项照落（ADR 0015/0008 两轴分立）。"""
    db, state, content = game
    applied = apply_score_extraction(db, state, {
        "surcharge_decrees": [
            _decree(db, state,),                                    # 好项
            _decree(db, state,region_id="mars", monthly_amount=1.0),  # 未知省
            {"region_id": "shaanxi", "monthly_amount": True, "origin_ref": "盘面自发"},
            {"region_id": "shaanxi", "monthly_amount": 1.0},  # 缺 origin_ref
            _decree(db, state,monthly_amount=1.0, extra="白名单外"),
        ],
    }, content, None)
    assert len(applied["surcharge_decrees"]) == 1
    assert len(applied["surcharge_decrees_rejections"]) == 4
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(10.0)


def test_surcharge_origin_requires_effect_eligible_materialized_dossier(game):
    db, state, content = game
    proposed = db.create_decree_dossier(
        state, action_type="policy", decree_text="拟加派", target_kind="region",
        target_id="shaanxi",
    )
    promulgated = db.create_decree_dossier(
        state, action_type="policy", decree_text="准加派", target_kind="region",
        target_id="shaanxi",
    )
    db.record_dossier_decision(promulgated, "promulgated")
    items = [
        _decree(db, state, monthly_amount=2.0, origin_ref=f"dossier:{promulgated}"),
        _decree(db, state, monthly_amount=7.0, origin_ref=f"dossier:{proposed}"),
        _decree(db, state, monthly_amount=7.0, origin_ref="dossier:999999"),
        _decree(db, state, monthly_amount=7.0, origin_ref="event:1"),
        _decree(db, state, monthly_amount=7.0, origin_ref=""),
        _decree(db, state, monthly_amount=7.0, origin_ref="盘面自发"),
    ]
    applied = apply_score_extraction(db, state, {"surcharge_decrees": items}, content, None)
    assert len(applied["surcharge_decrees"]) == 1
    assert len(applied["surcharge_decrees_rejections"]) == 5
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(2.0)


def test_repeated_delta_apply_does_not_consume_levy_ledger(game):
    db, state, content = game
    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state, monthly_amount=10.0)],
    }, content, None)
    before = _pop(db, "流民", "shaanxi")
    for delta in ({}, {}, {"metric_delta": {"皇威": 1}}):
        applied = apply_score_extraction(db, state, delta, content, None)
        assert not [r for r in applied["population_transfers"] if r.get("reason") == "加派"]
    assert _pop(db, "流民", "shaanxi") == before


def test_rejection_bucket_is_not_persisted_to_player_visible_extraction(game):
    """真实 settle 保留内部拒收报告，但玩家可见 extraction 不泄露拒收桶或坏项。"""
    db, state, content = game
    before_turn = state.turn
    settle_with_delta(state, db, {
        "surcharge_decrees": [
            _decree(db, state,monthly_amount=3.0),
            _decree(db, state,region_id="mars", monthly_amount=1.0),
        ],
    }, before_turn=before_turn, content=content)

    assert db.conn.execute(
        "SELECT 1 FROM rejection_reports WHERE turn=? AND section='surcharge_decrees_rejections'",
        (before_turn,),
    ).fetchone() is not None
    visible = db.get_turn_extraction(before_turn)["extractor_output"]
    assert "surcharge_decrees_rejections" not in visible
    assert "mars" not in json.dumps(visible, ensure_ascii=False)


def test_chinese_aliases_canonicalize(game):
    """中文别名（加派／月增额）经 canonicalize_extraction（生产管线同缝）归一后照落。"""
    db, state, content = game
    from ming_sim.simulation import canonicalize_extraction
    decree = _decree(db, state, monthly_amount=6.0)
    applied = apply_score_extraction(db, state, canonicalize_extraction({
        "加派": [{"地区编号": "shaanxi", "月增额": 6.0,
                 "来源引用": decree["origin_ref"]}],
    }), content, None)
    assert not applied["surcharge_decrees_rejections"]
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(6.0)


# ── AC1 后半：明选有明账——加派基线折入三饷底座（钱真被征上来）───────────────

def test_levy_pass_folds_jiapai_into_sanxiang_targets(game):
    """饷率通道重算时 加派基线 计入 三饷应征 与 起运定额（公开代价＝真征收）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year, state.period = 1627, 10
    db.save_state(state)

    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=10.0)],
    }, content, None)
    apply_historical_fiscal_rates(state, db)

    settle = _settle_payload(db, "shaanxi")
    expected = LIAO_SEED_SHAANXI + 10.0
    assert math.isclose(settle["p"]["三饷应征"], expected, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(settle["p"]["起运定额"], settle["_meta"]["正赋起运基线"] + expected,
                        rel_tol=1e-9, abs_tol=1e-9)


# ── AC2：结算按账入池，口径确定性可断言 ───────────────────────────────────────

def test_settlement_drives_deterministic_pool_inflow(game):
    """有账省份结算即按确定性口径入池（clamp 前的期望值独立 oracle 可算）；无账省不动。"""
    db, state, content = game
    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=10.0)],
    }, content, None)

    want = _expected_inflow_persons(10.0, SHAANXI_SUPPORT)
    assert want > 0
    farmer_before, pool_before = _pop(db, "农民", "shaanxi"), _pop(db, "流民", "shaanxi")

    before_turn = state.turn
    settle_with_delta(state, db, {}, before_turn=before_turn, content=content)  # 本月无新旨
    applied = db.get_turn_extraction(before_turn)["extractor_output"]
    recs = [r for r in applied["population_transfers"]
            if r.get("reason") == "加派" and r.get("region_id") == "shaanxi"]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["amount"] == want
    assert rec["source"] == "农民@shaanxi"
    assert rec["target"] == "流民@shaanxi"
    assert rec["origin_ref"] == "盘面自发"
    assert _pop(db, "农民", "shaanxi") == farmer_before - want
    assert _pop(db, "流民", "shaanxi") == pool_before + want


def test_ming_province_without_fiscal_base_is_not_a_levy_member(game):
    """合法无 settle 基座的明省自然出列，不阻断空 delta；无账人口不动。"""
    db, state, content = game
    fiscal = json.loads(db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='henan'"
    ).fetchone()[0])
    fiscal.pop("settle", None)
    db.conn.execute("UPDATE regions SET fiscal=? WHERE id='henan'",
                    (json.dumps(fiscal, ensure_ascii=False),))
    db.conn.commit()
    before = _pop(db, "流民", "henan")
    applied = apply_score_extraction(db, state, {}, content, None)
    assert not [r for r in applied["population_transfers"] if r.get("region_id") == "henan"]
    assert _pop(db, "流民", "henan") == before


def test_zero_base_province_gets_no_transfer(game):
    """无账（基线 0）省份零入池——停征后入池止的机制面。"""
    db, state, content = game
    pool_before = _pop(db, "流民", "henan")
    applied = apply_score_extraction(db, state, {}, content, None)
    henan = [r for r in applied["population_transfers"] if r.get("region_id") == "henan"]
    assert henan == []
    assert _pop(db, "流民", "henan") == pool_before


def test_inflow_clamped_to_farmer_balance(game):
    """量级 clamp：折算值超农民余额时钳到余额，不凭空造人也不产生拒收噪音。"""
    db, state, content = game
    db.conn.execute("UPDATE classes SET population=500 WHERE name='农民' AND region_id='shaanxi'")
    db.conn.commit()
    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=1000.0)],
    }, content, None)
    before_turn = state.turn
    settle_with_delta(state, db, {}, before_turn=before_turn, content=content)
    applied = db.get_turn_extraction(before_turn)["extractor_output"]
    assert not [r for r in applied["population_transfers"] if r.get("rejected")]
    assert _pop(db, "农民", "shaanxi") == 0
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + 500


# ── 持久累积账损坏须 fail-loud，月效来源不得伪归最后一道旨 ───────────────────

@pytest.mark.parametrize("corruption", ["bad_json", "bad_base", "missing_pool"])
def test_levy_ledger_corruption_fails_loud(game, corruption):
    db, state, content = game
    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=10.0)],
    }, content, None)
    if corruption == "bad_json":
        db.conn.execute("UPDATE regions SET fiscal='{' WHERE id='shaanxi'")
    elif corruption == "bad_base":
        fiscal = json.loads(db.conn.execute(
            "SELECT fiscal FROM regions WHERE id='shaanxi'"
        ).fetchone()[0])
        fiscal["settle"]["_meta"]["加派基线"] = "十万两"
        db.conn.execute("UPDATE regions SET fiscal=? WHERE id='shaanxi'",
                        (json.dumps(fiscal, ensure_ascii=False),))
    else:
        db.conn.execute("DELETE FROM classes WHERE name='流民' AND region_id='shaanxi'")
    db.conn.commit()

    with pytest.raises(SettlementAbort) as caught:
        settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "shaanxi" in str(caught.value.__cause__)


def test_accumulated_monthly_effect_uses_ledger_origin_not_latest_decree(game):
    db, state, content = game
    first = db.create_decree_dossier(state, action_type="policy", decree_text="陕西加派", target_kind="region", target_id="shaanxi")
    second = db.create_decree_dossier(state, action_type="policy", decree_text="陕西续派", target_kind="region", target_id="shaanxi")
    db.record_dossier_decision(first, "promulgated")
    db.record_dossier_decision(second, "promulgated")
    before_turn = state.turn
    settle_with_delta(state, db, {
        "surcharge_decrees": [
            _decree(db, state,monthly_amount=4.0, origin_ref=f"dossier:{first}"),
            _decree(db, state,monthly_amount=6.0, origin_ref=f"dossier:{second}"),
        ],
    }, before_turn=before_turn, content=content)
    applied = db.get_turn_extraction(before_turn)["extractor_output"]
    transfer = next(r for r in applied["population_transfers"] if r["reason"] == "加派")
    assert transfer["origin_ref"] == "盘面自发"
    assert "加派基线源" not in _settle_payload(db, "shaanxi")["_meta"]


# ── AC3：真实玩家回响链（结构化事实输入→自由叙事原样持久化→召对读链）──────────

def test_levy_fact_enters_existing_public_read_chain_and_writer_keeps_free_next_report(game):
    """连续两月真实结算：首月机器事实进逐来源读链；次月既有 writer 原样保存自由邸报。"""
    db, state, content = game
    first_turn = state.turn
    settle_with_delta(
        state, db, {"surcharge_decrees": [_decree(db, state,monthly_amount=10.0)]},
        before_turn=first_turn, content=content, narrative="陕西加派月报。",
    )
    want = _expected_inflow_persons(10.0, SHAANXI_SUPPORT)
    fact = f"陕西农民流失{want}口为流民（加派）"
    public_read = " ".join(
        item.get("body", "") for item in db.get_character_knowledge(state, "温体仁")["public_events"]
    )
    assert fact in public_read

    free_body = "陕西流民渐起，关中贼势暗流潜滋。"
    second_turn = state.turn
    # 此处 narrative 代表既有 player-facing simulator 的自由输出；archive writer 未替换。
    settle_with_delta(
        state, db, {"surcharge_decrees": [_decree(db, state,monthly_amount=-10.0)]},
        before_turn=second_turn, content=content, narrative=free_body,
    )
    assert db.get_turn_report(second_turn) == free_body
    public_read = " ".join(
        item.get("body", "") for item in db.get_character_knowledge(state, "温体仁")["public_events"]
    )
    assert free_body in public_read


def test_effect_brief_carries_levy_echo_fact(game):
    db, state, content = game
    before_turn = state.turn
    settle_with_delta(state, db, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=10.0)],
    }, before_turn=before_turn, content=content)
    applied = db.get_turn_extraction(before_turn)["extractor_output"]
    brief = effect_brief(applied)
    want = _expected_inflow_persons(10.0, SHAANXI_SUPPORT)
    assert f"陕西农民流失{want}口为流民（加派）" in brief


# ── legacy 万口径档：折算随存档单位换算，sub-万不可表达 ────────────────────────

def _make_legacy_db(content, path: str) -> GameDB:
    db = GameDB(path, content)
    db.seed_static_data()
    db.conn.execute("UPDATE classes SET population = population / 10000")
    db.conn.execute("UPDATE regions SET population = population / 10000")
    db.conn.execute("DELETE FROM save_meta WHERE key='population_unit'")
    db.conn.commit()
    return db


@pytest.fixture
def legacy_game(content, tmp_path):
    db = _make_legacy_db(content, str(tmp_path / "legacy650.db"))
    state = db.load_state()
    yield db, state, content


def test_legacy_wan_unit_inflow_scaled_to_save_unit(legacy_game):
    db, state, content = legacy_game
    apply_score_extraction(db, state, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=50.0)],
    }, content, None)
    before_turn = state.turn
    settle_with_delta(state, db, {}, before_turn=before_turn, content=content)
    applied = db.get_turn_extraction(before_turn)["extractor_output"]
    recs = [r for r in applied["population_transfers"]
            if r.get("reason") == "加派" and r.get("region_id") == "shaanxi"]
    assert len(recs) == 1
    want_wan = int(round(_expected_inflow_persons(50.0, SHAANXI_SUPPORT) / 10000))
    assert recs[0]["amount"] == want_wan > 0
    assert recs[0]["population_unit"] == POPULATION_UNIT_WAN


# ── AC4/AC5：e2e 验收锚用例①前半——陕西加派→流民↑→回响；restore 接续；停加派止 ──

def test_e2e_shaanxi_decree_pool_rises_restore_resumes_stop_halts(game):
    """settle_with_delta 全缝：加派月→流民↑＋effect_brief 回响；restore 只读 DB 无损接续；
    停征月入池止（出口回流归 S5 #652，不在本票）。"""
    db, state, content = game
    # 第 1 月：下旨加派
    before_turn = state.turn
    applied = settle_with_delta(state, db, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=10.0)],
    }, before_turn=before_turn, content=content)
    pool_m1 = _pop(db, "流民", "shaanxi")
    want_m1 = _expected_inflow_persons(10.0, SHAANXI_SUPPORT)
    assert pool_m1 == DISPLACED_SHAANXI + want_m1
    ext = db.get_turn_extraction(before_turn)
    recs = [r for r in (ext["extractor_output"].get("population_transfers") or [])
            if r.get("reason") == "加派"]
    assert len(recs) == 1 and recs[0]["amount"] == want_m1
    db.close()

    # restore：重开存档，只读 DB 接续（P1 判据）
    db = GameDB(db.path, content)
    state = db.load_state()
    assert state.turn == before_turn + 1
    assert _pop(db, "流民", "shaanxi") == pool_m1
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(10.0)

    # 第 2 月：无新旨，常设加派继续入池（渐起）
    before_turn = state.turn
    settle_with_delta(state, db, {}, before_turn=before_turn, content=content)
    pool_m2 = _pop(db, "流民", "shaanxi")
    assert pool_m2 == pool_m1 + want_m1

    # 第 3 月：停征（蠲免全停）→ 入池止
    before_turn = state.turn
    settle_with_delta(state, db, {
        "surcharge_decrees": [_decree(db, state,monthly_amount=-10.0)],
    }, before_turn=before_turn, content=content)
    assert _settle_payload(db, "shaanxi")["_meta"]["加派基线"] == pytest.approx(0.0)
    pool_m3 = _pop(db, "流民", "shaanxi")

    # 第 4 月：账已清，零入池
    before_turn = state.turn
    settle_with_delta(state, db, {}, before_turn=before_turn, content=content)
    assert _pop(db, "流民", "shaanxi") == pool_m3
    db.close()
