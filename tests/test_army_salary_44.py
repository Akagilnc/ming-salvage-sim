"""#44：军饷应发挂钩兵力（设计 v2）——军存每军 salary_rate（两/兵·月），
应发 needed(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。
0 兵 → 0 饷（消解白嫖扩军上界 + 零兵吃饷下界）。扩军只落 manpower、应发自动随兵涨。
"""

import math

import pytest

from ming_sim.flows import army_needed


def _army_row(db, army_id):
    return db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()


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


@pytest.mark.parametrize("army_id,expected", [
    ("guanning", 15),   # 72000 × 2.0 / 10000 = 14.4 → ceil 15
    ("jingying", 9),    # 85000 × 1.0 / 10000 = 8.5 → ceil 9
    ("xuan_da", 10),    # 65000 × 1.5 / 10000 = 9.75 → ceil 10
    ("jizhen", 9),      # 52000 × 1.55 / 10000 = 8.06 → ceil 9
    ("southwest_tusi", 2),  # 24000 × 0.8 / 10000 = 1.92 → ceil 2
])
def test_army_needed_derives_from_manpower_rate(read_game, army_id, expected):
    db, state, _ = read_game
    assert army_needed(_army_row(db, army_id)) == expected


def test_army_needed_zero_manpower_zero_pay(game):
    # 0 兵 → 应发 0（白嫖扩军上界 + 零兵吃饷下界一并消解，无需 #22 撤番）。
    db, state, _ = game
    db.conn.execute("UPDATE armies SET manpower=0 WHERE id='guanning'")
    db.conn.commit()
    assert army_needed(_army_row(db, "guanning")) == 0


def test_army_needed_scales_with_manpower(game):
    # 扩军（manpower 涨）→ 应发随之涨（不再「兵涨饷不涨」白嫖）。
    db, state, _ = game
    before = army_needed(_army_row(db, "guanning"))
    db.conn.execute("UPDATE armies SET manpower=manpower*2 WHERE id='guanning'")
    db.conn.commit()
    after = army_needed(_army_row(db, "guanning"))
    assert after > before
    assert after == math.ceil(_army_row(db, "guanning")["manpower"] * _army_row(db, "guanning")["salary_rate"] / 10000)


def test_army_needed_shrink_lowers_pay(game):
    # 裁军（manpower 负 delta）→ 应发降。
    db, state, _ = game
    before = army_needed(_army_row(db, "xuan_da"))
    db.conn.execute("UPDATE armies SET manpower=manpower/2 WHERE id='xuan_da'")
    db.conn.commit()
    assert army_needed(_army_row(db, "xuan_da")) < before


def test_army_needed_non_ming_no_pay(read_game):
    # 非明军（owner_power != ming）不强加饷需（叛军/外族不吃明国库）。
    db, state, _ = read_game
    row = db.conn.execute(
        "SELECT * FROM armies WHERE owner_power!='ming' LIMIT 1").fetchone()
    if row is None:
        pytest.skip("无非明军")
    assert army_needed(row) == 0


def test_defected_army_to_ming_owes_salary_not_free(read_game):
    """#44 ship-pre cmr R1（codex high）：原非明军经 owner_power 翻成 ming（倒戈/招安，军务 extractor
    prompt 明确要求写归属）后，salary_rate<=0（非明军 content 默认 0）不得让 army_needed 返 0 =
    零饷白嫖军——这正是 #44 已经募兵入口（_coerce_new_salary_rate 默认 1.5）+ 迁移入口
    （_backfill_salary_rate）堵住、但经 runtime 易主漏网的同一 exploit。army_needed 对
    ming + manpower>0 + rate<=0 锚定 1.5 → 应发>0。"""
    db, state, _ = read_game
    src = db.conn.execute(
        "SELECT * FROM armies WHERE owner_power!='ming' AND manpower>0 ORDER BY manpower DESC LIMIT 1"
    ).fetchone()
    if src is None:
        pytest.skip("无非明军可模拟倒戈")
    assert float(src["salary_rate"]) <= 0, "前提：非明军 content salary_rate 应<=0（默认 0）"
    manpower = int(src["manpower"])
    # 模拟 owner_power 翻成 ming（salary_rate 仍是非明军默认 0），settlement 读该行算应发。
    flipped = {"owner_power": "ming", "manpower": manpower, "salary_rate": float(src["salary_rate"])}
    needed = army_needed(flipped)
    assert needed == math.ceil(manpower * 1.5 / 10000), (
        f"倒戈成 ming 的大军(rate<=0)须按锚点 1.5 欠饷、非零饷白嫖（army_needed={needed}）"
    )
    assert needed > 0


def _insert_dynamic_ming_army(db, aid, name, manpower):
    """构造旧档动态明军（id 不在 content）：salary_rate 留 0（旧档 default）模拟未迁移态。
    #173：维护费列已删，不再传 maintenance。"""
    db.conn.execute(
        "INSERT INTO armies (id, name, station, theater, commander, controller, troop_type, "
        "manpower, supply, morale, training, equipment, arrears, mobility, "
        "loyalty, salary_rate, status, owner_power) "
        "VALUES (?, ?, '某地', 'jingji', '某将', 'ming', '步', ?, 80, 70, 60, 50, 0, 50, 70, 0, '驻防', 'ming')",
        (aid, name, manpower),
    )


def test_backfill_dynamic_army_falls_to_anchor(game):
    """#173 删 maintenance 后：动态明军（不在 content、salary_rate<=0）回填 salary_rate 一律落
    边军史实锚点——原「从 maintenance_per_turn 反推率（maint×10000/manpower）」的②路随列删除、
    并入锚点兜底（该回填仅 salary_rate 列首次 ADD 时跑一次，现存档早跑过、不再触发）。"""
    db, state, _ = game
    from ming_sim.constants import SALARY_RATE_ANCHOR
    _insert_dynamic_ming_army(db, "dyn_old_army", "某旧募军", 5000)
    db.conn.commit()
    db._backfill_salary_rate()
    db.conn.commit()
    row = db.conn.execute("SELECT salary_rate FROM armies WHERE id='dyn_old_army'").fetchone()
    assert row["salary_rate"] == pytest.approx(SALARY_RATE_ANCHOR), (
        f"动态旧军应落锚点 {SALARY_RATE_ANCHOR}，得 {row['salary_rate']}"
    )


def test_backfill_reverse_fills_from_maintenance_on_direct_upgrade(game):
    """#173 cmr drop R4(codex medium)：backfill 在 _drop_maintenance_column 之前跑，**直接升级
    老档**（salary_rate 首次 ADD 时维护费列仍在）须从 maintenance_per_turn 反推率（maint×10000/
    manpower），保旧档应发量级——不落锚点（否则 5000 兵 maint=20 重定价成 army_needed 20→1 腐蚀
    旧档预算）。与上一测试（列已删→锚点）互补，钉 column-exists gate 两态。"""
    db, _state, _ = game
    # 模拟直接升级老档：维护费列仍在 + 一支 salary_rate=0 的动态明军（不在 content）。
    db.conn.execute("ALTER TABLE armies ADD COLUMN maintenance_per_turn INTEGER NOT NULL DEFAULT 0")
    _insert_dynamic_ming_army(db, "dyn_up", "动态旧军", 5000)  # salary_rate 留 0
    db.conn.execute("UPDATE armies SET maintenance_per_turn=20 WHERE id='dyn_up'")
    db.conn.commit()
    db._backfill_salary_rate()
    db.conn.commit()
    row = db.conn.execute("SELECT salary_rate FROM armies WHERE id='dyn_up'").fetchone()
    assert row["salary_rate"] == pytest.approx(20 * 10000 / 5000), (
        f"维护费列在时动态军应从 maint 反推率=40（保旧档预算），得 {row['salary_rate']}"
    )


@pytest.mark.parametrize("manpower,maint", [
    (5000, 0),   # maint<=0 → 锚点
    (0, 20),     # manpower<=0 → 锚点（避免除零）
])
def test_backfill_anchor_when_column_present_but_data_unusable(game, manpower, maint):
    """#173 cmr drop PR R1(Sourcery)/R2(CodeRabbit)：维护费列**在**但数据不可用（maint<=0 或
    manpower<=0）→ ②反推兜底落边军史实锚点（不除零、不留 0 率白嫖）。两 case 锁退化两支
    （前一测试钉列在+正常数据反推、再前一钉列不在锚点）。"""
    db, _state, _ = game
    from ming_sim.constants import SALARY_RATE_ANCHOR
    db.conn.execute("ALTER TABLE armies ADD COLUMN maintenance_per_turn INTEGER NOT NULL DEFAULT 0")
    _insert_dynamic_ming_army(db, "dyn_unusable", "退化动态军", manpower)  # salary_rate 留 0
    db.conn.execute("UPDATE armies SET maintenance_per_turn=? WHERE id='dyn_unusable'", (maint,))
    db.conn.commit()
    db._backfill_salary_rate()
    db.conn.commit()
    row = db.conn.execute("SELECT salary_rate FROM armies WHERE id='dyn_unusable'").fetchone()
    assert row["salary_rate"] == pytest.approx(SALARY_RATE_ANCHOR), (
        f"维护费列在但 maint={maint}/manpower={manpower} 应落锚点（②反推兜底），得 {row['salary_rate']}"
    )


def test_total_ming_salary_is_72_ceil_sum(read_game):
    # 实际总月应发 = sum(ceil(每军))=72 万两。设计「66.5」是 sum(小数月应发)；army_needed 每军 ceil
    # （万两整数、不少发），ceil 累积使总额 72 > 66.5（cmr r1 codex/claude 实测）。开局 vs 旧 65 = +10.8%
    # （非设计表述的 +2.4%）——ceil 公式 vs「66.5 零冲击」是设计内部不一致，ceil 公式经 ratify，此处锁实际值。
    db, state, _ = read_game
    rows = db.conn.execute("SELECT * FROM armies WHERE owner_power='ming'").fetchall()
    total = sum(army_needed(r) for r in rows)
    assert total == 72, f"明军总月应发 = sum(ceil)=72 万两（设计 66.5 为小数和），实得 {total}"


def test_manpower_clamp_to_zero_leaves_army_log(game):
    # #44 顺手：0 兵再减 → clamp 仍 0、净 delta==0，但请求非 0 → 留 army_log delta=0（不静默吞，#14/#44）。
    # cmr r4 codex：起点必须先置 0 才命中 clamp 分支——正 manpower 减大数 → 净 delta 为负、走正常路。
    db, state, _ = game
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    db.conn.execute("UPDATE armies SET manpower=0 WHERE id=?", (aid,))  # 起点 0 兵，命中 clamp 净 0 分支
    db.conn.commit()
    pseudo = type("E", (), {"id": "test", "title": "裁军"})()
    before = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    db.apply_army_deltas(state, pseudo, None, "裁撤", {aid: {"manpower": -5}})  # 0 再减 → clamp 0、请求非 0
    after = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    assert after == before + 1, "0 兵再减(请求非 0 经 clamp 净 0)应留 army_log（不静默）"
    last = db.conn.execute(
        "SELECT delta FROM army_logs WHERE army_id=? AND field='manpower' ORDER BY id DESC LIMIT 1",
        (aid,)).fetchone()
    assert last["delta"] == 0, "clamp 净 0 的 army_log delta 应为 0"


def test_manpower_true_noop_no_log(game):
    # 真 no-op（manpower delta==0）不留痕避噪。
    db, state, _ = game
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "无变"})()
    before = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    db.apply_army_deltas(state, pseudo, None, "无变", {aid: {"manpower": 0}})
    after = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    assert after == before, "真 no-op(delta==0)不留痕"


def test_auto_pay_reaches_salary_army_via_arrears_filter(game):
    # #44 受饷资格用 arrears>0（不再 maintenance>0）；#173 删 maintenance 列后，受饷 filter 唯一
    # 依据 arrears>0。验证：salary_rate>0 累 arrears 的军被纳入受饷候选、且兜底拨饷真能花到（spent>0）。
    from ming_sim.flows import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    # 只留这一支有欠饷，孤立验证「它是否进得了受饷分发」
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET salary_rate=1.5, arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    hit = {str(r["id"]) for r in db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' AND arrears>0")}
    assert aid in hit, "arrears>0 filter 应纳入累 arrears 的军"
    spent = _auto_pay_arrears_by_priority(db, state, "国库", 5, "补饷", "诏拨补饷")
    assert spent > 0, "兜底拨饷应能花到该军"


def test_auto_pay_empty_allowed_ids_pays_no_armies(game):
    # #287 PR R2：空 scope 是「不允许任何军」，不能被 truthiness 当成「不限制」而回落全局池。
    from ming_sim.flows import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    spent = _auto_pay_arrears_by_priority(
        db, state, "国库", 5, "补饷", "空范围补饷", allowed_army_ids=[]
    )
    row = _army_row(db, aid)
    assert spent == 0, "allowed_army_ids=[] 应明确支付 0，不得回落全军池"
    assert row["arrears"] == pytest.approx(10)


def test_auto_pay_strips_allowed_army_ids_before_filtering(game):
    from ming_sim.flows import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=10 WHERE id=?", (aid,))
    db.conn.commit()

    spent = _auto_pay_arrears_by_priority(
        db, state, "国库", 5, "补饷", "空白范围补饷", allowed_army_ids=[f" {aid} "]
    )
    row = _army_row(db, aid)
    assert spent > 0
    assert row["arrears"] < 10


def test_legacy_salary_tick_preserves_fractional_opening_arrears(game):
    from ming_sim.flows import apply_fixed_period_flows
    db, state, _ = game
    _use_legacy_fiscal_engine(db)
    aid = "guanning"
    db.conn.execute("UPDATE armies SET manpower=0, arrears=0 WHERE owner_power='ming'")
    db.conn.execute(
        """
        UPDATE armies
        SET owner_power='ming', manpower=10000, salary_rate=1.0, arrears=1.5, morale=50
        WHERE id=?
        """,
        (aid,),
    )
    db.conn.commit()
    state.metrics["国库"] = 50

    apply_fixed_period_flows(db, state)

    row = _army_row(db, aid)
    assert row["arrears"] == pytest.approx(1.5)
    log = db.conn.execute(
        """
        SELECT old_value, new_value, delta
        FROM army_logs
        WHERE army_id=? AND field='arrears'
        ORDER BY id DESC
        LIMIT 1
        """,
        (aid,),
    ).fetchone()
    assert log["old_value"] == "1.5"
    assert log["new_value"] == "1.5"
    assert log["delta"] == pytest.approx(0.0)


def test_coerce_new_salary_rate_blocks_freeload():
    # cmr r3 codex medium: 新军 salary_rate 健壮解析——负/非数/bool/0/None → 锚点 1.5（防免费军白嫖）。
    # 原 `or 1.5` 漏负值：-1 经 army_needed(rate<=0→0) 成免费军，绕过 #44 防白嫖。
    from ming_sim.db import _coerce_new_salary_rate
    assert _coerce_new_salary_rate(-1) == 1.5, "负值=白嫖→锚点"
    assert _coerce_new_salary_rate(0) == 1.5
    assert _coerce_new_salary_rate(None) == 1.5
    assert _coerce_new_salary_rate("脏") == 1.5, "非数→锚点"
    assert _coerce_new_salary_rate(True) == 1.5, "bool→锚点"
    assert _coerce_new_salary_rate(2.0) == 2.0, "正常正值保留"


def test_non_finite_salary_rate_anchored_not_crash():
    """#44 ship-pre 线上 gemini high + coderabbit inf 探针：非有限 salary_rate（inf/-inf/nan）
    须落锚点、不得崩。inf>0 为真会漏过 coerce、经 army_needed 的 ceil(manpower×inf/10000) 抛
    OverflowError 崩整月结算。两道防线：_coerce_new_salary_rate（建军入口）+ army_needed（结算咽喉）。"""
    from ming_sim.db import _coerce_new_salary_rate
    from ming_sim.flows import army_needed

    assert _coerce_new_salary_rate(float("inf")) == 1.5, "inf→锚点"
    assert _coerce_new_salary_rate(float("-inf")) == 1.5, "-inf→锚点"
    assert _coerce_new_salary_rate(float("nan")) == 1.5, "nan→锚点"
    # army_needed 咽喉对非有限 rate 防御性归锚点、不抛 OverflowError。
    for bad in (float("inf"), float("-inf"), float("nan")):
        row = {"owner_power": "ming", "manpower": 5000, "salary_rate": bad}
        needed = army_needed(row)
        assert needed == math.ceil(5000 * 1.5 / 10000), f"非有限 rate({bad}) 应锚点应发，得 {needed}"


def test_twelve_turns_no_arrears_explosion(game):
    # #44 设计 TDD：开局 12 回合无干预，新升率（京营/陕西/登莱等率升）不过早引爆 arrears→民变链。
    # 结构性重切近对冲（旧 65 → 新 66.5 万/月），开局国库应可持续。run_settle(None) 确定性、无 LLM。
    from tests.section_rejection_helpers import prepare_then_settle as run_settle
    db, state, content = game
    start_turn = state.turn
    for _ in range(12):
        run_settle(db, state, content, None)
    assert state.turn == start_turn + 12, "12 回合应推进 12 turn"
    total_arrears = db.conn.execute(
        "SELECT SUM(arrears) FROM armies WHERE owner_power='ming'").fetchone()[0] or 0
    # 不失控（升率引爆民变）：开局结构性重切非抬总额，12 回合 arrears 应有界
    assert total_arrears < 1000, f"12 回合 arrears={total_arrears} 万两不应失控引爆"
