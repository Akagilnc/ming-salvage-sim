"""地区城市等级/城防大炮 须出现在 region_report / region_detail 真实出口。

同军表漏火器一类病：字段进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：不锁中文展示串；经真实入口 + 可数哨兵/差分断言证明出口消费 DB 城防事实。
payload 字段契约见 test_region_citydefense.py。
"""

from __future__ import annotations

from ming_sim.qualitative import city_defense_description


def _city_region(db):
    return db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE city_level>0 LIMIT 1"
    ).fetchone()


def test_region_report_surfaces_cannon_count(game):
    """region_report 须把城防炮门数带进玩家可见出口（差分：门数变→出口变）。"""
    db, _, _ = game
    r = _city_region(db)
    # cannon<=city_level*8：level=2→cap16，5/11 合法
    db.conn.execute("UPDATE regions SET city_level=2, cannon=5 WHERE id=?", (r["id"],))
    db.conn.commit()
    rep_lo = db.region_report(limit=20)
    db.conn.execute("UPDATE regions SET cannon=11 WHERE id=?", (r["id"],))
    db.conn.commit()
    rep_hi = db.region_report(limit=20)
    assert rep_lo != rep_hi and "5" in rep_lo and "11" not in rep_lo
    assert "11" in rep_hi and r["name"] in rep_hi


def test_region_detail_surfaces_city_level_and_cannon(game):
    """region_detail 暴露等级/炮门；定性模式落 city_defense 枚举，夹具不越 cap。"""
    db, _, _ = game
    r = _city_region(db)
    level, cannon = 5, 37  # cap=40
    db.conn.execute(
        "UPDATE regions SET city_level=?, cannon=? WHERE id=?", (level, cannon, r["id"]),
    )
    db.conn.commit()
    det = db.region_detail(r["name"])
    assert r["name"] in det and str(level) in det and str(level * 8) in det
    assert str(cannon) in det

    fixed_cannon = 4  # 对 level 1/3/5 均合法
    details = {}
    for lv in (1, 3, 5):
        db.conn.execute(
            "UPDATE regions SET city_level=?, cannon=? WHERE id=?",
            (lv, fixed_cannon, r["id"]),
        )
        db.conn.commit()
        details[lv] = db.region_detail(r["name"], qualitative=True)
    assert details[1] != details[3] != details[5] and details[1] != details[5]
    for lv in (1, 3, 5):
        assert city_defense_description(lv) in details[lv]
