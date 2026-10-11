"""#44：军饷应发挂钩兵力（设计 v2）——军存每军 salary_rate（两/兵·月），
应发 needed(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。
0 兵 → 0 饷（消解白嫖扩军上界 + 零兵吃饷下界）。扩军只落 manpower、应发自动随兵涨。
"""


import pytest

def _army_row(db, army_id):
    return db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()


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

def test_auto_pay_empty_allowed_ids_pays_no_armies(game):
    """#287 PR R2：空 scope 是「不允许任何军」，不能回落全局池。经公共 commitment 路径：
    门中无有效军 id（仅空白）→ 池范围为空 → 不得拨饷给任何军。"""
    import json
    from ming_sim.situation_drift import apply_situation_monthly_drift
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=10, province_pay_arrears=0, central_pay_arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    db.insert_issue(
        state, kind="initiative", title="空范围补饷承诺", origin_kind="decree",
        origin_ref="decree:turn-44:empty", bar_value=0, inertia=0,
        ongoing_effects={"economy": [{"account": "国库", "delta": -5, "reason": "空范围补饷", "purpose": "补饷"}]},
        stop_condition=json.dumps({"army. .arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )
    apply_situation_monthly_drift(db, state)
    assert db.conn.execute("SELECT arrears FROM armies WHERE id=?", (aid,)).fetchone()[0] == pytest.approx(10)

def test_auto_pay_strips_allowed_army_ids_before_filtering(game):
    """门中军 id 带空白仍须归一后命中该军（经公共 commitment 路径）。"""
    import json
    from ming_sim.situation_drift import apply_situation_monthly_drift
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=10, province_pay_arrears=0, central_pay_arrears=10 WHERE id=?", (aid,))
    db.conn.commit()
    db.insert_issue(
        state, kind="initiative", title="空白范围补饷承诺", origin_kind="decree",
        origin_ref="decree:turn-44:strip", bar_value=0, inertia=0,
        ongoing_effects={"economy": [{"account": "国库", "delta": -5, "reason": "空白范围补饷", "purpose": "补饷"}]},
        stop_condition=json.dumps({f"army. {aid} .arrears": "<=0"}, ensure_ascii=False),
        commitment_kind="until_stop",
    )
    apply_situation_monthly_drift(db, state)
    assert db.conn.execute("SELECT arrears FROM armies WHERE id=?", (aid,)).fetchone()[0] < 10


