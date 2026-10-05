"""#648（[#477 S1]）：人口单位「人」＋流民第八阶级 seed。

canonical＝ADR 0087/0088 + 票面冻结修正案 r1/r2（#1843 旧档万人双口径已退役）：
- F1：extractor class 写面只收 satisfaction/leverage，population 更新面删除；
- F2：机面 TSV 裸人 / 玩家面 LLM 输入投影「约N万口」（正向 prompt，零删改）；
- F3：流民冻结 seed 表（陕西15万/河南5万/内地其余省0；#659 辽东/东江边镇切片0；
      全国=省级求和派生；satisfaction 基线30 陕西20 河南25 / leverage 5 / agenda 冻结句）；
- F4：新档 DB 持久标「人」，不读 content 元信息。
"""

from __future__ import annotations

import pytest

from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.issues import (
    apply_score_extraction,
    bind_content as issues_bind_content,
)

# ── F3/r2 冻结 seed oracle（独立真源=票面冻结表，非实现推导）──────────────────
AGENDA_FROZEN = "就食求赈，流徙谋生"
DISPLACED_PROVINCES = [
    "beizhili", "nanzhili", "shandong", "shanxi", "henan", "shaanxi", "zhejiang",
    "jiangxi", "huguang", "sichuan", "fujian", "guangdong", "guangxi", "yunnan", "guizhou",
    # #659 边镇军户逃亡闭环：仅军户/流民切片，流民初值 0
    "liaodong", "dongjiang_area",
]
SHAANXI_POP, SHAANXI_SAT = 150000, 20
HENAN_POP, HENAN_SAT = 50000, 25
DEFAULT_DISPLACED_POP, DEFAULT_SAT, DEFAULT_LEV = 0, 30, 5
NATIONAL_DISPLACED_POP = SHAANXI_POP + HENAN_POP  # 全国行=省级求和派生

# regions/classes ×10⁴ 抽样钉（旧 content 万人口径字面 × 10000，独立算术）
BEIZHILI_POP_PERSONS = 720 * 10000
FARMER_NATIONAL_POP_PERSONS = 11000 * 10000


def _displaced_rows(db: GameDB):
    return db.conn.execute(
        "SELECT name, region_id, population, satisfaction, leverage, agenda "
        "FROM classes WHERE name='流民' ORDER BY region_id"
    ).fetchall()




# ── 新档 classes seed（F3/r2 冻结表 + ×10⁴）─────────────────────────────────

def test_new_save_displaced_class_seed_frozen_table(game):
    """F3/r2：流民第八阶级省切片＋全国，冻结 seed 表逐字段钉死（含 #659 边镇）。"""
    db, _, _ = game
    rows = _displaced_rows(db)
    assert len(rows) == len(DISPLACED_PROVINCES) + 1  # 省切片 + 全国

    by_region = {r["region_id"]: r for r in rows}
    assert set(by_region) == set(DISPLACED_PROVINCES) | {""}

    # 灾区覆写：陕西 15万/20、河南 5万/25（单位：人）
    assert by_region["shaanxi"]["population"] == SHAANXI_POP
    assert by_region["shaanxi"]["satisfaction"] == SHAANXI_SAT
    assert by_region["henan"]["population"] == HENAN_POP
    assert by_region["henan"]["satisfaction"] == HENAN_SAT

    # 其余省（含 #659 辽东/东江）population=0，satisfaction 取统一基线
    for prov in DISPLACED_PROVINCES:
        if prov in ("shaanxi", "henan"):
            continue
        assert by_region[prov]["population"] == DEFAULT_DISPLACED_POP, prov
        assert by_region[prov]["satisfaction"] == DEFAULT_SAT, prov

    # 全部行 leverage=5、agenda 冻结句
    for r in rows:
        assert r["leverage"] == DEFAULT_LEV, r["region_id"]
        assert r["agenda"] == AGENDA_FROZEN, r["region_id"]

    # 全国行 = 省级求和派生（展示汇总），基线三字段
    nat = by_region[""]
    assert nat["population"] == NATIONAL_DISPLACED_POP
    assert nat["population"] == sum(by_region[p]["population"] for p in DISPLACED_PROVINCES)
    assert nat["satisfaction"] == DEFAULT_SAT
    assert nat["leverage"] == DEFAULT_LEV
    assert nat["agenda"] == AGENDA_FROZEN


def test_new_save_classes_seed_persons_scale(game):
    """既有七阶级 seed 机械 ×10⁴（漏乘/重乘必咬）：抽样钉裸人数。"""
    db, _, _ = game
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name='农民' AND region_id=''"
    ).fetchone()
    assert row["population"] == FARMER_NATIONAL_POP_PERSONS


def test_new_save_regions_seed_persons_scale(game):
    """regions seed 机械 ×10⁴：北直隶 720万 → 7200000 人。"""
    db, _, _ = game
    row = db.conn.execute(
        "SELECT population FROM regions WHERE id='beizhili'"
    ).fetchone()
    assert row["population"] == BEIZHILI_POP_PERSONS


def test_new_save_persistent_population_unit_marker(game):
    """F4：新档 DB 落持久单位标「人」；判别只读存档 DB，不读 content 元信息。"""
    db, _, _ = game
    assert db.population_unit == POPULATION_UNIT_PERSONS
    row = db.conn.execute(
        "SELECT value FROM save_meta WHERE key='population_unit'"
    ).fetchone()
    assert row is not None and row["value"] == POPULATION_UNIT_PERSONS



# ── class_delta 写面（人口不经 class delta）──────────────────────────────────


def test_class_delta_displaced_accepts_sat_lev_population_face_removed(game):
    """流民行接受 satisfaction/leverage 更新落库；population 更新面已删除（不得单边改人口）。"""
    db, state, content = game
    issues_bind_content(content)

    apply_score_extraction(db, state, {
        "class_delta": {"流民@shaanxi": {"satisfaction": -5, "leverage": 2}},
    }, content, None)
    row = db.conn.execute(
        "SELECT population, satisfaction, leverage FROM classes "
        "WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()
    assert row["satisfaction"] == SHAANXI_SAT - 5
    assert row["leverage"] == DEFAULT_LEV + 2
    assert row["population"] == SHAANXI_POP  # 人口不经 class delta 触碰（留给 #649 转移账）

    # population 字段混进合法 key 的 item：#649 §1.4 升格——整项逐项拒收（原静默忽略），
    # 人口不被触碰，同 item 的 sat 也不落（拒收面＝整个 item）。
    applied = apply_score_extraction(db, state, {
        "class_delta": {"流民@shaanxi": {"satisfaction": 1, "population": 123456}},
    }, content, None)
    rejections = applied["class_delta_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["category"] == "invalid_enum"
    row2 = db.conn.execute(
        "SELECT population, satisfaction FROM classes "
        "WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()
    assert row2["satisfaction"] == SHAANXI_SAT - 5  # 混写 population 的 item 整项不落
    assert row2["population"] == SHAANXI_POP


# ── web 玩家面：UI 直显模板已删（P7），机面 population 单一真源 ───────────────

def test_web_region_payload_has_no_population_wan_projection(game):
    """W1（P7）：web 地区载荷不再有 population_wan 直显投影——玩家面人口
    呈现走 simulator seam featured input + LLM 长出叙事，UI 无固定模板；
    地图节点与地区载荷同源 db.region_payload()（机面 population 原样）。"""
    from types import SimpleNamespace

    import web_app

    new_db, new_state, content = game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=new_db, state=new_state, content=content)

    regions = runtime.db.region_payload()
    assert all("population_wan" not in row for row in regions)
    bz = next(r for r in regions if r["id"] == "beizhili")
    assert bz["population"] == BEIZHILI_POP_PERSONS  # 机面单一真源，不動

    nodes = {n["id"]: n for n in runtime.map_nodes()}
    node_bz = nodes["beizhili"]["region"]
    assert "population_wan" not in node_bz
    assert node_bz["population"] == BEIZHILI_POP_PERSONS


# ── on_restore 收复单位接缝（ADR 0088：content 静态真源已全线「人」）───────────

JIANZHOU_OPENING_POP_PERSONS = 1200000  # 新档开局建州人口（人）
JIANZHOU_RESTORE_POP_PERSONS = 900000   # content on_restore 90（万）→ 迁「人」


def _settle_region_delta(db, state, content, delta):
    """自发信封形态从现役声明入口触发收复。"""
    from tests.section_rejection_helpers import run_declaration as run_settle

    for item in (delta.get("region_delta") or {}).values():
        if isinstance(item, dict):
            item.setdefault("origin_ref", "盘面自发")
    run_settle(db, state, content, delta, narrative="x", decree_text="y")


def test_new_save_restore_jianzhou_keeps_persons_unit(game):
    """判词反例：新档收复建州不得从 1,200,000 人重置为 90——on_restore 预置按「人」落库。"""
    db, state, content = game
    before = db.conn.execute(
        "SELECT population FROM regions WHERE id='jianzhou'"
    ).fetchone()[0]
    assert before == JIANZHOU_OPENING_POP_PERSONS

    _settle_region_delta(db, state, content, {
        "region_delta": {"jianzhou": {"controlled_by": "ming"}},
    })

    after = db.conn.execute(
        "SELECT population FROM regions WHERE id='jianzhou'"
    ).fetchone()[0]
    assert after == JIANZHOU_RESTORE_POP_PERSONS
    assert after != 90  # 漏迁/漏换算任一即 FAIL（×10⁴ mutation 咬点）
