"""#44：军饷应发挂钩兵力（设计 v2）——军存每军 salary_rate（两/兵·月），
应发 needed(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。
0 兵 → 0 饷（消解白嫖扩军上界 + 零兵吃饷下界）。扩军只落 manpower、应发自动随兵涨。
"""

import math

import pytest

from ming_sim.flows import army_needed


def _army_row(db, army_id):
    return db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()


@pytest.mark.parametrize("army_id,expected", [
    ("guanning", 15),   # 72000 × 2.0 / 10000 = 14.4 → ceil 15
    ("jingying", 9),    # 85000 × 1.0 / 10000 = 8.5 → ceil 9
    ("xuan_da", 10),    # 65000 × 1.5 / 10000 = 9.75 → ceil 10
    ("jizhen", 9),      # 52000 × 1.55 / 10000 = 8.06 → ceil 9
    ("southwest_tusi", 2),  # 24000 × 0.8 / 10000 = 1.92 → ceil 2
])
def test_army_needed_derives_from_manpower_rate(game, army_id, expected):
    db, state, _ = game
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


def test_army_needed_non_ming_no_pay(game):
    # 非明军（owner_power != ming）不强加饷需（叛军/外族不吃明国库）。
    db, state, _ = game
    row = db.conn.execute(
        "SELECT * FROM armies WHERE owner_power!='ming' LIMIT 1").fetchone()
    if row is None:
        pytest.skip("无非明军")
    assert army_needed(row) == 0


def test_total_ming_salary_near_design(game):
    # 设计总月应发 ~66.5 万两（结构性重切非抬总额，开局国库零冲击）。
    db, state, _ = game
    rows = db.conn.execute("SELECT * FROM armies WHERE owner_power='ming'").fetchall()
    total = sum(army_needed(r) for r in rows)
    assert 60 <= total <= 72, f"明军总月应发 {total} 万两应在设计 ~66.5 附近"


def test_manpower_clamp_to_zero_leaves_army_log(game):
    # #44 顺手：减兵超过现有 → clamp 0、净 delta=0，但请求非 0 → 留 army_log（不静默吞，#14/#44）。
    db, state, _ = game
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "裁军"})()
    before = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    db.apply_army_deltas(state, pseudo, None, "裁撤", {aid: {"manpower": -99999999}})
    after = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    assert after == before + 1, "请求非 0 经 clamp 0 应留 army_log（不静默）"
    assert db.conn.execute(
        "SELECT manpower FROM armies WHERE id=?", (aid,)).fetchone()[0] == 0


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


def test_twelve_turns_no_arrears_explosion(game):
    # #44 设计 TDD：开局 12 回合无干预，新升率（京营/陕西/登莱等率升）不过早引爆 arrears→民变链。
    # 结构性重切近对冲（旧 65 → 新 66.5 万/月），开局国库应可持续。run_settle(None) 确定性、无 LLM。
    from driver import run_settle
    db, state, content = game
    start_turn = state.turn
    for _ in range(12):
        run_settle(db, state, content, None)
    assert state.turn == start_turn + 12, "12 回合应推进 12 turn"
    total_arrears = db.conn.execute(
        "SELECT SUM(arrears) FROM armies WHERE owner_power='ming'").fetchone()[0] or 0
    # 不失控（升率引爆民变）：开局结构性重切非抬总额，12 回合 arrears 应有界
    assert total_arrears < 1000, f"12 回合 arrears={total_arrears} 万两不应失控引爆"
