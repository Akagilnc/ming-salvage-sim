"""#44：军饷应发挂钩兵力（设计 v2）——军存每军 salary_rate（两/兵·月），
应发 needed(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。
0 兵 → 0 饷（消解白嫖扩军上界 + 零兵吃饷下界）。扩军只落 manpower、应发自动随兵涨。
"""

import math

import pytest

from ming_sim.army_pay import army_needed

def _army_row(db, army_id):
    return db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()

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
    # A salaried army with source debt participates in pooled repayment.
    from ming_sim.army_pay import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    # 只留这一支有欠饷，孤立验证「它是否进得了受饷分发」
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET salary_rate=1.5, arrears=10, province_pay_arrears=0, central_pay_arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    spent = _auto_pay_arrears_by_priority(db, state, "国库", 5, "补饷", "诏拨补饷")
    assert spent > 0, "兜底拨饷应能花到该军"

def test_auto_pay_empty_allowed_ids_pays_no_armies(game):
    # #287 PR R2：空 scope 是「不允许任何军」，不能被 truthiness 当成「不限制」而回落全局池。
    from ming_sim.army_pay import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=10, province_pay_arrears=0, central_pay_arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    spent = _auto_pay_arrears_by_priority(
        db, state, "国库", 5, "补饷", "空范围补饷", allowed_army_ids=[]
    )
    row = _army_row(db, aid)
    assert spent == 0, "allowed_army_ids=[] 应明确支付 0，不得回落全军池"
    assert row["arrears"] == pytest.approx(10)

def test_auto_pay_strips_allowed_army_ids_before_filtering(game):
    from ming_sim.army_pay import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=10, province_pay_arrears=0, central_pay_arrears=10 WHERE id=?", (aid,))
    db.conn.commit()

    spent = _auto_pay_arrears_by_priority(
        db, state, "国库", 5, "补饷", "空白范围补饷", allowed_army_ids=[f" {aid} "]
    )
    row = _army_row(db, aid)
    assert spent > 0
    assert row["arrears"] < 10


def test_non_finite_salary_rate_anchored_not_crash():
    """#44 ship-pre 线上 gemini high + coderabbit inf 探针：非有限 salary_rate（inf/-inf/nan）
    须落锚点、不得崩。inf>0 为真会漏过 coerce、经 army_needed 的 ceil(manpower×inf/10000) 抛
    OverflowError 崩整月结算。两道防线：_coerce_new_salary_rate（建军入口）+ army_needed（结算咽喉）。"""
    from ming_sim.db import _coerce_new_salary_rate
    from ming_sim.army_pay import army_needed

    assert _coerce_new_salary_rate(float("inf")) == 1.5, "inf→锚点"
    assert _coerce_new_salary_rate(float("-inf")) == 1.5, "-inf→锚点"
    assert _coerce_new_salary_rate(float("nan")) == 1.5, "nan→锚点"
    # army_needed 咽喉对非有限 rate 防御性归锚点、不抛 OverflowError。
    for bad in (float("inf"), float("-inf"), float("nan")):
        row = {"owner_power": "ming", "manpower": 5000, "salary_rate": bad}
        needed = army_needed(row)
        assert needed == math.ceil(5000 * 1.5 / 10000), f"非有限 rate({bad}) 应锚点应发，得 {needed}"
