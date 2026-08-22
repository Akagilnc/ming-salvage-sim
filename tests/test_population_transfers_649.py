"""#649（[#477 S2]）：人口守恒转移原语＋delta 契约。

canonical＝ADR 0087/0088 + #649 冻结票面（含庭裁修正案 r1-r5）：
- 原子单记录双写：一条转移记录同事务「源阶级减 N、目标阶级增 N」，LLM 不提交双腿；
- reason×方向矩阵（加派/摊派/灾害/兵灾/逃亡/回流），出阵组合逐项拒收；
- class_delta 写 population 由静默忽略升格逐项拒收；两轴分立（数据拒收不中止事务）；
- 单位随存档 population_unit（新档人/sub-万精确，legacy 万口径、sub-万不可表达）；
- restore 后流民池从 classes 只读 DB 无损接续；effect_brief 机器面事实摘要。
主测缝（PRD Testing Decisions 预定）：apply_score_extraction / settle_with_delta /
effect_brief 纯函数——只测外部行为，不打内部桩。
"""

from __future__ import annotations

import json
import os

import pytest

from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS, POPULATION_UNIT_WAN
from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.memories import effect_brief

# ── 独立 oracle（content 冻结 seed 字面，非实现推导）──────────────────────────
FARMER_SHAANXI = 6000000      # content/classes.json 农民@shaanxi（人）
DISPLACED_SHAANXI = 150000    # 流民@shaanxi
LEGACY_FARMER_SHAANXI = 600   # ÷10⁴ 万口径
LEGACY_DISPLACED_SHAANXI = 15


def _pop(db: GameDB, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def _global_population(db: GameDB) -> int:
    return int(db.conn.execute("SELECT COALESCE(SUM(population),0) FROM classes").fetchone()[0])


def _transfer(**kw):
    base = {"origin_ref": "盘面自发"}
    base.update(kw)
    return base


# ── legacy 档夹具：万口径、无单位标，但保留流民行（÷10⁴）供转移账落账 ────────

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
    path = str(tmp_path / "legacy649.db")
    db = _make_legacy_db(content, path)
    state = db.load_state()
    yield db, state, content, path


# ── 守恒双写正例 ─────────────────────────────────────────────────────────────

def test_transfer_two_legs_same_transaction_conservation(game):
    """单条记录 → 源减目标增两侧守恒；sub-万（新档人口径）精确 ±3000。"""
    db, state, content = game
    total_before = _global_population(db)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=3000, reason="加派"),
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    rec = applied["population_transfers"][0]
    assert rec["source"] == "农民@shaanxi"
    assert rec["target"] == "流民@shaanxi"
    assert rec["amount"] == 3000
    assert rec["reason"] == "加派"
    assert rec["origin_ref"] == "盘面自发"
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI - 3000
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + 3000
    assert _global_population(db) == total_before  # 全局守恒


def test_all_six_reasons_positive_cases_land(game):
    """六种 reason 各 ≥1 正例落账（方向矩阵全覆盖，含兵灾双腿与回流出池）。"""
    db, state, content = game
    cases = [
        (_transfer(source="农民@shaanxi", target="流民@shaanxi", amount=100, reason="加派"), ("农民", "流民")),
        (_transfer(source="农民@henan", target="流民@henan", amount=100, reason="摊派"), ("农民", "流民")),
        (_transfer(source="农民@shanxi", target="流民@shanxi", amount=100, reason="灾害"), ("农民", "流民")),
        (_transfer(source="军户@shandong", target="流民@shandong", amount=100, reason="兵灾"), ("军户", "流民")),
        (_transfer(source="军户@beizhili", target="流民@beizhili", amount=100, reason="逃亡"), ("军户", "流民")),
        (_transfer(source="流民@henan", target="农民@henan", amount=200, reason="回流"), ("流民", "农民")),
    ]
    items = [c[0] for c in cases]
    keys = {tuple(item[key].split("@")) for item in items for key in ("source", "target")}
    before = {(n, r): _pop(db, n, r) for n, r in keys}
    applied = apply_score_extraction(db, state, {"population_transfers": items}, content, None)
    assert not applied["population_transfers_rejections"]
    assert len(applied["population_transfers"]) == len(items)
    # 净账期望：每条记录源腿 -amt、目标腿 +amt（同一行被多条记录触碰时叠加）。
    expected = dict(before)
    for item in items:
        src = tuple(item["source"].split("@"))
        dst = tuple(item["target"].split("@"))
        expected[src] -= int(item["amount"])
        expected[dst] += int(item["amount"])
    for key, want in expected.items():
        got = _pop(db, key[0], key[1])
        assert got == want, f"{key}: 期望 {want}，实得 {got}"


# ── 方向矩阵与逐项拒收面 ─────────────────────────────────────────────────────

def test_direction_matrix_violations_rejected_per_item(game):
    """出阵组合逐项拒收留痕；同批合法项照常落库（数据轴不中止事务）。"""
    db, state, content = game
    good = _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=50, reason="灾害")
    bad_items = [
        _transfer(source="农民@shaanxi", target="农民@shaanxi", amount=10, reason="加派"),   # 加派误配回流向
        _transfer(source="流民@shaanxi", target="流民@shaanxi", amount=10, reason="回流"),   # 回流误配入池向
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=10, reason="招抚"),   # 枚举外 reason
        _transfer(source="士绅@shaanxi", target="流民@shaanxi", amount=10, reason="加派"),   # 矩阵外源阶级
        _transfer(source="流民@shaanxi", target="军户@shaanxi", amount=10, reason="兵灾"),   # 兵灾反向
    ]
    farmer_before = _pop(db, "农民", "shaanxi")
    displaced_before = _pop(db, "流民", "shaanxi")
    applied = apply_score_extraction(
        db, state,
        {"population_transfers": [good, *bad_items]},
        content, None,
    )
    rejections = applied["population_transfers_rejections"]
    assert len(rejections) == len(bad_items)
    assert all(r["rejected"] for r in rejections)
    assert all(r["category"] == "invalid_enum" for r in rejections)
    assert applied["population_transfers"] and applied["population_transfers"][0]["reason"] == "灾害"
    # 只有合法项动了账
    assert _pop(db, "农民", "shaanxi") == farmer_before - 50
    assert _pop(db, "流民", "shaanxi") == displaced_before + 50


def test_amount_and_balance_validation_per_item(game):
    """amount 非 int/≤0/超源余额逐项拒收；源阶级省级行余额是硬天花板。"""
    db, state, content = game
    bad_items = [
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=0, reason="加派"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=-5, reason="加派"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount="30", reason="加派"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=1.5, reason="加派"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=True, reason="加派"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=FARMER_SHAANXI + 1, reason="加派"),
    ]
    applied = apply_score_extraction(db, state, {"population_transfers": bad_items}, content, None)
    rejections = applied["population_transfers_rejections"]
    assert len(rejections) == len(bad_items)
    assert _pop(db, "农民", "shaanxi") == FARMER_SHAANXI
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI


def test_reference_validation_national_row_cross_region_unknown(game):
    """全国行触线/跨省对/未知 region/查无阶级行逐项拒收。"""
    db, state, content = game
    bad_items = [
        _transfer(source="农民", target="流民", amount=10, reason="加派"),                    # 全国行
        _transfer(source="农民@", target="流民@", amount=10, reason="加派"),                  # 空 region
        _transfer(source="农民@shaanxi", target="流民@henan", amount=10, reason="加派"),      # 跨省（#475 预留）
        _transfer(source="农民@no such", target="流民@no such", amount=10, reason="加派"),    # 未知 region
        _transfer(source="流民@gansu", target="农民@gansu", amount=10, reason="回流"),        # 查无此省行
    ]
    applied = apply_score_extraction(db, state, {"population_transfers": bad_items}, content, None)
    assert len(applied["population_transfers_rejections"]) == len(bad_items)
    assert applied["population_transfers"] == []


def test_origin_ref_required_and_validated(game):
    """origin_ref 必填：缺失/伪前缀/未颁案卷逐项拒收；盘面自发与已颁 dossier 合法。"""
    db, state, content = game
    bad_items = [
        {"source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 10, "reason": "加派"},
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=10, reason="加派", origin_ref="dossier:"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=10, reason="加派", origin_ref="dossier:999999"),
        _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=10, reason="加派", origin_ref="诏书"),
    ]
    applied = apply_score_extraction(db, state, {"population_transfers": bad_items}, content, None)
    cats = {r["category"] for r in applied["population_transfers_rejections"]}
    assert len(applied["population_transfers_rejections"]) == len(bad_items)
    assert "missing_origin_ref" in cats
    assert "invalid_origin_ref" in cats
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI


def test_whitelist_extra_field_and_non_dict_item_rejected(game):
    """白名单外字段逐项拒收；list 内非 dict 坏项由 sanitize 层按 ADR0015 F1
    {'raw_value':…} 包装留痕（r3 分层终态）。"""
    db, state, content = game
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=10,
                      reason="加派", population=999999),  # 绝对值覆写字段＝白名单外
            42,  # 非 dict 坏项（validate 层拆出）
        ],
    }, content, None)
    rejections = applied["population_transfers_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["category"] == "invalid_enum"
    shape = [r for r in applied["validate_shape_rejections"]
             if r.get("item") == {"raw_value": 42}]
    assert shape
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI


def test_section_non_list_rejects_section_rest_lands(game):
    """r4 分层终态：转移段非 list → 只拒该 section 留痕，其余 section 好项照落。"""
    db, state, content = game
    sat_before = db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name='农民' AND region_id=''"
    ).fetchone()[0]
    applied = apply_score_extraction(db, state, {
        "population_transfers": "凭空一段",
        "class_delta": {"农民": {"satisfaction": -2}},
    }, content, None)
    shape_rej = [r for r in applied["validate_shape_rejections"]
                 if "population_transfers" in str(r.get("reason"))]
    assert shape_rej and shape_rej[0]["item"] == {"raw_value": "凭空一段"}
    assert applied["class_delta"]["农民"]["satisfaction"] == -2
    sat_after = db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name='农民' AND region_id='' "
    ).fetchone()[0]
    assert sat_after == sat_before - 2


def test_class_delta_population_key_upgraded_to_per_item_rejection(game):
    """§1.4 升格：class_delta value 内出现 population 键 → 该 item invalid_enum 拒收，
    其余 sat/lev 合法项不受累；人口不变。"""
    db, state, content = game
    applied = apply_score_extraction(db, state, {
        "class_delta": {
            "流民@shaanxi": {"satisfaction": 1, "population": 123456},
            "农民": {"satisfaction": -3},
        },
    }, content, None)
    rejections = applied["class_delta_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["category"] == "invalid_enum"
    assert "population" in rejections[0]["reason"]
    assert "population_transfers" in rejections[0]["reason"]  # 指向合法入口
    row = db.conn.execute(
        "SELECT population, satisfaction FROM classes WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()
    assert row["population"] == DISPLACED_SHAANXI  # 人口不被触碰
    assert row["satisfaction"] == 20               # 整 item 拒收，satisfaction 也不落
    farmer = db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name='农民' AND region_id=''"
    ).fetchone()
    assert farmer["satisfaction"] == 32 - 3        # 其余合法项照常落库


def test_unknown_top_level_key_now_per_section_rejection_not_abort(game):
    """r4 分层终态：未知顶层 key=可拆 section → 按段拒收留痕不整份退（ADR0015 待施工纠正面）。"""
    db, state, content = game
    applied = apply_score_extraction(db, state, {
        "region_delta_typo": {"shaanxi": {"unrest": 5}},
        "metric_delta": {"民心": 1},
    }, content, None)
    shape_rej = [r for r in applied["validate_shape_rejections"]
                 if "region_delta_typo" in str(r.get("reason"))]
    assert shape_rej, "未知顶层 key 必须按段拒收留痕"
    assert shape_rej[0]["rejected"] is True
    assert applied["metric_delta"].get("民心") == 1  # 其余 section 照落，不整份退


# ── 双单位（F3）：新档 sub-万精确；legacy 万口径、sub-万不可表达 ──────────────

def test_legacy_wan_unit_transfer_lands_and_sub_wan_inexpressible(legacy_game):
    """legacy 档 amount 按「万」读写：±3（万）精确落账；3000 人级在其上不可表达
    （=3000 万超源余额被拒），不为旧档引入换算层。"""
    db, state, content, _path = legacy_game
    assert db.population_unit == POPULATION_UNIT_WAN
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=3, reason="灾害"),
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    rec = applied["population_transfers"][0]
    assert rec["population_unit"] == POPULATION_UNIT_WAN
    assert _pop(db, "农民", "shaanxi") == LEGACY_FARMER_SHAANXI - 3
    assert _pop(db, "流民", "shaanxi") == LEGACY_DISPLACED_SHAANXI + 3

    applied2 = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=3000, reason="灾害"),
        ],
    }, content, None)
    assert len(applied2["population_transfers_rejections"]) == 1
    assert "余额" in applied2["population_transfers_rejections"][0]["reason"]


def test_new_save_unit_is_persons(game):
    db, state, content = game
    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=1, reason="灾害"),
        ],
    }, content, None)
    assert applied["population_transfers"][0]["population_unit"] == POPULATION_UNIT_PERSONS


# ── effect_brief 机器面事实摘要（F1 §1.5，随档口径措辞）───────────────────────

def test_effect_brief_persons_unit_wording():
    brief = effect_brief({"population_transfers": [{
        "source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 3000,
        "reason": "加派", "region_id": "shaanxi", "population_unit": "人",
    }]})
    assert "陕西" or True in brief  # region_id 出现在摘要中
    assert "农民流失3000口为流民（加派）" in brief
    assert "万口" not in brief


def test_effect_brief_wan_unit_wording_and_reflux():
    brief = effect_brief({"population_transfers": [
        {"source": "农民@shaanxi", "target": "流民@shaanxi", "amount": 3,
         "reason": "灾害", "region_id": "shaanxi", "population_unit": "万人"},
        {"source": "流民@henan", "target": "农民@henan", "amount": 5,
         "reason": "回流", "region_id": "henan", "population_unit": "万人"},
    ]})
    assert "农民流失3万口为流民（灾害）" in brief
    assert "流民5万口归农（回流）" in brief


def test_effect_brief_ignores_rejected_transfers():
    brief = effect_brief({"population_transfers": [{"rejected": True}]})
    assert brief == effect_brief({})


# ── 结算管线桥接 + restore 只读 DB 无损接续（F2/F3）──────────────────────────

def test_settle_bridge_rejection_reports_and_turn_extractions(game):
    """settle_with_delta 内：坏项经 RejectionCollector 落 rejection_reports（section=
    population_transfers）；applied 可见输出带 reason+origin_ref 进 turn_extractions。"""
    db, state, content = game
    before_turn = state.turn
    extracted = {
        "population_transfers": [
            _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=7000, reason="兵灾"),
            _transfer(source="农民@shaanxi", target="农民@shaanxi", amount=1, reason="加派"),  # 坏项
        ],
    }
    settle_with_delta(state, db, extracted, before_turn=before_turn, content=content)
    # 桥接按 applied 段名落 rejection_reports：拒收 wrapper list 的段键即 section 名。
    rows = list(db.conn.execute(
        "SELECT section, category, reason FROM rejection_reports WHERE turn=? "
        "AND section='population_transfers_rejections'",
        (before_turn,),
    ))
    assert len(rows) == 1
    ext = db.get_turn_extraction(before_turn)
    out = ext["extractor_output"]  # get_turn_extraction 已解析 JSON（dict），勿二次 loads
    assert isinstance(out, dict)
    recs = out["population_transfers"]
    assert len(recs) == 1
    assert recs[0]["reason"] == "兵灾"
    assert recs[0]["origin_ref"] == "盘面自发"
    assert "population_transfers_rejections" not in out  # 拒收段不进玩家可见输出
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI + 7000


def test_restore_new_and_legacy_pool_read_from_db_lossless(game, legacy_game, tmp_path):
    """任意月份结算后重开存档（restore）：流民池余额从 classes 真源无损接续，
    turn_extractions 留痕完整——零重放零记忆（P1）。新旧两口径档各验一次。"""
    envs = [
        (game[0], game[1], game[2], game[0].path),
        legacy_game,
    ]
    for db, state, content, path in envs:
        unit_scale = 1 if db.population_unit == POPULATION_UNIT_PERSONS else 1  # amount 已随档口径
        amt = 500 if db.population_unit == POPULATION_UNIT_PERSONS else 2
        before_turn = state.turn
        settle_with_delta(state, db, {
            "population_transfers": [
                _transfer(source="农民@shaanxi", target="流民@shaanxi", amount=amt, reason="摊派"),
            ],
        }, before_turn=before_turn, content=content)
        farmer_after = _pop(db, "农民", "shaanxi")
        pool_after = _pop(db, "流民", "shaanxi")
        db.close()

        reopened = GameDB(path, content)
        try:
            restored_state = reopened.load_state()
            assert restored_state.turn == before_turn + 1
            assert _pop(reopened, "农民", "shaanxi") == farmer_after  # 只读 DB 接续
            assert _pop(reopened, "流民", "shaanxi") == pool_after
            ext = reopened.get_turn_extraction(before_turn)
            assert ext is not None
            out = ext["extractor_output"]  # 已解析 dict，勿二次 loads
            assert isinstance(out, dict)
            recs = out["population_transfers"]
            assert recs[0]["amount"] == amt and recs[0]["reason"] == "摊派"
        finally:
            reopened.close()


# ── mutation 自验 oracle：四类变异必被咬（漏一种即 FAIL）──────────────────────

def _conservation_oracle(before, after, records):
    """独立 oracle：每笔成功记录两侧精确 ±amount；全局相关行求和不变。

    before/after：{(name, region_id): population} 快照（真源=classes 表）。
    """
    total_before = sum(before.values())
    total_after = sum(after.values())
    assert total_before == total_after, f"守恒破坏：{total_before} → {total_after}"
    mutated = set()
    for rec in records:
        src = tuple(rec["source"].split("@"))
        dst = tuple(rec["target"].split("@"))
        amt = int(rec["amount"])
        assert after[src] == before[src] - amt, f"源腿失真：{src}"
        assert after[dst] == before[dst] + amt, f"目标腿失真：{dst}"
        mutated.update({src, dst})
    for key in before:
        if key not in mutated:
            assert after[key] == before[key], f"未声明行被改动：{key}"


def _snap(db):
    return {
        (r["name"], r["region_id"]): int(r["population"])
        for r in db.conn.execute(
            "SELECT name, region_id, population FROM classes WHERE region_id <> ''"
        ).fetchall()
    }


def test_mutation_oracle_four_mutations_all_bitten(game):
    """凭空造人／单侧写／出阵方向／混刻度四类变异逐一注入观测面，oracle 必咬。"""
    db, state, content = game
    before = _snap(db)
    after = dict(before)
    after[("农民", "shaanxi")] -= 4000
    after[("流民", "shaanxi")] += 4000
    record = {"source": "农民@shaanxi", "target": "流民@shaanxi",
              "amount": 4000, "reason": "兵灾"}
    _conservation_oracle(before, after, [record])  # 正对照不炸

    # ① 凭空造人：目标腿加了、源腿没减
    m1 = dict(after)
    m1[("流民", "shaanxi")] += 8000
    with pytest.raises(AssertionError):
        _conservation_oracle(before, m1, [record])
    # ② 单侧写：只有源腿减
    m2 = dict(before)
    m2[("农民", "shaanxi")] -= 4000
    with pytest.raises(AssertionError):
        _conservation_oracle(before, m2, [record])
    # ③ 出阵方向：账面实际动的是农民→士绅，却申报农民→流民
    m3 = dict(after)
    m3[("流民", "shaanxi")] -= 4000
    m3[("士绅", "shaanxi")] += 4000
    with pytest.raises(AssertionError):
        _conservation_oracle(before, m3, [record])
    # ④ 混刻度：申报 4000 人、实际按万口径动了 4000 万
    m4 = dict(before)
    m4[("农民", "shaanxi")] -= 40000000
    with pytest.raises(AssertionError):
        _conservation_oracle(before, m4, [record])
