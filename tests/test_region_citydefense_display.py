"""地区城市等级/城防大炮 在 region_report 与 region_detail 里要显示。

同军表漏火器一类病：字段加进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：断言改查 region 结构字段 city_level/cannon 与离散等级边界，不锁中文展示串。
"""

from __future__ import annotations

import pytest

from ming_sim.qualitative import city_defense_description

# 离散城防 0–5 等级枚举（与 city_defense_description 同源契约）
_CITY_DEFENSE_SCALE = ("初设", "简陋", "成形", "坚固", "重镇", "雄城")


def _city_region(db):
    return db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE city_level>0 LIMIT 1"
    ).fetchone()


def test_region_report_shows_city_defense(game):
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=5 WHERE id=?", (r["id"],))
    db.conn.commit()

    row = db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE id=?", (r["id"],)
    ).fetchone()
    assert int(row["city_level"]) > 0
    assert int(row["cannon"]) == 5

    # display 路径仍带出结构化 cannon 可数事实（不锁「城防炮N门」文案）
    rep = db.region_report(limit=20)
    assert row["name"] in rep
    assert str(int(row["cannon"])) in rep


def test_region_detail_shows_city_level_and_cannon(game):
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=6 WHERE id=?", (r["id"],))
    db.conn.commit()

    row = db.conn.execute(
        "SELECT name, city_level, cannon FROM regions WHERE id=?", (r["id"],)
    ).fetchone()
    assert int(row["cannon"]) == 6
    cap = int(row["city_level"]) * 8

    det = db.region_detail(r["name"])
    # detail 出口带出 city_level / cannon / 上限结构事实
    assert str(int(row["city_level"])) in det
    assert str(int(row["cannon"])) in det
    assert str(cap) in det


@pytest.mark.parametrize("level", (1, 3, 5))
def test_region_detail_uses_the_discrete_city_defense_scale(game, level):
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute("UPDATE regions SET city_level=? WHERE id=?", (level, region["id"]))
    db.conn.commit()

    row = db.conn.execute(
        "SELECT city_level FROM regions WHERE id=?", (region["id"],)
    ).fetchone()
    assert int(row["city_level"]) == level
    assert 0 <= int(row["city_level"]) <= 5

    # 离散等级 → 结构枚举边界；detail 消费同一枚举，不锁散文模板
    band = _CITY_DEFENSE_SCALE[level]
    assert city_defense_description(level) == band
    detail = db.region_detail(region["name"], qualitative=True)
    assert band in detail
