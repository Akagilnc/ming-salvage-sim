"""#66 slice2：regions.fiscal 省级 settle_tick 基座 + DB↔settle_tick 桥。

两件事：
1. 种子——陕西（单省脊柱）fiscal JSON 内嵌 settle 基座（开账 st + 月参 p），占位数 = v23
   spike G1 base（史实重标在 slice5）。种子必须能被 settle_tick 接受（=有效基座）。
2. 桥——`GameDB.settle_province_tick(region_id, actions)` 读 settle.st/p → 跑 settle_tick →
   写回 new_st。**港口锁**：坏输入/守恒破 raise 时 FAIL tick 绝不落库（毒态不钉存档）。

陕西种子 = G1 基线（省库50/军饷欠20/正赋60/三饷10/火耗.2/逋赋.3/起运40/Due军饷45…），
故空 action 跑一 tick 应得 G1 末态 {省库0, C_地方截留9.8, 民欠21, 军饷欠18}——把桥的
落库输出直接钉到已验证 golden。
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


def test_shaanxi_seed_has_valid_settle_substrate(fresh_db):
    settle = _read_settle(fresh_db)
    assert isinstance(settle, dict), "陕西 fiscal 缺 settle 基座"
    assert isinstance(settle.get("st"), dict) and isinstance(settle.get("p"), dict), \
        "settle 基座须含 st + p"
    # 关键不变式：种子 st/p 能被 settle_tick 接受（不 raise）= 有效基座
    res = settle_tick(settle["st"], settle["p"], [])
    assert res.new_st["省库库银"] is not None


def test_settle_province_tick_persists_g1_baseline(fresh_db):
    res = fresh_db.settle_province_tick("shaanxi", [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db)["st"]
    # 钉 G1 末态（种子=G1 基线）：桥的落库输出 == 已验证 golden
    for k, v in {"省库库银": 0, "C_地方截留": 9.8, "民欠旧赋": 21, "军饷欠": 18}.items():
        assert abs(after[k] - v) < 1e-3, f"{k}：落库 {after[k]} ≠ G1 {v}"
    # 落库逐键 == settle_tick 的 new_st（桥不篡改）
    for k, v in res.new_st.items():
        assert abs(after[k] - v) < 1e-6, f"{k}：落库 {after[k]} ≠ new_st {v}"


def test_settle_province_tick_qingzhang_action(fresh_db):
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
    # 月末固定财政相位推进省级基座：陕西种子=G1 基线，空 action 一 tick → 军饷欠 20→18、省库 50→0
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    assert _read_settle(db)["st"]["军饷欠"] == 20  # 种子
    apply_fixed_period_flows(db, state)
    after = _read_settle(db)["st"]
    assert abs(after["军饷欠"] - 18) < 1e-3, f"军饷欠 {after['军饷欠']} ≠ 18（基座未在固定财政相位推进？）"
    assert abs(after["省库库银"] - 0) < 1e-3
    assert abs(after["C_地方截留"] - 9.8) < 1e-3


def test_substrate_absent_does_not_break_flows(game):
    # 旧档（probe.db）无 settle 种子 → shadow 隔离：固定财政照常完成，不抛
    from ming_sim.flows import apply_fixed_period_flows
    db, state, _ = game
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
