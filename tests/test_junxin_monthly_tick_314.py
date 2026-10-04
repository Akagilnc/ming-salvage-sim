"""#314 — 确定性军心月度 tick（欠饷月数分档 +5/0/-5，ADR 0025 D2）。

seam = 月末确定性结算 tick（apply_fixed_period_flows，现役 substrate_hub）。
oracle：army_loyalty_tick_delta 分档 + hub 路真实落库接线。

票面验收覆盖：
① 满饷月 +5 回血（oracle 单元）
② 欠饷第 1-2 月不掉（dead-band，oracle 单元）
③ 第 3 月起每月 -5（oracle + hub 落库）
④ clamp 触底/触顶（oracle 单元；落库侧 clamp 由 hub tick）
⑤ 土司 / 非明 / 自养 / 零兵不被 tick 动（hub 路）
"""

from __future__ import annotations

import pytest

from ming_sim.army_pay import army_loyalty_tick_delta
from ming_sim.flows import apply_fixed_period_flows

KEG = "guanning"    # 火药桶/主测军（content 军，needed 可控）
ELITE = "jingying"  # 精锐对照军


def _silence_other_armies(db, keep=(KEG, ELITE)):
    """其余全军 manpower=0（needed=0 → continue 短路），孤立被测军。"""
    marks = ",".join("?" for _ in keep)
    db.conn.execute(
        f"UPDATE armies SET manpower=0 WHERE id NOT IN ({marks})", keep)


def _setup_army(db, aid, *, loyalty=50, arrears=0.0, manpower=10000,
                salary_rate=1.0, is_tusi=0, owner_power="ming"):
    """needed = ceil(10000×1.0/10000) = 1 万两/月。"""
    db.conn.execute(
        """
        UPDATE armies
        SET owner_power=?, is_tusi=?, self_funded_pay=0,
            manpower=?, salary_rate=?, loyalty=?, arrears=?, morale=50
        WHERE id=?
        """,
        (owner_power, is_tusi, manpower, salary_rate, loyalty, arrears, aid),
    )


def _loyalty_of(db, aid):
    return int(db.conn.execute(
        "SELECT loyalty FROM armies WHERE id=?", (aid,)).fetchone()["loyalty"])


def _run_months(db, state, months, *, fund_fully=True):
    for _ in range(months):
        state.metrics["国库"] = 10 ** 9 if fund_fully else 0
        apply_fixed_period_flows(db, state)


def test_army_loyalty_tick_delta_tiers():
    """分档 oracle：满饷 +5；半欠/短欠 dead-band 0；≥3 月 -5；零需短路 0。"""
    assert army_loyalty_tick_delta(0, 1) == 5
    assert army_loyalty_tick_delta(0.5, 1) == 0
    assert army_loyalty_tick_delta(1, 1) == 0
    assert army_loyalty_tick_delta(2, 1) == 0
    assert army_loyalty_tick_delta(3, 1) == -5
    assert army_loyalty_tick_delta(5, 1) == -5
    assert army_loyalty_tick_delta(10, 0) == 0


def test_substrate_hub_path_loyalty_tier(game):
    # substrate_hub 路：欠 ≥3 月结算后 -5，且同事务写 army_logs loyalty 行。
    db, state, _ = game
    _silence_other_armies(db)
    db.conn.execute(
        "UPDATE armies SET province_pay_share=0, central_pay_share=1.0, "
        "province_pay_arrears=0, central_pay_arrears=0 WHERE id=?", (KEG,))
    _setup_army(db, KEG, loyalty=50)
    db.conn.execute("UPDATE armies SET central_pay_arrears=3.0 WHERE id=?", (KEG,))
    db.conn.commit()
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 45, "hub 路欠 3 月 → -5"
    log = db.conn.execute(
        "SELECT delta FROM army_logs WHERE army_id=? AND field='loyalty' "
        "ORDER BY id DESC LIMIT 1", (KEG,)).fetchone()
    assert log is not None and int(log["delta"]) == -5, "hub 路同事务写 loyalty 日志"


def test_substrate_hub_pure_province_source_loyalty_regression(game):
    """纯省源 1.0/0.0 — hub 路仍按合计欠饷分档动 loyalty。"""
    db, state, _ = game
    aid = "fujian_navy"  # 种子纯省源 fujian 1.0/0.0
    _silence_other_armies(db, keep=(aid,))
    db.conn.execute(
        """
        UPDATE armies
        SET owner_power='ming', is_tusi=0, self_funded_pay=0,
            manpower=10000, salary_rate=1.0, loyalty=50, morale=50,
            province_pay_share=1.0, central_pay_share=0.0,
            pay_source_region='fujian',
            province_pay_arrears=3.0, central_pay_arrears=0, arrears=3.0
        WHERE id=?
        """,
        (aid,),
    )
    db.conn.commit()
    db.conn.execute("DELETE FROM army_logs WHERE army_id=?", (aid,))
    db.conn.commit()
    state.metrics["国库"] = 10 ** 9
    apply_fixed_period_flows(db, state)
    assert _loyalty_of(db, aid) == 45, "纯省源欠 3 月结算后 loyalty 应 -5"
    logs = db.conn.execute(
        "SELECT delta, reason FROM army_logs WHERE army_id=? AND field='loyalty' ORDER BY id",
        (aid,),
    ).fetchall()
    assert len(logs) == 1, f"忠诚日志应仅一条，实得 {len(logs)}"
    assert int(logs[0]["delta"]) == -5


def test_substrate_hub_hybrid_source_loyalty_regression(game):
    """混合 0.55/0.45 — hub 路按合计欠饷分档。"""
    db, state, _ = game
    aid = "xuan_da"  # 种子混合 shanxi 0.55/0.45
    _silence_other_armies(db, keep=(aid,))
    db.conn.execute(
        """
        UPDATE armies
        SET owner_power='ming', is_tusi=0, self_funded_pay=0,
            manpower=10000, salary_rate=1.0, loyalty=50, morale=50,
            province_pay_share=0.55, central_pay_share=0.45,
            pay_source_region='shanxi',
            province_pay_arrears=3.0, central_pay_arrears=0, arrears=3.0
        WHERE id=?
        """,
        (aid,),
    )
    db.conn.commit()
    db.conn.execute("DELETE FROM army_logs WHERE army_id=?", (aid,))
    db.conn.commit()
    state.metrics["国库"] = 10 ** 9
    apply_fixed_period_flows(db, state)
    assert _loyalty_of(db, aid) == 45, "混合省源欠 3 月结算后 loyalty 应 -5"
    logs = db.conn.execute(
        "SELECT delta, reason FROM army_logs WHERE army_id=? AND field='loyalty' ORDER BY id",
        (aid,),
    ).fetchall()
    assert len(logs) == 1, f"忠诚日志应仅一条，实得 {len(logs)}"
    assert int(logs[0]["delta"]) == -5


def test_tusi_and_non_ming_untouched_on_hub(game):
    db, state, _ = game
    # 豁免军分源份额/欠饷须全 0（守恒）；本案只验 loyalty 不被 tick，cutover 保持现役。
    _silence_other_armies(db, keep=(KEG, ELITE))
    _setup_army(db, KEG, is_tusi=1, arrears=0.0, loyalty=50)
    _setup_army(db, ELITE, owner_power="houjin", arrears=0.0, loyalty=66)
    db.conn.execute(
        "UPDATE armies SET province_pay_share=0, central_pay_share=0, "
        "pay_source_region='', province_pay_arrears=0, central_pay_arrears=0, "
        "arrears=0 WHERE id IN (?, ?)",
        (KEG, ELITE),
    )
    db.conn.commit()
    before_non_ming = _loyalty_of(db, ELITE)
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 50, "土司自养军 loyalty 不得被 tick 动"
    assert _loyalty_of(db, ELITE) == before_non_ming, "非明军 loyalty 不得被 tick 动"


def test_self_funded_army_untouched_on_hub(game):
    db, state, _ = game
    _silence_other_armies(db, keep=(KEG,))
    db.conn.execute(
        "UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=1, "
        "manpower=10000, salary_rate=1.0, loyalty=50, arrears=0.0, "
        "province_pay_share=0, central_pay_share=0, pay_source_region='', "
        "province_pay_arrears=0, central_pay_arrears=0 WHERE id=?",
        (KEG,),
    )
    db.conn.commit()
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 50, "自养军 loyalty 不得被 tick 动"


def test_zero_manpower_army_no_crash_no_tick_on_hub(game):
    db, state, _ = game
    _silence_other_armies(db, keep=(KEG,))
    _setup_army(db, KEG, manpower=0, arrears=10.0, loyalty=30)
    db.conn.execute(
        "UPDATE armies SET province_pay_share=0, central_pay_share=1.0, "
        "province_pay_arrears=0, central_pay_arrears=10.0 WHERE id=?",
        (KEG,),
    )
    db.conn.commit()
    _run_months(db, state, 2)
    assert _loyalty_of(db, KEG) == 30, "零兵残军 loyalty 不得被 tick 动"
