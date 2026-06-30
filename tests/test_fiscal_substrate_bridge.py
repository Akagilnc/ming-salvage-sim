"""#66/#266：regions.fiscal 省级 settle_tick 基座 + DB↔settle_tick 桥。

两件事：
1. 种子——已 seed 的明控省 fiscal JSON 内嵌 settle 基座（开账 st + 月参 p），必须能被
   settle_tick 接受（=有效基座）；陕西作为 #266 史实量级 shadow seed 的基线样例。
2. 桥——`GameDB.settle_province_tick(region_id, actions)` 读 settle.st/p → 跑 settle_tick →
   写回 new_st。**港口锁**：坏输入/守恒破 raise 时 FAIL tick 绝不落库（毒态不钉存档）。

陕西种子 = 低省库 + 正赋15/月 + 辽饷2.5/月 + 逋赋0.45 + 边镇 Due；
空 action 跑一 tick 应进入欠账螺旋。月末 shadow spine 按 controlled_by==ming 且有 settle
动态推进，失地/无基座省自然出列。
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

import ming_sim.content as content_mod
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.fiscal_tick import settle_tick
from ming_sim.flows import army_needed


@pytest.fixture
def fresh_db(tmp_path):
    """全新空库 + 从当前 content 种子（含本 slice 新增的 settle 基座）。
    不能用 conftest 的 game fixture——它拷贝 data/probe.db 旧档，INSERT OR IGNORE 不会带出
    content 新增字段（同「金手指只对新档生效」）。"""
    content = GameContent.load()
    bind_content(content)
    db = GameDB(str(tmp_path / "fresh.db"), content)
    db.seed_static_data()
    try:
        yield db
    finally:
        db.conn.close()


def _read_settle(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}")).get("settle")


def _write_settle(db, region_id, settle):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}"))
    fiscal["settle"] = settle
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), region_id),
    )
    db.conn.commit()


def _province_pay_due(db, region_id):
    rows = db.conn.execute(
        """
        SELECT * FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND pay_source_region = ?
        """,
        (region_id,),
    ).fetchall()
    return sum(army_needed(row) * float(row["province_pay_share"] or 0) for row in rows)


def _province_pay_arrears(db, region_id):
    return float(db.conn.execute(
        """
        SELECT COALESCE(SUM(province_pay_arrears), 0) AS total
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND pay_source_region = ?
        """,
        (region_id,),
    ).fetchone()["total"] or 0)


def _region_with_settle(settle):
    return {
        "id": "test_province",
        "name": "测试省",
        "kind": "布政司",
        "population": 1,
        "public_support": 50,
        "unrest": 0,
        "natural_disaster": "无",
        "human_disaster": "无",
        "registered_land": 1,
        "hidden_land": 1,
        "tax_per_turn": 1,
        "grain_security": 1,
        "gentry_resistance": 0,
        "military_pressure": 0,
        "status": "测试",
        "controlled_by": "ming",
        "fiscal": {"settle": settle},
    }


def test_region_loader_expands_shared_settle_meta_defaults(monkeypatch):
    region = _region_with_settle({
        "_meta_defaults": "ming_province",
        "_meta": {
            "postures": ["江南财赋核心"],
            "notes": {"漕粮": "保留省份专属说明"},
        },
        "st": {},
        "p": {},
    })
    fake_regions = {
        "settle_meta_defaults": {
            "ming_province": {
                "provisional": ["宗禄", "起运定额", "官民田", "隐田"],
                "levies": {"seeded": ["辽饷"], "not_seeded": ["剿饷", "练饷"]},
                "notes": {"起运定额": "#259 后由饷率通道动态接管、此值届时失效"},
            }
        },
        "regions": [region],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    loaded = content_mod.load_region_content()["test_province"].fiscal["settle"]

    assert "_meta_defaults" not in loaded
    assert loaded["_meta"]["provisional"] == ["宗禄", "起运定额", "官民田", "隐田"]
    assert loaded["_meta"]["levies"]["seeded"] == ["辽饷"]
    assert loaded["_meta"]["levies"]["not_seeded"] == ["剿饷", "练饷"]
    assert loaded["_meta"]["postures"] == ["江南财赋核心"]
    assert loaded["_meta"]["notes"]["起运定额"].startswith("#259")
    assert loaded["_meta"]["notes"]["漕粮"] == "保留省份专属说明"


def test_army_pay_source_spine_seed_splits_arrears_and_reconciles_tusi(fresh_db):
    assert fresh_db.is_army_pay_source_cutover_enabled()

    row = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               pay_source_region, province_pay_share, central_pay_share,
               is_tusi, self_funded_pay
        FROM armies WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert row["pay_source_region"] == "shaanxi"
    assert row["province_pay_share"] == pytest.approx(0.65)
    assert row["central_pay_share"] == pytest.approx(0.35)
    assert row["province_pay_arrears"] == pytest.approx(16.25)
    assert row["central_pay_arrears"] == pytest.approx(8.75)
    assert row["arrears"] == pytest.approx(
        row["province_pay_arrears"] + row["central_pay_arrears"]
    )

    pure = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               pay_source_region, province_pay_share, central_pay_share
        FROM armies WHERE id = 'fujian_navy'
        """
    ).fetchone()
    assert pure["pay_source_region"] == "fujian"
    assert pure["province_pay_share"] == pytest.approx(1.0)
    assert pure["central_pay_share"] == pytest.approx(0.0)
    assert pure["province_pay_arrears"] == pytest.approx(pure["arrears"])
    assert pure["central_pay_arrears"] == pytest.approx(0.0)

    tusi = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               province_pay_share, central_pay_share, is_tusi, self_funded_pay
        FROM armies WHERE id = 'southwest_tusi'
        """
    ).fetchone()
    assert tusi["is_tusi"] == 1
    assert tusi["self_funded_pay"] == 1
    assert tusi["province_pay_share"] == pytest.approx(0.0)
    assert tusi["central_pay_share"] == pytest.approx(0.0)
    assert tusi["province_pay_arrears"] == pytest.approx(0.0)
    assert tusi["central_pay_arrears"] == pytest.approx(0.0)
    assert tusi["arrears"] == pytest.approx(0.0)


def test_province_tick_derives_due_and_allocates_province_arrears_by_pay_source(fresh_db):
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 1.0,
            central_pay_share = 0.0, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            station = '福建', manpower = 10000, salary_rate = 5
        WHERE id = 'fujian_navy'
        """
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.65,
            central_pay_share = 0.35, province_pay_arrears = 6.5,
            central_pay_arrears = 3.5, arrears = 10,
            station = '北直隶 / 客防', manpower = 10000, salary_rate = 10
        WHERE id = 'shaanxi_army'
        """
    )
    _write_settle(
        fresh_db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 999,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 8,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )

    result = fresh_db.settle_province_tick("shaanxi")

    mixed = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    pure = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'fujian_navy'"
    ).fetchone()
    mixed_due = army_needed(mixed) * 0.65
    pure_due = army_needed(pure)
    total_due = mixed_due + pure_due
    assert result.breakdown["NewDebt"]["军饷欠"] == pytest.approx(total_due - 8)

    expected_mixed = 6.5 + (total_due - 8) * mixed_due / total_due
    expected_pure = (total_due - 8) * pure_due / total_due
    assert mixed["province_pay_arrears"] == pytest.approx(expected_mixed)
    assert pure["province_pay_arrears"] == pytest.approx(expected_pure)
    assert mixed["central_pay_arrears"] == pytest.approx(3.5)
    assert mixed["arrears"] == pytest.approx(
        mixed["province_pay_arrears"] + mixed["central_pay_arrears"]
    )

    settle = _read_settle(fresh_db, "shaanxi")
    assert settle["p"]["Due"]["军饷"] == pytest.approx(total_due)
    assert settle["st"]["军饷欠"] == pytest.approx(
        mixed["province_pay_arrears"] + pure["province_pay_arrears"]
    )


def test_army_delta_arrears_splits_positive_and_rejects_negative_under_cutover(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="剧情加欠")
    before = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()

    changes = fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"arrears": 10, "reason": "剧情加欠"}},
        commit=False,
    )

    after = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    assert not any(c.get("rejected") for c in changes)
    assert after["province_pay_arrears"] == pytest.approx(before["province_pay_arrears"] + 6.5)
    assert after["central_pay_arrears"] == pytest.approx(before["central_pay_arrears"] + 3.5)
    assert after["arrears"] == pytest.approx(after["province_pay_arrears"] + after["central_pay_arrears"])

    rejected = fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"arrears": -1, "reason": "无现金减欠"}},
        commit=False,
    )
    assert rejected and rejected[0]["rejected"] is True
    again = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    assert again["arrears"] == pytest.approx(after["arrears"])


@pytest.mark.parametrize("bad_defaults", [None, [], "not-a-dict"])
def test_region_loader_rejects_bad_shared_settle_meta_defaults_container(monkeypatch, bad_defaults):
    fake_regions = {
        "settle_meta_defaults": bad_defaults,
        "regions": [_region_with_settle({"st": {}, "p": {}})],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    with pytest.raises(SystemExit, match="content/regions.json.settle_meta_defaults"):
        content_mod.load_region_content()


def test_region_loader_rejects_bad_plain_settle_meta(monkeypatch):
    fake_regions = {
        "regions": [_region_with_settle({"_meta": [], "st": {}, "p": {}})],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    with pytest.raises(SystemExit, match="_meta 必须是 JSON 对象"):
        content_mod.load_region_content()


@pytest.mark.parametrize(
    "settle,defaults,error",
    [
        (
            {"_meta_defaults": "", "_meta": {}, "st": {}, "p": {}},
            {"ming_province": {}},
            "_meta_defaults 必须是非空字符串",
        ),
        (
            {"_meta_defaults": "missing_group", "_meta": {}, "st": {}, "p": {}},
            {"ming_province": {}},
            "_meta_defaults 指向未知默认组：missing_group",
        ),
        (
            {"_meta_defaults": "ming_province", "_meta": [], "st": {}, "p": {}},
            {"ming_province": {}},
            "_meta 必须是 JSON 对象",
        ),
        (
            {"_meta_defaults": "ming_province", "_meta": {}, "st": {}, "p": {}},
            {"ming_province": []},
            "settle_meta_defaults.ming_province 必须是 JSON 对象",
        ),
    ],
)
def test_region_loader_rejects_bad_settle_meta_defaults(monkeypatch, settle, defaults, error):
    fake_regions = {
        "settle_meta_defaults": defaults,
        "regions": [_region_with_settle(settle)],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    with pytest.raises(SystemExit, match=error):
        content_mod.load_region_content()


ZHONGYUAN_JINGSHI_GOLDEN = {
    "beizhili": {
        "省库库银": 0,
        "C_地方截留": 2.352,
        "民欠旧赋": 6.3,
        "军饷欠": 12,
        "官俸欠": 0.3,
        "宗禄欠": 10,
    },
    "shandong": {
        "省库库银": 0,
        "C_地方截留": 2.184,
        "民欠旧赋": 7.35,
        "军饷欠": 2.85,
        "官俸欠": 0,
        "宗禄欠": 0,
    },
    "henan": {
        "省库库银": 0,
        "C_地方截留": 2.16,
        "民欠旧赋": 8,
        "军饷欠": 0,
        "官俸欠": 0,
        "宗禄欠": 31,
    },
}


SOUTH_SOUTHWEST_SEEDS = {
    "sichuan": {
        "zh": "四川", "正赋应征": 8.0, "三饷应征": 1.4, "起运定额": 1.8, "军饷": 5.0, "宗禄": 1.4,
        "first_tick": {"省库库银": 0, "C_地方截留": 0.93248, "民欠旧赋": 3.572, "军饷欠": 4.472,
                       "官俸欠": 1.2, "宗禄欠": 1.4},
    },
    "fujian": {
        "zh": "福建", "正赋应征": 11.0, "三饷应征": 1.7, "起运定额": 2.4, "军饷": 4.0, "宗禄": 0.8,
        "first_tick": {"省库库银": 0, "C_地方截留": 1.46304, "民欠旧赋": 3.556, "军饷欠": 1.256,
                       "官俸欠": 0, "宗禄欠": 0},
    },
    "guangdong": {
        "zh": "广东", "正赋应征": 10.0, "三饷应征": 1.5, "起运定额": 2.2, "军饷": 3.6, "宗禄": 0.9,
        "first_tick": {"省库库银": 0, "C_地方截留": 1.288, "民欠旧赋": 3.45, "军饷欠": 1.75,
                       "官俸欠": 0, "宗禄欠": 0},
    },
    "guangxi": {
        "zh": "广西", "正赋应征": 3.2, "三饷应征": 0.6, "起运定额": 0.8, "军饷": 2.2, "宗禄": 0.3,
        "first_tick": {"省库库银": 0, "C_地方截留": 0.342, "民欠旧赋": 1.9, "军饷欠": 1.8,
                       "官俸欠": 0.5, "宗禄欠": 0.3},
    },
    "yunnan": {
        "zh": "云南", "正赋应征": 3.8, "三饷应征": 0.5, "起运定额": 0.7, "军饷": 1.8, "宗禄": 0.2,
        "first_tick": {"省库库银": 0, "C_地方截留": 0.40248, "民欠旧赋": 2.064, "军饷欠": 1.0,
                       "官俸欠": 0.364, "宗禄欠": 0.2},
    },
    "guizhou": {
        "zh": "贵州", "正赋应征": 2.4, "三饷应征": 0.25, "起运定额": 0.4, "军饷": 1.6, "宗禄": 0.15,
        "first_tick": {"省库库银": 0, "C_地方截留": 0.21465, "民欠旧赋": 1.4575, "军饷欠": 1.6075,
                       "官俸欠": 0.4, "宗禄欠": 0.15},
    },
}


@pytest.mark.parametrize("region_id,expected", SOUTH_SOUTHWEST_SEEDS.items(), ids=list(SOUTH_SOUTHWEST_SEEDS))
def test_south_southwest_seeds_have_valid_historical_settle_substrate(fresh_db, region_id, expected):
    settle = _read_settle(fresh_db, region_id)
    assert isinstance(settle, dict), f"{expected['zh']} fiscal 缺 settle 基座"
    assert isinstance(settle.get("st"), dict) and isinstance(settle.get("p"), dict), \
        f"{expected['zh']} settle 基座须含 st + p"

    p = settle["p"]
    assert p["正赋应征"] == pytest.approx(expected["正赋应征"])
    assert p["三饷应征"] == pytest.approx(expected["三饷应征"])
    assert p["起运定额"] == pytest.approx(expected["起运定额"])
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, region_id))
    assert p["Due"]["宗禄"] == pytest.approx(expected["宗禄"])
    assert p["Due"]["赈济"] == 0
    assert p["三饷应征"] < p["正赋应征"], f"{expected['zh']} 开局只 seed 辽饷，不能塞剿/练饷"
    assert p["起运定额"] >= p["三饷应征"], f"{expected['zh']} 辽饷应可全额起运"
    assert "salt_tax" not in p and "commerce_tax" not in p, "盐税/商税不进 settle substrate"

    meta = settle["_meta"]
    assert "辽饷" in meta["levies"]["seeded"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]
    assert "salt_tax" in meta["excluded_from_settle"]
    assert "commerce_tax" in meta["excluded_from_settle"]
    res = settle_tick(settle["st"], p, [])
    assert res.new_st["省库库银"] is not None


@pytest.mark.parametrize("region_id,expected", SOUTH_SOUTHWEST_SEEDS.items(), ids=list(SOUTH_SOUTHWEST_SEEDS))
def test_south_southwest_settle_tick_golden_and_bridge_persist(fresh_db, region_id, expected):
    settle = _read_settle(fresh_db, region_id)
    pure = settle_tick(settle["st"], settle["p"], [])
    bridged = fresh_db.settle_province_tick(region_id, [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db, region_id)["st"]

    for k, v in expected["first_tick"].items():
        if k in ("省库库银", "军饷欠", "官俸欠", "宗禄欠"):
            continue
        assert pure.new_st[k] == pytest.approx(v, abs=1e-4), f"{region_id} pure {k}"
        assert after[k] == pytest.approx(v, abs=1e-4), f"{region_id} DB {k}"
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, region_id), abs=1e-6)
    for k, v in bridged.new_st.items():
        if k == "军饷欠":
            continue
        assert after[k] == pytest.approx(v, abs=1e-6), f"{region_id} 桥落库 {k} ≠ new_st"


def test_shaanxi_seed_has_valid_settle_substrate(fresh_db):
    settle = _read_settle(fresh_db)
    assert isinstance(settle, dict), "陕西 fiscal 缺 settle 基座"
    assert isinstance(settle.get("st"), dict) and isinstance(settle.get("p"), dict), \
        "settle 基座须含 st + p"
    # 关键不变式：种子 st/p 能被 settle_tick 接受（不 raise）= 有效基座
    res = settle_tick(settle["st"], settle["p"], [])
    assert res.new_st["省库库银"] is not None


def test_shaanxi_seed_is_relabelled_to_historical_shadow_scale(fresh_db):
    settle = _read_settle(fresh_db)
    p = settle["p"]
    assert p["正赋应征"] == pytest.approx(15)
    assert p["三饷应征"] == pytest.approx(2.5)
    assert p["火耗率"] == pytest.approx(0.18)
    assert p["逋赋率"] == pytest.approx(0.45)
    assert p["起运定额"] == pytest.approx(3.5)
    assert p["拨付gross"] == pytest.approx(4)
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shaanxi"))
    assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == {"官俸": 3, "宗禄": 6, "赈济": 0}
    assert settle["st"]["省库库银"] == 0

    meta = settle["_meta"]
    assert "宗禄" in meta["provisional"]
    assert "起运定额" in meta["provisional"]
    assert "官民田" in meta["provisional"]
    assert "隐田" in meta["provisional"]
    assert meta["levies"]["seeded"] == ["辽饷"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]
    assert "#259 后由饷率通道动态接管" in meta["notes"]["起运定额"]


def test_border_remainder_seeds_have_valid_settle_substrate(fresh_db):
    for region_id in ("shanxi", "liaodong", "dongjiang_area"):
        settle = _read_settle(fresh_db, region_id)
        assert isinstance(settle, dict), f"{region_id} fiscal 缺 settle 基座"
        assert isinstance(settle.get("st"), dict) and isinstance(settle.get("p"), dict), \
            f"{region_id} settle 基座须含 st + p"
        res = settle_tick(settle["st"], settle["p"], [])
        assert res.new_st["省库库银"] is not None


def test_shanxi_seed_stacks_frontier_pay_and_jin_vassal_dues(fresh_db):
    settle = _read_settle(fresh_db, "shanxi")
    p = settle["p"]
    assert p["正赋应征"] == pytest.approx(18)
    assert p["三饷应征"] == pytest.approx(3)
    assert p["拨付gross"] == pytest.approx(10)
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shanxi"))
    assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == {"官俸": 4, "宗禄": 10, "赈济": 0}

    meta = settle["_meta"]
    assert "边镇军饷" in meta["postures"]
    assert "晋藩宗禄" in meta["postures"]
    assert "宗禄" in meta["provisional"]
    assert meta["levies"]["seeded"] == ["辽饷"]


def test_liaodong_and_dongjiang_are_pure_military_pay_funnels(fresh_db):
    expected = {
        "liaodong": {"grant": 12, "due": 32, "opening_arrears": 80},
        "dongjiang_area": {"grant": 5, "due": 14, "opening_arrears": 25},
    }
    for region_id, e in expected.items():
        settle = _read_settle(fresh_db, region_id)
        p = settle["p"]
        st = settle["st"]
        assert p["正赋应征"] == 0
        assert p["三饷应征"] == 0
        assert p["起运定额"] == 0
        assert p["拨付gross"] == pytest.approx(e["grant"])
        assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, region_id))
        assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == {"官俸": 0, "宗禄": 0, "赈济": 0}
        assert st["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, region_id))

        res = settle_tick(st, p, [])
        assert res.breakdown["实征"] == 0
        assert res.breakdown["起运到京"] == 0
        assert res.new_st["军饷欠"] == pytest.approx(max(0, st["军饷欠"] + p["Due"]["军饷"] - e["grant"]))


JIANGNAN_CORE_EXPECTED = {
    "nanzhili": {
        "正赋应征": 30, "三饷应征": 8, "起运定额": 24,
        "Due": {"官俸": 4, "宗禄": 2, "赈济": 0},
        "first_tick": {"起运到京": 24},
    },
    "zhejiang": {
        "正赋应征": 23, "三饷应征": 5.5, "起运定额": 18,
        "Due": {"官俸": 3, "宗禄": 1, "赈济": 0},
        "first_tick": {"起运到京": 18, "省库库银": 0.8, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "jiangxi": {
        "正赋应征": 22, "三饷应征": 4.5, "起运定额": 15,
        "Due": {"官俸": 3, "宗禄": 1, "赈济": 0},
        "first_tick": {"起运到京": 15, "省库库银": 0.875, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "huguang": {
        "正赋应征": 34, "三饷应征": 6, "起运定额": 18,
        "Due": {"官俸": 3, "宗禄": 5, "赈济": 0},
        "first_tick": {"起运到京": 18, "省库库银": 5.2, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
}


@pytest.mark.parametrize("region_id,expected", JIANGNAN_CORE_EXPECTED.items())
def test_jiangnan_core_seeds_have_positive_remittance_golden(fresh_db, region_id, expected):
    settle = _read_settle(fresh_db, region_id)
    assert isinstance(settle, dict), f"{region_id} fiscal 缺 settle 基座"
    meta = settle["_meta"]
    assert "江南财赋核心" in meta["postures"]
    assert meta["levies"]["seeded"] == ["辽饷"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]

    p = settle["p"]
    for key in ("正赋应征", "三饷应征", "起运定额"):
        assert p[key] == pytest.approx(expected[key])
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, region_id))
    assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == expected["Due"]
    assert p["起运定额"] > p["三饷应征"], "江南起运定额须覆盖三饷并含正赋大份额"

    res = settle_tick(settle["st"], p, [])
    for key, value in expected["first_tick"].items():
        got = res.breakdown.get(key) if key == "起运到京" else res.new_st[key]
        assert got == pytest.approx(value, abs=1e-3), f"{region_id} {key}"
    assert res.breakdown["起运到京"] > 0, f"{region_id} 应跑出正起运"


def test_huguang_seed_stacks_jiangnan_surplus_with_chu_princely_due(fresh_db):
    huguang = _read_settle(fresh_db, "huguang")
    nanzhili = _read_settle(fresh_db, "nanzhili")

    assert "楚藩重宗禄" in huguang["_meta"]["postures"]
    assert huguang["p"]["Due"]["宗禄"] > nanzhili["p"]["Due"]["宗禄"]

    res = settle_tick(huguang["st"], huguang["p"], [])
    assert res.breakdown["起运到京"] > 0
    assert res.new_st["省库库银"] > 0
    assert res.new_st["宗禄欠"] == pytest.approx(0)


@pytest.mark.parametrize("region_id", ["beizhili", "shandong", "henan"])
def test_zhongyuan_jingshi_seeds_have_valid_historical_settle(region_id, fresh_db):
    settle = _read_settle(fresh_db, region_id)
    assert isinstance(settle, dict), f"{region_id} fiscal 缺 settle 基座"
    assert isinstance(settle.get("st"), dict) and isinstance(settle.get("p"), dict), \
        "settle 基座须含 st + p"

    p = settle["p"]
    assert p["三饷应征"] > 0, "开局只应 seed 辽饷九厘，不应为 0"
    assert settle["_meta"]["levies"]["seeded"] == ["辽饷"]
    assert "剿饷" in settle["_meta"]["levies"]["not_seeded"]
    assert "练饷" in settle["_meta"]["levies"]["not_seeded"]
    res = settle_tick(settle["st"], p, [])
    assert res.new_st["省库库银"] is not None


def test_beizhili_huangzhuang_is_inner_treasury_not_transport_quota(fresh_db):
    settle = _read_settle(fresh_db, "beizhili")
    fiscal = json.loads(str(fresh_db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='beizhili'"
    ).fetchone()["fiscal"]))

    huang_meta = settle["_meta"]["huang_tian"]
    assert fiscal["huang_tian"] == 35
    assert huang_meta["account"] == "内库"
    assert huang_meta["excluded_from"] == ["正赋应征", "起运到京"]
    assert settle["st"]["官民田"] == fiscal["guan_min_tian"] * 10
    assert settle["p"]["起运定额"] == pytest.approx(5)


def test_henan_royal_grants_make_zonglu_due_heavy(fresh_db):
    henan = _read_settle(fresh_db, "henan")
    beizhili = _read_settle(fresh_db, "beizhili")
    shandong = _read_settle(fresh_db, "shandong")

    assert henan["_meta"]["wang_tian"]["houses"] == ["周王", "福王"]
    assert henan["_meta"]["wang_tian"]["basis"] == "wang_tian"
    assert henan["p"]["Due"]["宗禄"] > beizhili["p"]["Due"]["宗禄"]
    assert henan["p"]["Due"]["宗禄"] > shandong["p"]["Due"]["宗禄"]
    assert henan["p"]["Due"]["宗禄"] == pytest.approx(24)


@pytest.mark.parametrize("region_id,expect", ZHONGYUAN_JINGSHI_GOLDEN.items())
def test_zhongyuan_jingshi_settle_province_tick_golden(region_id, expect, fresh_db):
    res = fresh_db.settle_province_tick(region_id, [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db, region_id)["st"]

    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, region_id), abs=1e-6)
    for key, value in res.new_st.items():
        if key == "军饷欠":
            continue
        assert abs(after[key] - value) < 1e-6, f"{region_id} {key}: 落库 {after[key]} ≠ new_st {value}"


def test_settle_province_tick_persists_shaanxi_historical_shadow_golden(fresh_db):
    res = fresh_db.settle_province_tick("shaanxi", [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db)["st"]
    assert after["C_地方截留"] == pytest.approx(1.7325, abs=1e-3)
    assert after["民欠旧赋"] == pytest.approx(7.875, abs=1e-3)
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6)
    # 落库逐键 == settle_tick 的 new_st（桥不篡改）
    for k, v in res.new_st.items():
        if k == "军饷欠":
            continue
        assert abs(after[k] - v) < 1e-6, f"{k}：落库 {after[k]} ≠ new_st {v}"


def test_settle_province_tick_persists_border_remainder_golden(fresh_db):
    expected = {
        "shanxi": {
            "C_地方截留": 2.3205,
            "民欠旧赋": 7.35,
        },
        "liaodong": {
            "C_地方截留": 0,
            "民欠旧赋": 0,
        },
        "dongjiang_area": {
            "C_地方截留": 0,
            "民欠旧赋": 0,
        },
    }
    for region_id, want in expected.items():
        res = fresh_db.settle_province_tick(region_id, [])
        after = _read_settle(fresh_db, region_id)["st"]
        for k, v in want.items():
            assert after[k] == pytest.approx(v, abs=1e-3), \
                f"{region_id} {k}：落库 {after[k]} ≠ #267 {v}"
        assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, region_id), abs=1e-6)
        for k, v in res.new_st.items():
            if k == "军饷欠":
                continue
            assert abs(after[k] - v) < 1e-6, f"{region_id} {k}：落库 {after[k]} ≠ new_st {v}"


def test_settle_province_tick_qingzhang_action(fresh_db):
    row = fresh_db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["st"]["省库库银"] = 50
    fresh_db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    fresh_db.conn.commit()
    # 带 action 的桥：清丈挖隐田 300 → 官民田 3050→3350、隐田 1600→1300（土地守恒）
    fresh_db.settle_province_tick("shaanxi", [{"type": "清丈", "cost": 2, "挖隐田": 300}])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db)["st"]
    assert abs(after["官民田"] - 3350) < 1e-3, f"官民田 {after['官民田']} ≠ 3350"
    assert abs(after["隐田"] - 1300) < 1e-3, f"隐田 {after['隐田']} ≠ 1300"


def test_settle_province_tick_port_lock_no_persist_on_raise(fresh_db):
    # 港口锁：坏 p（删必填火耗率）→ settle_tick raise → DB 绝不变（FAIL tick 不持久化）
    row = fresh_db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    del fiscal["settle"]["p"]["火耗率"]
    fresh_db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    fresh_db.conn.commit()
    st_before = _read_settle(fresh_db)["st"]
    with pytest.raises(ValueError):
        fresh_db.settle_province_tick("shaanxi", [])
    st_after = _read_settle(fresh_db)["st"]
    assert st_after == st_before, "港口锁破：FAIL tick 改了 DB"


def test_settle_province_tick_unknown_region_raises(fresh_db):
    with pytest.raises(ValueError):
        fresh_db.settle_province_tick("atlantis", [])


def test_settle_province_tick_nondict_fiscal_raises(fresh_db):
    # cmr R3（gemini）：fiscal JSON 非 dict（如 "[]"）→ ValueError（可被隔离捕获），
    # 非 fiscal.get 抛 AttributeError 逃逸。
    fresh_db.conn.execute("UPDATE regions SET fiscal='[]' WHERE id='shaanxi'")
    fresh_db.conn.commit()
    with pytest.raises(ValueError):
        fresh_db.settle_province_tick("shaanxi", [])


# ── slice3：接入月末固定财政相位（shadow，不驱动国库；fail-loud 但隔离）──

@pytest.fixture
def fresh_game(fresh_db):
    """fresh_db + load_state，供调 apply_fixed_period_flows（需 GameState）。"""
    return fresh_db, fresh_db.load_state()


def test_apply_fixed_period_flows_advances_shaanxi_substrate(fresh_game):
    # 月末固定财政相位推进省级基座：陕西史实量级 seed 空 action 一 tick → 欠账螺旋累积
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    assert _read_settle(db)["st"]["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"))
    apply_fixed_period_flows(db, state)
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6)
    assert after["省库库银"] == pytest.approx(0, abs=1e-3)
    assert after["C_地方截留"] == pytest.approx(1.7325, abs=1e-3)
    assert after["民欠旧赋"] == pytest.approx(7.875, abs=1e-3)


def test_apply_fixed_period_flows_uses_dynamic_ming_settle_spine(fresh_game):
    # #266: shadow spine is controlled_by==ming AND has fiscal.settle.
    # That lets lost provinces freeze naturally and lets newly-seeded Ming provinces tick.
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    shaanxi_settle = _read_settle(db)

    henan_settle = json.loads(json.dumps(shaanxi_settle, ensure_ascii=False))
    henan_settle["st"]["省库库银"] = 40
    henan_fiscal = {"settle": henan_settle}
    db.conn.execute(
        "UPDATE regions SET controlled_by = 'rebel', fiscal = ? WHERE id = 'henan'",
        (json.dumps(henan_fiscal, ensure_ascii=False),),
    )
    db.conn.execute("UPDATE regions SET controlled_by = 'ming' WHERE id = 'taiwan'")
    db.conn.commit()

    apply_fixed_period_flows(db, state)
    assert _read_settle(db)["st"]["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"))
    assert _read_settle(db, "henan")["st"]["省库库银"] == 40, "非明控制省不应 tick"
    assert _read_settle(db, "taiwan") is None, "明控但无 settle 的省不应被创建/推进"

    db.conn.execute("UPDATE regions SET controlled_by = 'ming' WHERE id = 'henan'")
    db.conn.commit()
    apply_fixed_period_flows(db, state)
    assert _read_settle(db, "henan")["st"]["省库库银"] != 40, "明控且有 settle 的省应 tick"


def test_apply_fixed_period_flows_logs_border_remainder_substrate(fresh_game, monkeypatch):
    from ming_sim import flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod.apply_fixed_period_flows(db, state)

    for region_id in ("shanxi", "liaodong", "dongjiang_area"):
        assert any(f"[fiscal-substrate] {region_id} 推进" in msg for msg in msgs), msgs


def test_apply_fixed_period_flows_logs_zhongyuan_jingshi_shadow_ticks(fresh_game, monkeypatch):
    from ming_sim import flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod.apply_fixed_period_flows(db, state)

    for region_id in ("beizhili", "shandong", "henan"):
        surfaced = [m for m in msgs if f"[fiscal-substrate] {region_id} 推进" in m]
        assert surfaced, f"{region_id} shadow tick 未逐省 tlog：{msgs}"


def test_substrate_absent_does_not_break_flows(game):
    # 旧档无 settle 种子 → shadow 隔离：固定财政照常完成，不抛。
    # 显式保证「无基座」前提（不依赖 probe.db 恰好缺 settle——刷新种子档也不失效，PR#110 coderabbit）。
    from ming_sim.flows import apply_fixed_period_flows
    db, state, _ = game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}")) if row else {}
    fiscal.pop("settle", None)
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    assert _read_settle(db) is None, "前提：陕西无 settle 基座"
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "固定财政应照常落账（基座缺失不该掀翻 pre_settle）"


def test_substrate_corrupt_isolated_from_flows(fresh_game):
    # 坏基座（删必填火耗率）→ settle_tick raise → 隔离：固定财政照常完成 + 基座不推进（港口锁）
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    del fiscal["settle"]["p"]["火耗率"]
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "坏基座不该掀翻固定财政（cmr S4 F4）"
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6), \
        "坏基座不该推进（港口锁：FAIL tick 不落库）"


def test_substrate_corrupt_due_isolated(fresh_game):
    # cmr ship-pre R1（codex+gemini concur P1）：Due 非字典曾抛 AttributeError 逃逸 flows 的
    # (ValueError, FiscalConservationError) 隔离 → 炸 pre_settle 固定财政。settle_tick 验形归
    # ValueError 后→被隔离捕获，固定财政照常完成 + 基座不推进（港口锁）。
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"]["Due"] = None  # 非字典
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "Due 非字典不该掀翻固定财政（AttributeError 逃逸隔离）"
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6), \
        "坏 Due 不该推进（港口锁）"


def test_substrate_corrupt_stock_isolated(fresh_game):
    # cmr ship-pre R2（codex concur P1）：开账 stock 非数值（如 省库库银=[]）曾在 float() 抛
    # TypeError 逃逸 flows 隔离炸 pre_settle。前置验形归 ValueError 后→被隔离捕获，固定财政照常。
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["st"]["省库库银"] = []  # 非数值
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "非数值 stock 不该掀翻固定财政（TypeError 逃逸隔离）"
    after = _read_settle(db)["st"]
    assert after["省库库银"] == [], "坏 stock 不该推进（港口锁：原值不变）"


def test_substrate_malformed_settle_shape_is_logged_not_prefiltered(fresh_game, monkeypatch):
    # cmr fix：动态 spine 只负责找「明控且已有 settle key」的省；st/p 形状坏态必须交给
    # settle_province_tick 验证并经 shadow 隔离日志留痕，不能在 spine 预过滤后静默跳过。
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"] = []  # malformed settle block: 有 settle key，但缺合法 p dict
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 settle 形状不该掀翻固定财政"
    assert _read_settle(db)["p"] == [], "坏 settle 形状不该被 tick 改写"
    surfaced = [m for m in msgs if "[fiscal-substrate] shaanxi" in m and "ValueError" in m]
    assert surfaced, msgs


def test_substrate_malformed_fiscal_container_is_logged_not_prefiltered(fresh_game, monkeypatch):
    # cmr step6 r2：动态 spine 不得在 selector 里静默跳过 fiscal='[]' 这类坏容器；
    # 应交给 settle_province_tick 归 ValueError，再由 shadow 隔离 tlog 留痕。
    # 这里刻意直打 shadow seam：完整 fixed-flow 的旧财政收入路径会先解析 fiscal。
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    db.conn.execute("UPDATE regions SET fiscal='[]' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod._advance_province_fiscal_substrate(db, state)

    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "[]"
    surfaced = [m for m in msgs if "[fiscal-substrate] shaanxi" in m and "fiscal 非字典" in m]
    assert surfaced, msgs


def test_apply_fixed_period_flows_malformed_fiscal_container_isolated(fresh_game, monkeypatch):
    # Public entry contract: fixed fiscal must not crash before shadow substrate isolation can log.
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _, _, before_details = flows_mod.calc_province_fiscal(state, db)
    expected_tax = sum(
        int(d["province_total"]) for d in before_details if d["region_id"] != "shaanxi"
    )
    db.conn.execute("UPDATE regions SET fiscal='[]' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 fiscal 容器不该掀翻固定财政"
    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "[]"
    tax_flow = next(f for f in flow_rows if f.get("category") == "田赋辽饷盐商")
    assert tax_flow["amount"] == expected_tax, "坏 fiscal 省当月固定税收应出列，不能按默认 fiscal 造钱"
    assert any("[province-fiscal] shaanxi fiscal 非字典" in m and "固定税收出列" in m for m in msgs), msgs
    assert any("[fiscal-substrate] shaanxi" in m and "fiscal 非字典" in m for m in msgs), msgs


def test_substrate_malformed_fiscal_json_is_logged_not_prefiltered(fresh_game, monkeypatch):
    # 动态 spine selector 解析 fiscal JSON 失败时仍应把该省交给 bridge，让 shadow 隔离
    # 统一 tlog 留痕；不能静默跳过坏 JSON。
    # 这里刻意直打 shadow seam：完整 fixed-flow 的旧财政收入路径会先解析 fiscal。
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    db.conn.execute("UPDATE regions SET fiscal='{bad' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod._advance_province_fiscal_substrate(db, state)

    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "{bad"
    surfaced = [m for m in msgs if "[fiscal-substrate] shaanxi" in m and "JSONDecodeError" in m]
    assert surfaced, msgs


def test_apply_fixed_period_flows_malformed_fiscal_json_isolated(fresh_game, monkeypatch):
    # Public entry contract: syntax-bad fiscal JSON must not abort before shadow isolation.
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _, _, before_details = flows_mod.calc_province_fiscal(state, db)
    expected_tax = sum(
        int(d["province_total"]) for d in before_details if d["region_id"] != "shaanxi"
    )
    db.conn.execute("UPDATE regions SET fiscal='{bad' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 fiscal JSON 不该掀翻固定财政"
    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "{bad"
    tax_flow = next(f for f in flow_rows if f.get("category") == "田赋辽饷盐商")
    assert tax_flow["amount"] == expected_tax, "坏 fiscal 省当月固定税收应出列，不能按默认 fiscal 造钱"
    assert any(
        "[province-fiscal] shaanxi fiscal 解析失败" in m
        and "固定税收出列" in m
        and "JSONDecodeError" in m
        for m in msgs
    ), msgs
    assert any("[fiscal-substrate] shaanxi" in m and "JSONDecodeError" in m for m in msgs), msgs


@pytest.mark.parametrize("field,bad_value", [
    ("corruption", []),
    ("liao_xiang", []),
])
def test_apply_fixed_period_flows_malformed_fiscal_scalar_isolated(fresh_game, monkeypatch, field, bad_value):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _, _, before_details = flows_mod.calc_province_fiscal(state, db)
    expected_tax = sum(
        int(d["province_total"]) for d in before_details if d["region_id"] != "shaanxi"
    )
    fiscal = json.loads(str(db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='shaanxi'"
    ).fetchone()["fiscal"] or "{}"))
    fiscal[field] = bad_value
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 fiscal 标量不该掀翻固定财政"
    tax_flow = next(f for f in flow_rows if f.get("category") == "田赋辽饷盐商")
    assert tax_flow["amount"] == expected_tax, "坏 fiscal 标量省当月固定税收应出列"
    assert any(
        f"[province-fiscal] shaanxi fiscal.{field} 非数字" in m
        and "固定税收出列" in m
        for m in msgs
    ), msgs


def test_fixed_flow_loader_accepts_already_decoded_fiscal_dict(monkeypatch):
    import ming_sim.flows as flows_mod

    fiscal = {"settle": {"st": {}, "p": {}}, "tax": 1}
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    assert flows_mod._load_region_fiscal_for_fixed_flow("shaanxi", fiscal) == fiscal
    assert msgs == []


@pytest.mark.parametrize("bad_scalar", [float("nan"), float("inf"), 10 ** 309])
def test_fixed_flow_loader_rejects_non_finite_numeric_values(monkeypatch, bad_scalar):
    import ming_sim.flows as flows_mod

    fiscal = {"settle": {"st": {}, "p": {}}, "liao_xiang": bad_scalar}
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    assert flows_mod._load_region_fiscal_for_fixed_flow("shaanxi", fiscal) is None
    assert any(
        "[province-fiscal] shaanxi fiscal.liao_xiang 非数字" in m
        and "固定税收出列" in m
        for m in msgs
    ), msgs


@pytest.mark.parametrize("payload", [[], 0, False])
def test_fixed_flow_loader_rejects_decoded_non_dict_payloads(monkeypatch, payload):
    import ming_sim.flows as flows_mod

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    assert flows_mod._load_region_fiscal_for_fixed_flow("shaanxi", payload) is None
    assert any(
        "[province-fiscal] shaanxi fiscal 非字典" in m
        and "固定税收出列" in m
        for m in msgs
    ), msgs


def test_apply_fixed_period_flows_commits_shadow_substrate_when_standalone(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    flows_mod.apply_fixed_period_flows(db, state)
    in_memory = _read_settle(db, "shaanxi")["st"]

    other = sqlite3.connect(db.path)
    try:
        row = other.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    finally:
        other.close()
    on_disk = json.loads(str(row[0] or "{}"))["settle"]["st"]

    assert on_disk["军饷欠"] == pytest.approx(in_memory["军饷欠"], abs=1e-3)
    assert on_disk["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6)


def test_apply_fixed_period_flows_advances_and_logs_jiangnan_core(fresh_game, monkeypatch):
    from ming_sim import flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod.apply_fixed_period_flows(db, state)

    for region_id, expected in JIANGNAN_CORE_EXPECTED.items():
        settle = _read_settle(db, region_id)
        if "省库库银" in expected["first_tick"]:
            assert settle["st"]["省库库银"] == pytest.approx(
                expected["first_tick"]["省库库银"], abs=1e-3
            )
        assert any(
            f"[fiscal-substrate] {region_id} 推进" in msg and "起运" in msg
            for msg in msgs
        ), f"{region_id} 缺 shadow tlog：{msgs}"


def test_apply_fixed_period_flows_logs_south_southwest_shadow_ticks(fresh_game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod.apply_fixed_period_flows(db, state)

    for region_id in SOUTH_SOUTHWEST_SEEDS:
        assert any(f"[fiscal-substrate] {region_id} 推进" in m for m in msgs), \
            f"{region_id} shadow tick 未逐省 tlog: {msgs}"


def test_all_ming_settle_substrates_advance_with_observable_shadow_tlog(fresh_game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    fixed_flows = flows_mod.apply_fixed_period_flows(db, state)

    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
    ).fetchall()
    settle_region_ids = [
        str(row["id"])
        for row in rows
        if "settle" in json.loads(str(row["fiscal"] or "{}"))
    ]
    shadow_msgs = [m for m in msgs if m.startswith("[fiscal-substrate] ") and " 推进：" in m]

    assert len(settle_region_ids) == 17
    assert len(shadow_msgs) == 17
    assert not any(
        flow.get("account") == "国库"
        and flow.get("dir") == "income"
        and ("起运" in str(flow) or "fiscal-substrate" in str(flow))
        for flow in fixed_flows
    ), "shadow 基座只算/打印起运，不得作为额外国库收入落账"
    for region_id in settle_region_ids:
        surfaced = [m for m in shadow_msgs if f"[fiscal-substrate] {region_id} 推进：" in m]
        assert surfaced, f"{region_id} 缺 shadow tlog: {msgs}"
        msg = surfaced[0]
        for field in ("实征", "起运", "火耗", "末态欠账"):
            assert field in msg, f"{region_id} tlog 缺 {field}: {msg}"

    for region_id in ("zhejiang", "jiangxi", "huguang"):
        settle = _read_settle(db, region_id)
        assert settle["st"]["省库库银"] > 0, f"{region_id} 江南核心应有省库盈余"
        assert f"[fiscal-substrate] {region_id} 推进" in "\n".join(shadow_msgs)
    for region_id in ("shaanxi", "shanxi", "liaodong", "dongjiang_area"):
        settle = _read_settle(db, region_id)
        assert settle["st"]["军饷欠"] == pytest.approx(_province_pay_arrears(db, region_id), abs=1e-6)
    assert _read_settle(db, "henan")["st"]["宗禄欠"] > 0, "周/福藩重省应有宗禄欠压"
    assert _read_settle(db, "huguang")["p"]["Due"]["宗禄"] > _read_settle(db, "nanzhili")["p"]["Due"]["宗禄"], \
        "楚藩重省宗禄 Due 应重于江南基准"


def test_shadow_spine_uses_batch_bridge_without_per_region_reload(fresh_game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    calls = {"batch": 0}
    monkeypatch.setattr(flows_mod, "tlog", msgs.append)

    def fake_batch_bridge():
        calls["batch"] += 1
        return [
            SimpleNamespace(
                region_id="shaanxi",
                error=None,
                result=SimpleNamespace(
                    breakdown={"实征": 1.2, "起运到京": 0.3, "火耗实收": 0.4},
                    new_st={"军饷欠": 2, "官俸欠": 0, "宗禄欠": 0, "民欠旧赋": 1},
                ),
            )
        ]

    def fail_single_region_reload(*args, **kwargs):
        raise AssertionError("shadow spine must use the batch fiscal payload bridge")

    monkeypatch.setattr(db, "settle_ming_province_substrate_ticks", fake_batch_bridge)
    monkeypatch.setattr(db, "settle_province_tick", fail_single_region_reload)

    flows_mod._advance_province_fiscal_substrate(db, state)

    assert calls["batch"] == 1
    assert any("[fiscal-substrate] shaanxi 推进：" in msg for msg in msgs)


def test_seeded_substrates_keep_multi_tick_historical_trajectories(fresh_db):
    """#70 capstone：用真实 content seed 跑多 tick 轨迹，而非只测首 tick golden。"""
    jiangnan = ("nanzhili", "zhejiang", "jiangxi", "huguang")
    border = ("shaanxi", "shanxi", "liaodong", "dongjiang_area")

    for region_id in jiangnan:
        settle = _read_settle(fresh_db, region_id)
        st = settle["st"]
        remittances = []
        for _ in range(3):
            res = settle_tick(st, settle["p"], [])
            remittances.append(res.breakdown["起运到京"])
            st = res.new_st
        assert all(value > 0 for value in remittances), \
            f"{region_id} 江南财赋核心应多 tick 保持正起运: {remittances}"

    for region_id in border:
        settle = _read_settle(fresh_db, region_id)
        st = settle["st"]
        arrears = []
        for _ in range(3):
            res = settle_tick(st, settle["p"], [])
            arrears.append(res.new_st["军饷欠"])
            st = res.new_st
        assert all(value >= 0 for value in arrears), \
            f"{region_id} 边镇军饷容器不得为负: {arrears}"


def test_all_settle_substrate_provisional_meta_covers_virtual_fields(fresh_db):
    rows = fresh_db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
    ).fetchall()

    checked = 0
    for row in rows:
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle")
        if not settle:
            continue
        checked += 1
        region_id = str(row["id"])
        st = settle["st"]
        p = settle["p"]
        provisional = set(settle["_meta"].get("provisional", []))
        if p["正赋应征"] == 0 and p["起运定额"] == 0:
            required = {"军饷", "拨付gross", "军饷欠", "起运定额"}
        else:
            required = {"宗禄", "起运定额", "官民田", "隐田"}
        assert required <= provisional, f"{region_id} provisional 缺 {sorted(required - provisional)}"
        if "官民田" in required:
            assert "官民田" in st and "隐田" in st, f"{region_id} 田亩虚字段缺 seed"

    assert checked == 17
