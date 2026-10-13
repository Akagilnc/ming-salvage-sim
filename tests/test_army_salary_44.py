from ming_sim.applier import Provenance
import pytest
from ming_sim.flows import apply_fixed_period_flows
"""#44：军饷应发挂钩兵力（设计 v2）——军存每军 salary_rate（两/兵·月），
应发 needed(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。
0 兵 → 0 饷（消解白嫖扩军上界 + 零兵吃饷下界）。扩军只落 manpower、应发自动随兵涨。
"""



def _army_row(db, army_id):
    return db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()

@pytest.mark.parametrize("army_id,manpower,rate,owner,expected", [
    ("guanning", 72000, 2, "ming", 15),
    ("jingying", 85000, 1, "ming", 9),
    ("xuan_da", 65000, 1.5, "ming", 10),
    ("jizhen", 52000, 1.55, "ming", 9),
    ("southwest_tusi", 24000, 0.8, "ming", 2),
    ("guanning", 0, 2, "ming", 0),
    ("guanning", 144000, 2, "ming", 29),
    ("xuan_da", 32500, 1.5, "ming", 5),
    ("manchu_banners_main", 72000, 2, "houjin", 0),
    ("manchu_banners_main", 32000, 0, "ming", 5),
    ("guanning", 5000, 0, "ming", 1),
    ("guanning", 5000, float("inf"), "ming", 1),
    ("guanning", 5000, float("-inf"), "ming", 1),
])
def test_army_needed_derives_from_manpower_rate(game, army_id, manpower, rate, owner, expected):
    """无可支国库时，应发必须在真实月度核账成为该军中央欠饷。"""
    db, state, _ = game
    db.conn.execute("UPDATE armies SET manpower=0")
    db.conn.execute(
        "UPDATE armies SET manpower=?,salary_rate=?,owner_power=?,is_tusi=0,"
        "self_funded_pay=0,pay_source_region='beizhili',province_pay_share=0,central_pay_share=?,"
        "province_pay_arrears=0,central_pay_arrears=0 WHERE id=?",
        (manpower, rate, owner, int(owner == "ming"), army_id),
    )
    state.metrics["国库"] = 0
    db.reign.save_game_state(state)
    db.conn.commit()
    apply_fixed_period_flows(db, state)
    assert _army_row(db, army_id)["central_pay_arrears"] == pytest.approx(expected)


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
    db.apply_army_deltas(state, pseudo, None, "裁撤", {aid: {"manpower": -5}}, source=Provenance.system_simulation)  # 0 再减 → clamp 0、请求非 0
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
    db.apply_army_deltas(state, pseudo, None, "无变", {aid: {"manpower": 0}}, source=Provenance.system_simulation)
    after = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='manpower'", (aid,)).fetchone()[0]
    assert after == before, "真 no-op(delta==0)不留痕"

def test_auto_pay_empty_allowed_ids_pays_no_armies(game):
    # #287 PR R2：空 scope 是「不允许任何军」，不能被 truthiness 当成「不限制」而回落全局池。
    from ming_sim.army_pay import _auto_pay_arrears_by_priority
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET province_pay_arrears=0, central_pay_arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    spent = _auto_pay_arrears_by_priority(
        db, state, "国库", 5, "补饷", "空范围补饷", allowed_army_ids=[]
    )
    row = _army_row(db, aid)
    assert spent == 0, "allowed_army_ids=[] 应明确支付 0，不得回落全军池"
    assert row["arrears"] == pytest.approx(10)


def _pay_source():
    return {
        "pay_source_region": "shaanxi",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }
