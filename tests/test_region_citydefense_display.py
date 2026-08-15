"""地区城市等级/城防大炮 须出现在 region_report / region_detail 真实出口。

同军表漏火器一类病：字段进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：不锁中文展示串；经真实入口 + 可数哨兵/差分断言证明出口消费 DB 城防事实。
payload 字段契约见 test_region_citydefense.py。
"""

from __future__ import annotations


def _city_region(db):
    return db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE city_level>0 LIMIT 1"
    ).fetchone()


def test_region_report_surfaces_cannon_count(game):
    """region_report 须把城防炮门数带进玩家可见出口（差分：门数变→出口变）。"""
    db, _, _ = game
    r = _city_region(db)

    db.conn.execute("UPDATE regions SET cannon=5 WHERE id=?", (r["id"],))
    db.conn.commit()
    rep_lo = db.region_report(limit=20)

    db.conn.execute("UPDATE regions SET cannon=11 WHERE id=?", (r["id"],))
    db.conn.commit()
    rep_hi = db.region_report(limit=20)

    assert rep_lo != rep_hi
    assert "5" in rep_lo and "11" not in rep_lo
    assert "11" in rep_hi
    assert r["name"] in rep_hi


def test_region_detail_surfaces_city_level_and_cannon(game):
    """region_detail 须暴露城市等级与城防炮门数；定性模式消费 city_level 差分。"""
    db, _, _ = game
    r = _city_region(db)
    stored_level = int(
        db.conn.execute(
            "SELECT city_level FROM regions WHERE id=?", (r["id"],)
        ).fetchone()["city_level"]
    )
    sentinel_cannon = 817263
    db.conn.execute(
        "UPDATE regions SET cannon=? WHERE id=?", (sentinel_cannon, r["id"])
    )
    db.conn.commit()

    det = db.region_detail(r["name"])
    assert r["name"] in det
    assert str(stored_level) in det
    assert str(stored_level * 8) in det  # 城防炮上限 = city_level×8
    assert str(sentinel_cannon) in det

    # qualitative：等级差分可判别（不 patch 内部 city_defense_description）
    details = {}
    for level in (1, 3, 5):
        db.conn.execute(
            "UPDATE regions SET city_level=? WHERE id=?", (level, r["id"])
        )
        db.conn.commit()
        details[level] = db.region_detail(r["name"], qualitative=True)
    assert details[1] != details[3] != details[5]
    assert details[1] != details[5]
