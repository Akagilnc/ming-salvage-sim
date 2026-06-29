"""#66/#266：regions.fiscal 省级 settle_tick 基座 + DB↔settle_tick 桥。

两件事：
1. 种子——陕西 fiscal JSON 内嵌 settle 基座（开账 st + 月参 p），#266 已重标为史实量级
   shadow seed。种子必须能被 settle_tick 接受（=有效基座）。
2. 桥——`GameDB.settle_province_tick(region_id, actions)` 读 settle.st/p → 跑 settle_tick →
   写回 new_st。**港口锁**：坏输入/守恒破 raise 时 FAIL tick 绝不落库（毒态不钉存档）。

陕西种子 = 低省库 + 正赋15/月 + 辽饷2.5/月 + 逋赋0.45 + 边镇 Due；
空 action 跑一 tick 应进入欠账螺旋。月末 shadow spine 按 controlled_by==ming 且有 settle
动态推进，失地/无基座省自然出列。
"""
import json

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.fiscal_tick import settle_tick


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
    assert p["Due"] == {"军饷": 18, "官俸": 3, "宗禄": 6, "赈济": 0}
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
    assert p["Due"] == {"军饷": 24, "官俸": 4, "宗禄": 10, "赈济": 0}

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
        assert p["Due"] == {"军饷": e["due"], "官俸": 0, "宗禄": 0, "赈济": 0}
        assert st["军饷欠"] == pytest.approx(e["opening_arrears"])

        res = settle_tick(st, p, [])
        assert res.breakdown["实征"] == 0
        assert res.breakdown["起运到京"] == 0
        assert res.new_st["军饷欠"] == pytest.approx(e["opening_arrears"] + e["due"] - e["grant"])


JIANGNAN_CORE_EXPECTED = {
    "nanzhili": {
        "正赋应征": 30, "三饷应征": 8, "起运定额": 24,
        "Due": {"军饷": 0, "官俸": 4, "宗禄": 2, "赈济": 0},
        "first_tick": {"起运到京": 24, "省库库银": 1.16, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "zhejiang": {
        "正赋应征": 23, "三饷应征": 5.5, "起运定额": 18,
        "Due": {"军饷": 0, "官俸": 3, "宗禄": 1, "赈济": 0},
        "first_tick": {"起运到京": 18, "省库库银": 0.8, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "jiangxi": {
        "正赋应征": 22, "三饷应征": 4.5, "起运定额": 15,
        "Due": {"军饷": 0, "官俸": 3, "宗禄": 1, "赈济": 0},
        "first_tick": {"起运到京": 15, "省库库银": 0.875, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "huguang": {
        "正赋应征": 34, "三饷应征": 6, "起运定额": 18,
        "Due": {"军饷": 0, "官俸": 3, "宗禄": 5, "赈济": 0},
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
    assert p["Due"] == expected["Due"]
    assert p["Due"]["军饷"] == 0, "江南腹地非边镇，军饷 Due 应为 0"
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

    for key, value in expect.items():
        assert after[key] == pytest.approx(value, abs=1e-3), \
            f"{region_id} {key}: 落库 {after[key]} ≠ golden {value}"
    for key, value in res.new_st.items():
        assert abs(after[key] - value) < 1e-6, f"{region_id} {key}: 落库 {after[key]} ≠ new_st {value}"


def test_settle_province_tick_persists_g1_baseline(fresh_db):
    res = fresh_db.settle_province_tick("shaanxi", [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db)["st"]
    # 钉 #266 陕西史实量级 shadow 末态：低省库 + 高逋赋 + 边镇 Due 形成欠账螺旋。
    for k, v in {
        "省库库银": 0,
        "C_地方截留": 1.7325,
        "民欠旧赋": 7.875,
        "军饷欠": 27.875,
        "官俸欠": 3,
        "宗禄欠": 6,
    }.items():
        assert after[k] == pytest.approx(v, abs=1e-3), f"{k}：落库 {after[k]} ≠ #266 {v}"
    # 落库逐键 == settle_tick 的 new_st（桥不篡改）
    for k, v in res.new_st.items():
        assert abs(after[k] - v) < 1e-6, f"{k}：落库 {after[k]} ≠ new_st {v}"


def test_settle_province_tick_persists_border_remainder_golden(fresh_db):
    expected = {
        "shanxi": {
            "省库库银": 0,
            "C_地方截留": 2.3205,
            "民欠旧赋": 7.35,
            "军饷欠": 29.35,
            "官俸欠": 4,
            "宗禄欠": 10,
        },
        "liaodong": {
            "省库库银": 0,
            "C_地方截留": 0,
            "民欠旧赋": 0,
            "军饷欠": 100,
        },
        "dongjiang_area": {
            "省库库银": 0,
            "C_地方截留": 0,
            "民欠旧赋": 0,
            "军饷欠": 34,
        },
    }
    for region_id, want in expected.items():
        res = fresh_db.settle_province_tick(region_id, [])
        after = _read_settle(fresh_db, region_id)["st"]
        for k, v in want.items():
            assert after[k] == pytest.approx(v, abs=1e-3), \
                f"{region_id} {k}：落库 {after[k]} ≠ #267 {v}"
        for k, v in res.new_st.items():
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
    assert _read_settle(db)["st"]["军饷欠"] == 20  # 种子
    apply_fixed_period_flows(db, state)
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(27.875, abs=1e-3), \
        f"军饷欠 {after['军饷欠']} ≠ 27.875（基座未在固定财政相位推进？）"
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
    db.conn.commit()

    apply_fixed_period_flows(db, state)
    assert _read_settle(db)["st"]["军饷欠"] != 20, "陕西仍应由动态 spine 推进"
    assert _read_settle(db, "henan")["st"]["省库库银"] == 40, "非明控制省不应 tick"
    assert _read_settle(db, "sichuan") is None, "明控但无 settle 的省不应被创建/推进"

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
    assert abs(after["军饷欠"] - 20) < 1e-3, "坏基座不该推进（港口锁：FAIL tick 不落库）"


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
    assert abs(after["军饷欠"] - 20) < 1e-3, "坏 Due 不该推进（港口锁）"


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


def test_apply_fixed_period_flows_advances_and_logs_jiangnan_core(fresh_game, monkeypatch):
    from ming_sim import flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod.apply_fixed_period_flows(db, state)

    for region_id, expected in JIANGNAN_CORE_EXPECTED.items():
        settle = _read_settle(db, region_id)
        assert settle["st"]["省库库银"] == pytest.approx(
            expected["first_tick"]["省库库银"], abs=1e-3
        )
        assert any(
            f"[fiscal-substrate] {region_id} 推进" in msg and "起运" in msg
            for msg in msgs
        ), f"{region_id} 缺 shadow tlog：{msgs}"
