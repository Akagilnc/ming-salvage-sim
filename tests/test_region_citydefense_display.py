"""地区城市等级/城防大炮 须出现在 region_report / region_detail 真实出口。

同军表漏火器一类病：字段进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：不锁中文展示串；经真实入口 + 可数哨兵/差分断言证明出口消费 DB 城防事实。
payload 字段契约见 test_region_citydefense.py。
"""

from __future__ import annotations

import ming_sim.db as dbmod
import ming_sim.qualitative as qualitative


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
    """region_detail 须暴露城市等级与城防炮门数（可数哨兵，非中文盯文）。"""
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


def test_region_detail_qualitative_city_defense_consumes_level(game, monkeypatch):
    """qualitative detail 须把 city_level 送进城防描述器（renderer 哨兵，无中文钉）。"""
    db, _, _ = game
    region = _city_region(db)
    seen: list[object] = []

    def _sentinel(value: object) -> str:
        seen.append(value)
        return f"CDEF_SENTINEL_{value}"

    monkeypatch.setattr(dbmod, "city_defense_description", _sentinel)
    monkeypatch.setattr(qualitative, "city_defense_description", _sentinel)

    for level in (1, 3, 5):
        seen.clear()
        db.conn.execute(
            "UPDATE regions SET city_level=? WHERE id=?", (level, region["id"])
        )
        db.conn.commit()
        detail = db.region_detail(region["name"], qualitative=True)
        assert seen == [level] or seen == [str(level)] or any(
            int(v) == level for v in seen if str(v).lstrip("-").isdigit()
        )
        assert f"CDEF_SENTINEL_{level}" in detail


def test_region_detail_does_not_clamp_out_of_range_city_level(game):
    """越界存量 city_level 在非定性 detail 读回不被静默截断。"""
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute(
        "UPDATE regions SET city_level=9 WHERE id=?", (region["id"],)
    )
    db.conn.commit()

    detail = db.region_detail(region["name"], qualitative=False)
    assert "9" in detail
    assert "72" in detail  # 9×8 上限仍按存量计算
