"""#648（[#477 S1]）：人口单位「人」迁移＋流民第八阶级 seed。

canonical＝ADR 0087/0088 + 票面冻结修正案 r1/r2：
- F1：extractor class 写面只收 satisfaction/leverage，population 更新面删除；
- F2：机面 TSV 裸人 / 玩家面 LLM 输入投影「约N万口」（正向 prompt，零删改）；
- F3：流民 16 行冻结 seed 表（陕西15万/河南5万/其余13省0；全国=省级求和派生；
      satisfaction 基线30 陕西20 河南25 / leverage 5 / agenda 冻结句）；
- F4：旧档双口径——新档 DB 持久标「人」，无标旧档判「万人」，不读 content 元信息；
- AC4+AC8 合并：五项 mutation 验收矩阵（classes seed / regions seed / events effect /
  new-save prompt / old-save prompt），逐项钉新旧档期望口径，×10⁴ 漏乘或重乘必咬。
"""

from __future__ import annotations

import pytest

from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS, POPULATION_UNIT_WAN
from ming_sim.issues import (
    apply_score_extraction,
    auto_trigger_seed_issues,
    bind_content as issues_bind_content,
)
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload

# ── F3/r2 冻结 seed oracle（独立真源=票面冻结表，非实现推导）──────────────────
AGENDA_FROZEN = "就食求赈，流徙谋生"
DISPLACED_PROVINCES = [
    "beizhili", "nanzhili", "shandong", "shanxi", "henan", "shaanxi", "zhejiang",
    "jiangxi", "huguang", "sichuan", "fujian", "guangdong", "guangxi", "yunnan", "guizhou",
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


def _make_legacy_db(content, path: str) -> GameDB:
    """构造无标旧档：fresh seed 后把人口回缩到万人口径并剥掉单位标。

    与真实旧档同构：DB 行为 pre-0088 content seed 出的万人值、save_meta 无
    population_unit 标（旧档不迁移、无流民行）。"""
    db = GameDB(path, content)
    db.seed_static_data()
    db.conn.execute("UPDATE classes SET population = population / 10000")
    db.conn.execute("UPDATE regions SET population = population / 10000")
    # 旧档不迁移：流民第八阶级行（0087 新档生效）也一并剥除，与真实 pre-0087 旧档同构
    db.conn.execute("DELETE FROM classes WHERE name='流民'")
    db.conn.execute("DELETE FROM save_meta WHERE key='population_unit'")
    db.conn.commit()
    return db


@pytest.fixture
def legacy_game(content, tmp_path):
    """返回 (db, state)：无标万人口径旧档（含 load_state 同核）。"""
    path = str(tmp_path / "legacy.db")
    db = _make_legacy_db(content, path)
    state = db.load_state()
    issues_bind_content(content)
    yield db, state


# ── 新档 classes seed（F3/r2 冻结表 + ×10⁴）─────────────────────────────────

def test_new_save_displaced_class_seed_frozen_table(game):
    """F3/r2：流民第八阶级 15 省＋全国切片，冻结 seed 表逐字段钉死。"""
    db, _, _ = game
    rows = _displaced_rows(db)
    assert len(rows) == 16  # 15 省 + 全国

    by_region = {r["region_id"]: r for r in rows}
    assert set(by_region) == set(DISPLACED_PROVINCES) | {""}

    # 灾区覆写：陕西 15万/20、河南 5万/25（单位：人）
    assert by_region["shaanxi"]["population"] == SHAANXI_POP
    assert by_region["shaanxi"]["satisfaction"] == SHAANXI_SAT
    assert by_region["henan"]["population"] == HENAN_POP
    assert by_region["henan"]["satisfaction"] == HENAN_SAT

    # 其余 13 省 population=0，satisfaction 取统一基线
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


# ── 旧档双口径（F4）───────────────────────────────────────────────────────

def test_legacy_save_defaults_to_wan_unit_and_keeps_snapshot(legacy_game):
    """无标旧档一律判「万人」，seed 不重跑、快照读数不变（不混刻度、无流民行）。"""
    db, _ = legacy_game
    assert db.population_unit == POPULATION_UNIT_WAN
    row = db.conn.execute(
        "SELECT population FROM regions WHERE id='beizhili'"
    ).fetchone()
    assert row["population"] == 720  # 万人口径原样
    farmer = db.conn.execute(
        "SELECT population FROM classes WHERE name='农民' AND region_id=''"
    ).fetchone()
    assert farmer["population"] == 11000
    # 旧档不迁移：无流民行（0087 新档生效）
    assert len(_displaced_rows(db)) == 0


# ── 五项 mutation 验收矩阵（AC4+AC8 合并，逐项钉新旧档期望口径）──────────────

def test_population_unit_mutation_matrix(game, legacy_game):
    """①classes seed ②regions seed ③events effect：×10⁴ 漏乘或重乘任一即 FAIL。

    期望值来自独立 oracle（content 字面/冻结表/事件 -40万），非实现推导；
    ④⑤ prompt 契约见 test_prompt_contract_* 两案。"""
    new_db = game[0]
    old_db, _old_state = legacy_game
    content = game[2]

    def one(db, sql):
        return db.conn.execute(sql).fetchone()[0]

    # ① classes seed：农民全国 11000万 → 110000000 人；旧档 11000 万人不动
    assert one(new_db, "SELECT population FROM classes WHERE name='农民' AND region_id=''") \
        == FARMER_NATIONAL_POP_PERSONS
    assert one(old_db, "SELECT population FROM classes WHERE name='农民' AND region_id=''") == 11000
    # ② regions seed：北直隶 720万 → 7200000 人；旧档 720 万人不动
    assert one(new_db, "SELECT population FROM regions WHERE id='beizhili'") == BEIZHILI_POP_PERSONS
    assert one(old_db, "SELECT population FROM regions WHERE id='beizhili'") == 720

    # ③ events effect 双向实测：同一 content 真源（华北大疫山西 -400000 人），按档口径落库
    issues_bind_content(content)
    for db, expect_delta in ((new_db, -400000), (old_db, -40)):
        before = one(db, "SELECT population FROM regions WHERE id='shanxi'")
        state = db.load_state()
        state.year, state.period = 1633, 7
        triggered = auto_trigger_seed_issues(state, db)
        assert any(item["id"] == "huabei_plague" for item in triggered)
        after = one(db, "SELECT population FROM regions WHERE id='shanxi'")
        assert after == before + expect_delta, (
            f"mutation[events_effect] 口径错：期望 {expect_delta}，实得 {after - before}"
        )


# ── prompt 契约（④ new-save / ⑤ old-save）＋ F2 机面/玩家面拆分 ────────────

def test_prompt_contract_new_save_persons(game):
    """④ 新档写端契约：population_unit=人（与 manpower 同刻度）；玩家面投影万口、机面裸人。"""
    db, state, content = game
    issues_bind_content(content)

    ctx = build_extractor_shared_context(db, state, "邸报", "诏文")
    assert ctx["population_unit"] == POPULATION_UNIT_PERSONS

    payload = build_simulator_payload(state, db, "诏文", "")
    rows = payload["regions"]["rows"]
    cols = payload["regions"]["cols"]
    pop_col = cols.index("population")
    name_col = cols.index("name")
    beizhili = next(r for r in rows if r[name_col].startswith("北直隶"))
    # 玩家可感 LLM 输入：约N万口定性（P4 正向投影），无裸大数直出
    assert beizhili[pop_col] == "约720万口"

    # 机面（extractor issues 档阈值裸数视图）：裸人数
    issues_ctx = build_extractor_shared_context(db, state, "邸报", "诏文", module="issues")
    issue_region_rows = issues_ctx["regions"]["rows"]
    issue_cols = issues_ctx["regions"]["cols"]
    bz = next(r for r in issue_region_rows if r[issue_cols.index("id")] == "beizhili")
    assert bz[issue_cols.index("population")] == BEIZHILI_POP_PERSONS


def test_prompt_contract_legacy_save_wan(legacy_game):
    """⑤ 旧档写端契约：缺 DB 标 → population_unit=万人，展示沿 legacy 原样不加换算。"""
    db, state = legacy_game

    ctx = build_extractor_shared_context(db, state, "邸报", "诏文")
    assert ctx["population_unit"] == POPULATION_UNIT_WAN

    payload = build_simulator_payload(state, db, "诏文", "")
    rows = payload["regions"]["rows"]
    cols = payload["regions"]["cols"]
    pop_col = cols.index("population")
    name_col = cols.index("name")
    beizhili = next(r for r in rows if r[name_col].startswith("北直隶"))
    assert beizhili[pop_col] == 720  # 万人口径原样


# ── F1：class 写面只收 satisfaction/leverage（流民行含内）───────────────────

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

    # population 字段即使混进合法 key 的 item 也被忽略（无更新面，非静默改账）
    apply_score_extraction(db, state, {
        "class_delta": {"流民@shaanxi": {"satisfaction": 1, "population": 123456}},
    }, content, None)
    row2 = db.conn.execute(
        "SELECT population, satisfaction FROM classes "
        "WHERE name='流民' AND region_id='shaanxi'"
    ).fetchone()
    assert row2["satisfaction"] == SHAANXI_SAT - 5 + 1
    assert row2["population"] == SHAANXI_POP


# ── web 玩家面展示投影（AC1：无裸大数直出给皇帝）─────────────────────────────

def _web_runtime(db, state, content):
    """轻壳 WebGame：仅挂 regions_display_payload 所需缝（同 test_army_card_status_1501 风格）。"""
    from types import SimpleNamespace

    import web_app

    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, state=state, content=content)
    return runtime


def test_web_region_display_population_wan_by_save_unit(game, legacy_game, tmp_path):
    """web 地区人口展示值：新档（人）÷10⁴ 出万口；旧档（万人）原值。机面字段原样保留。"""
    from types import SimpleNamespace

    new_db, new_state, content = game
    runtime = _web_runtime(new_db, new_state, content)
    rows = {r["id"]: r for r in runtime.regions_display_payload()}
    assert rows["beizhili"]["population_wan"] == 720
    assert rows["beizhili"]["population"] == BEIZHILI_POP_PERSONS  # 机面不動

    old_db, _old_state = legacy_game
    old_runtime = _web_runtime(old_db, _old_state, content)
    old_rows = {r["id"]: r for r in old_runtime.regions_display_payload()}
    assert old_rows["beizhili"]["population_wan"] == 720
    assert old_rows["beizhili"]["population"] == 720


def test_web_map_nodes_share_save_aware_population_projection(game, legacy_game):
    """#648 类2：地图节点 region 与地区抽屉共享同一存档感知人口投影。

    map_nodes 不得直取 db.region_payload()——否则 node.region 缺 population_wan，
    前端渲染 undefined万；机面 population 字段仍原样保留。"""
    new_db, new_state, content = game
    nodes = {n["id"]: n for n in _web_runtime(new_db, new_state, content).map_nodes()}
    bz = nodes["beizhili"]["region"]
    assert bz["population_wan"] == 720
    assert bz["population"] == BEIZHILI_POP_PERSONS  # 机面不動

    old_db, old_state = legacy_game
    old_nodes = {
        n["id"]: n for n in _web_runtime(old_db, old_state, game[2]).map_nodes()
    }
    old_bz = old_nodes["beizhili"]["region"]
    assert old_bz["population_wan"] == 720
    assert old_bz["population"] == 720


# ── on_restore 收复单位接缝（ADR 0088：content 静态真源已全线「人」）───────────

JIANZHOU_OPENING_POP_PERSONS = 1200000  # 新档开局建州人口（人）
JIANZHOU_RESTORE_POP_PERSONS = 900000   # content on_restore 90（万）→ 迁「人」
JIANZHOU_RESTORE_POP_WAN = 90           # 无标旧档接缝无损 ÷10⁴ 回万人


def _settle_region_delta(db, state, content, delta):
    """同 test_section4_rejections 帮手：自发信封形态走真结算路径触发收复。"""
    from driver import run_settle

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


def test_legacy_save_restore_jianzhou_converts_to_wan(game, legacy_game):
    """无标旧档收复建州：content→档唯一接缝无损换回万人口径，不混刻度。"""
    old_db, old_state = legacy_game
    _settle_region_delta(old_db, old_state, game[2], {
        "region_delta": {"jianzhou": {"controlled_by": "ming"}},
    })
    after = old_db.conn.execute(
        "SELECT population FROM regions WHERE id='jianzhou'"
    ).fetchone()[0]
    assert after == JIANZHOU_RESTORE_POP_WAN
