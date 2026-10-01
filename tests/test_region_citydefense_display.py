"""DB 城防事实到现役读侧出口的接线，不锁数字格式。"""

from ming_sim.qualitative import city_defense_description


def _city_region(db):
    return db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE city_level>0 LIMIT 1"
    ).fetchone()


def test_region_report_surfaces_cannon_count(game):
    db, _, _ = game
    row = _city_region(db)
    db.conn.execute("UPDATE regions SET city_level=2, cannon=5 WHERE id=?", (row["id"],))
    db.conn.commit()
    before = db.region_report(limit=20)
    db.conn.execute("UPDATE regions SET cannon=11 WHERE id=?", (row["id"],))
    db.conn.commit()
    assert db.region_report(limit=20) != before


def test_region_detail_surfaces_city_level_and_cannon(game):
    db, _, _ = game
    row = _city_region(db)
    db.conn.execute("UPDATE regions SET city_level=5, cannon=4 WHERE id=?", (row["id"],))
    db.conn.commit()
    before = db.region_detail(row["name"])
    db.conn.execute("UPDATE regions SET cannon=37 WHERE id=?", (row["id"],))
    db.conn.commit()
    assert db.region_detail(row["name"]) != before

    details = {}
    for level in (1, 3, 5):
        db.conn.execute(
            "UPDATE regions SET city_level=?, cannon=4 WHERE id=?", (level, row["id"])
        )
        db.conn.commit()
        details[level] = db.region_detail(row["name"], qualitative=True)
        assert city_defense_description(level) in details[level]
    assert len(set(details.values())) == 3
