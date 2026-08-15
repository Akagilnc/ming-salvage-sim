"""地区城市等级/城防大炮 在 region_report 与 region_detail 里要显示。

同军表漏火器一类病：字段加进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：外部契约是文本时，用局部语义单元绑定数值归属（标签+单位），
不用裸数字子串，也不用生产私有映射算 expected。
"""

from __future__ import annotations

import pytest


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
    assert int(row["cannon"]) == 5

    rep = db.region_report(limit=20)
    assert row["name"] in rep
    # 语义单元：门数归属「城防炮…门」，标签/单位错位须失败
    assert f"城防炮{int(row['cannon'])}门" in rep


def test_region_detail_shows_city_level_and_cannon(game):
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=6 WHERE id=?", (r["id"],))
    db.conn.commit()

    row = db.conn.execute(
        "SELECT name, city_level, cannon FROM regions WHERE id=?", (r["id"],)
    ).fetchone()
    level = int(row["city_level"])
    cannon = int(row["cannon"])
    assert cannon == 6
    cap = level * 8

    det = db.region_detail(r["name"])
    # 各数值绑定各自语义标签；互换归属须失败
    assert f"城市等级{level}" in det
    assert f"城防炮上限{cap}门" in det
    assert f"城防大炮{cannon}门" in det


@pytest.mark.parametrize(
    ("level", "label"),
    ((1, "简陋"), (3, "坚固"), (5, "雄城")),
)
def test_region_detail_uses_the_discrete_city_defense_scale(game, level, label):
    """独立显式样例：离散等级 → 定性标签；不调用生产 city_defense_description。"""
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute("UPDATE regions SET city_level=? WHERE id=?", (level, region["id"]))
    db.conn.commit()

    row = db.conn.execute(
        "SELECT city_level FROM regions WHERE id=?", (region["id"],)
    ).fetchone()
    assert int(row["city_level"]) == level

    detail = db.region_detail(region["name"], qualitative=True)
    assert f"城防{label}" in detail
