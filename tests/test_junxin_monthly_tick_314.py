"""#314 — 确定性军心月度 tick（欠饷月数分档 +5/0/-5，ADR 0025 D2）。

seam = 月末确定性结算 tick（apply_fixed_period_flows，紧邻 #287 morale tick）。
spike_settle_tick 式 oracle：喂逐月发饷序列 → 断言 loyalty 逐月轨迹。

票面验收覆盖：
① 满饷月 +5 回血
② 欠饷第 1-2 月不掉（dead-band）
③ 第 3 月起每月 -5
④ clamp 触底 [0] / 触顶 [100]
⑤ 火药桶（低初值）vs 精锐（高初值）耐受差异由初值体现
⑥ 土司军 / owner≠ming 军 loyalty 不被 tick 动
⑦ 零兵残军不除零不崩
"""

from __future__ import annotations

import pytest

from ming_sim.flows import army_loyalty_tick_delta, apply_fixed_period_flows

KEG = "guanning"    # 火药桶/主测军（content 军，needed 可控）
ELITE = "jingying"  # 精锐对照军


def _use_legacy_fiscal_engine(db):
    db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES ('__army_pay_source_cutover', 0, 'meta', 'test legacy salary path')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """
    )
    db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES ('__fiscal_engine', 0, 'meta', 'test legacy salary path')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """
    )
    db.conn.commit()


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


def _arrears_of(db, aid):
    return float(db.conn.execute(
        "SELECT arrears FROM armies WHERE id=?", (aid,)).fetchone()["arrears"])


def _run_months(db, state, months, *, fund_fully=True):
    """跑月末结算。fund_fully=True → 足额发饷：只发当月、不动旧欠，
    欠饷月数由预置的 arrears 种子精确控制（oracle 不受月度财政噪声干扰）。"""
    for _ in range(months):
        state.metrics["国库"] = 10 ** 9 if fund_fully else 0
        apply_fixed_period_flows(db, state)


def _seed_arrears_months(db, aid, months, needed):
    db.conn.execute("UPDATE armies SET arrears=? WHERE id=?", (months * needed, aid))
    db.conn.commit()


# ── oracle 单元：分档真源 ────────────────────────────────────────────────


@pytest.mark.parametrize("arrears,needed,expected", [
    (0.0, 1, 5),     # ① 满饷（arrears==0）→ +5
    (0.01, 1, 0),    # 分数欠饷 0.01 月：非满饷 → 半欠不回血（dead-band 0）
    (0.9, 1, 0),     # 分数欠饷 0.9 月：零头也是欠、半欠不回血（dead-band 0，ADR 0025 D2）
    (1.0, 1, 0),     # ② 恰好欠 1 月 → dead-band 0
    (2.0, 1, 0),     # ② 欠 2 月 → dead-band 0
    (2.99, 1, 0),
    (3.0, 1, -5),    # ③ 欠满 3 月 → -5
    (6.4, 1, -5),    # ③ 继续欠 → 每月 -5
])
def test_loyalty_tick_delta_tiers(arrears, needed, expected):
    assert army_loyalty_tick_delta(arrears, needed) == expected


def test_loyalty_tick_delta_zero_needed_no_div_zero():
    assert army_loyalty_tick_delta(50.0, 0) == 0


def test_fractional_arrears_no_recovery(game):
    # 负例：半欠不回血（ADR 0025 D2「不清欠则不脱困」）。种子欠 0.5×needed、足额发饷后
    # arrears 不变仍为分数欠饷 → loyalty 机械不动（不得 +5）。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db)
    _setup_army(db, KEG, loyalty=50)
    db.conn.commit()
    _seed_arrears_months(db, KEG, 0.5, needed=1)
    _run_months(db, state, 2)
    assert _arrears_of(db, KEG) == pytest.approx(0.5), "足额发饷月不动旧欠"
    assert _loyalty_of(db, KEG) == 50, "半欠月 loyalty 不回血不流失（dead-band）"


# ── 结算 tick 轨迹 oracle（legacy 路 seam） ───────────────────────────────


def test_full_pay_month_restores_plus5(game):
    # ① 满饷月 +5 回血（旧欠只发当月不还 → arrears 不变、仍按合计欠 6 月判？否——满饷档
    # 由「合计 arrears」驱动：旧欠在账则非满饷。故本例 arrears=0 起步、足额发饷。）
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db)
    _setup_army(db, KEG, loyalty=40)
    db.conn.commit()
    _run_months(db, state, 1)
    assert _arrears_of(db, KEG) == pytest.approx(0.0), "国库足额应发清、不累欠"
    assert _loyalty_of(db, KEG) == 45, "满饷月 loyalty +5 回血"


def test_arrears_monthly_trajectory_dead_band_then_minus5(game):
    # needed=1 万两/月；第 m 月前置种 arrears=(m-1)*1，足额发饷后仍为 (m-1)*1
    # → 本月按「已欠 m-1 月」分档：m1/m2 欠 0/1 月？——注意口径：tick 读**结算后合计**。
    # 第 m 月种子 = m*1（即结算时点已累计欠 m 月）→ m1/m2 dead-band、m3 起 -5。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db)
    _setup_army(db, KEG, loyalty=50)
    db.conn.commit()
    expected = [50, 50, 50, 45, 40, 35]  # 结算时欠 0/1/2/3/4/5 月
    trajectory = [_loyalty_of(db, KEG)]
    for m, exp in enumerate(expected[1:], start=1):
        _seed_arrears_months(db, KEG, m, needed=1)
        _run_months(db, state, 1)
        assert _arrears_of(db, KEG) == pytest.approx(m), "足额发饷月不动旧欠"
        trajectory.append(_loyalty_of(db, KEG))
    assert trajectory == expected, f"逐月轨迹 {trajectory} ≠ oracle {expected}"
    assert trajectory[1] == trajectory[0] and trajectory[2] == trajectory[0], "② dead-band"
    assert trajectory[3] < trajectory[2], "③ 第 3 月起流失"


def test_clamp_bottom_at_zero_and_top_at_hundred(game):
    # ④ clamp：触底 [0] 不为负；触顶 [100] 不越界。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db)
    _setup_army(db, KEG, loyalty=2)      # 欠 ≥3 月 -5 → clamp 0
    _setup_army(db, ELITE, loyalty=98)   # 满饷 +5 → clamp 100
    db.conn.commit()
    _seed_arrears_months(db, KEG, 3, needed=1)
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 0, "loyalty=2 欠 3 月 -5 应 clamp 触底 0"
    _seed_arrears_months(db, KEG, 5, needed=1)
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 0 and _loyalty_of(db, KEG) >= 0, "连扣不得为负"
    _run_months(db, state, 1)
    assert _loyalty_of(db, ELITE) == 100, "loyalty=98 满饷 +5 应 clamp 到 100"


def test_powder_keg_vs_elite_tolerance_by_initial_value(game):
    # ⑤ 同样欠饷序列：火药桶(初值 12) 三月即入鼓噪门口径区间，精锐(初值 80) 仍稳。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db)
    _setup_army(db, KEG, loyalty=12)
    _setup_army(db, ELITE, loyalty=80)
    _seed_arrears_months(db, KEG, 3, needed=1)
    _seed_arrears_months(db, ELITE, 3, needed=1)
    db.conn.commit()
    _run_months(db, state, 1)
    keg, elite = _loyalty_of(db, KEG), _loyalty_of(db, ELITE)
    assert keg == 7 and elite == 75, f"keg={keg} elite={elite}"
    assert keg < 42 <= elite, "火药桶已入鼓噪门口径区间、精锐远未及——耐受差异由初值体现"


def test_tusi_and_non_ming_untouched(game):
    # ⑥ 土司军 / owner≠ming 军 loyalty 不被 tick 动（即便欠饷 ≥3 月）。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db, keep=(KEG,))
    _setup_army(db, KEG, is_tusi=1, arrears=10.0, loyalty=50)
    non_ming = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power!='ming' AND id=? LIMIT 1", (ELITE,)
    ).fetchone()
    if non_ming is None:
        # 无现成非明军 → 借 ELITE 临时易主模拟（叛军/外族不吃明国库口径）
        _setup_army(db, ELITE, owner_power="houjin", arrears=10.0, loyalty=66)
        nid = ELITE
    else:
        nid = str(non_ming["id"])
    db.conn.commit()
    before_non_ming = _loyalty_of(db, nid)
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 50, "土司自养军 loyalty 不得被 tick 动"
    assert _loyalty_of(db, nid) == before_non_ming, "非明军 loyalty 不得被 tick 动"


def test_self_funded_army_untouched(game):
    # 边界：self_funded_pay=1 的明控军不吃国库饷 → loyalty 不被 tick 动（legacy 路）。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db, keep=(KEG,))
    db.conn.execute(
        "UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=1, "
        "manpower=10000, salary_rate=1.0, loyalty=50, arrears=10.0 WHERE id=?", (KEG,))
    db.conn.commit()
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 50, "自养军 loyalty 不得被 tick 动"


def test_substrate_hub_path_loyalty_tier(game):
    # substrate_hub 路：SELECT 已滤 ming+非土司+非自养；欠 ≥3 月结算后 -5，
    # 且同事务写 army_logs loyalty 行。hub 路京运克扣/运损使足饷 +5 不可精确隔离，
    # 满饷档已由 oracle 单元 + legacy 轨迹覆盖，此处只钉 hub 路接线。
    db, state, _ = game
    _silence_other_armies(db)
    # 全额中央份额，绕开省级饷源噪声；needed=1 万两/月。
    db.conn.execute(
        "UPDATE armies SET province_pay_share=0, central_pay_share=1.0, "
        "province_pay_arrears=0, central_pay_arrears=0 WHERE id=?", (KEG,))
    _setup_army(db, KEG, loyalty=50)
    # hub 路结算后 arrears 由饷源列重算（province/central_pay_arrears），种子须落中央欠列。
    db.conn.execute("UPDATE armies SET central_pay_arrears=3.0 WHERE id=?", (KEG,))
    db.conn.commit()
    _run_months(db, state, 1)
    assert _loyalty_of(db, KEG) == 45, "hub 路欠 3 月 → -5"
    log = db.conn.execute(
        "SELECT delta FROM army_logs WHERE army_id=? AND field='loyalty' "
        "ORDER BY id DESC LIMIT 1", (KEG,)).fetchone()
    assert log is not None and int(log["delta"]) == -5, "hub 路同事务写 loyalty 日志"


def test_substrate_hub_pure_province_source_loyalty_regression(game):
    """处方3a 纯省源 1.0/0.0 — 旧 hub 只遍历 central_pay_share>0，纯省军永冻。

    manpower=10000 salary_rate=1.0 needed=1 province_pay_arrears=3 central=0，
    足额国库后跑一次 apply_fixed_period_flows，断言 loyalty -5 且 loyalty 日志仅一条、
    reason 为累计欠饷逾三月（不含“中央军饷足额”）。旧码纯省永冻 0 变化 FAIL。
    """
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
    reason = str(logs[0]["reason"])
    assert "累计欠饷逾三月" in reason, f"reason 应为累计原因，实得 {reason!r}"
    assert "中央军饷足额" not in reason, f"累计原因不得含中央军饷足额，实得 {reason!r}"


def test_substrate_hub_hybrid_source_loyalty_regression(game):
    """处方3b 混合 0.55/0.45 — 旧 hub 在省结算前按上月省欠分档、reason 复用当月 shortfall。

    同 a 的 arrears/国库条件，断言同 a。旧码因时序/复用原因导致 reason 含“中央军饷足额”FAIL。
    """
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
    reason = str(logs[0]["reason"])
    assert "累计欠饷逾三月" in reason, f"reason 应为累计原因，实得 {reason!r}"
    assert "中央军饷足额" not in reason, f"累计原因不得含中央军饷足额，实得 {reason!r}"


def test_zero_manpower_army_no_crash_no_tick(game):
    # ⑦ 零兵残军 needed<=0 → continue 短路：不除零、loyalty 不动。
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    _silence_other_armies(db, keep=(KEG,))
    _setup_army(db, KEG, manpower=0, arrears=10.0, loyalty=30)
    db.conn.commit()
    _run_months(db, state, 2)
    assert _loyalty_of(db, KEG) == 30, "零兵残军 loyalty 不得被 tick 动"
