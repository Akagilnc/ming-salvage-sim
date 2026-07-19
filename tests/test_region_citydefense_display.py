"""地区城市等级/城防大炮 在 region_report 与 region_detail 里要显示。

同军表漏火器一类病：字段加进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。
"""

from __future__ import annotations

import pytest


def _city_region(db):
    return db.conn.execute("SELECT id, name FROM regions WHERE city_level>0 LIMIT 1").fetchone()


def test_region_report_shows_city_defense(game):
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=5 WHERE id=?", (r["id"],))
    db.conn.commit()
    rep = db.region_report(limit=20)
    assert "城防炮5门" in rep            # 危情概览带上城防大炮


def test_region_detail_shows_city_level_and_cannon(game):
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=6 WHERE id=?", (r["id"],))
    db.conn.commit()
    det = db.region_detail(r["name"])
    assert "城市等级" in det              # 详情带城市等级
    assert "城防大炮6门" in det           # 带城防大炮门数


@pytest.mark.parametrize(
    ("level", "label"),
    ((1, "简陋"), (3, "坚固"), (5, "雄城")),
)
def test_region_detail_uses_the_discrete_city_defense_scale(game, level, label):
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute("UPDATE regions SET city_level=? WHERE id=?", (level, region["id"]))
    db.conn.commit()

    detail = db.region_detail(region["name"], qualitative=True)

    assert f"城防{label}" in detail
