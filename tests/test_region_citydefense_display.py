"""地区城市等级/城防大炮 在 region_report 与 region_detail 里要显示。

同军表漏火器一类病：字段加进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：断言绑 region_public_payload（report/detail 唯一结构消费面）的
city_level / cannon / cannon_cap 与 0–5 离散等级边界；不锁中文展示串。
"""

from __future__ import annotations

import pytest


def _city_region(db):
    return db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE city_level>0 LIMIT 1"
    ).fetchone()


def _region_public_entry(db, region_id: str):
    """Slice of the sole public projection actually consumed by report/detail."""
    public = db.region_public_payload()
    return next(entry for entry in public["regions"] if entry["id"] == region_id)


def test_region_report_shows_city_defense(game):
    """region_report 出口消费的公共投影须带出 cannon 可数事实。"""
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=5 WHERE id=?", (r["id"],))
    db.conn.commit()

    # Same builder/args the report exit consumes.
    public = db.region_public_payload(limit=20, danger_order=True)
    entry = next(e for e in public["regions"] if e["id"] == r["id"])
    assert int(entry["city_level"]) > 0
    assert int(entry["cannon"]) == 5
    assert int(entry["cannon_cap"]) == int(entry["city_level"]) * 8

    rep = db.region_report(limit=20)
    assert isinstance(rep, str) and entry["name"] in rep


def test_region_detail_shows_city_level_and_cannon(game):
    """region_detail 出口消费的公共投影须带 city_level / cannon / cannon_cap。"""
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=6 WHERE id=?", (r["id"],))
    db.conn.commit()

    entry = _region_public_entry(db, r["id"])
    assert int(entry["cannon"]) == 6
    assert int(entry["city_level"]) == int(
        db.conn.execute(
            "SELECT city_level FROM regions WHERE id=?", (r["id"],)
        ).fetchone()["city_level"]
    )
    assert int(entry["cannon_cap"]) == int(entry["city_level"]) * 8

    det = db.region_detail(r["name"])
    assert isinstance(det, str) and entry["name"] in det


@pytest.mark.parametrize("level", (1, 3, 5))
def test_region_detail_uses_the_discrete_city_defense_scale(game, level):
    """离散 0–5 城防等级边界：投影 city_level 即结构枚举，detail 消费同一投影。"""
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute(
        "UPDATE regions SET city_level=? WHERE id=?", (level, region["id"])
    )
    db.conn.commit()

    entry = _region_public_entry(db, region["id"])
    assert int(entry["city_level"]) == level
    assert 0 <= int(entry["city_level"]) <= 5
    assert int(entry["cannon_cap"]) == level * 8

    detail = db.region_detail(region["name"], qualitative=True)
    assert isinstance(detail, str) and entry["name"] in detail
