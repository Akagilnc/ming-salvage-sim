"""城市等级(city_level 0-5) + 城防大炮(城头红夷炮门数, 上限 city_level×8)。

city_level：静态结构属性(改一级需五年十年，暂不做变更机制)，按史实分级——
首都5、江南/陪都/后金都城/朝鲜日本4、四聚海贸3、中等省2、边远1、游牧孤岛0。
将来也供经济/内政用。城防炮门数挂 region(地区=城池暂不分)，上限 = city_level×8。
"""

from __future__ import annotations


def _region_cols(db):
    return {r["name"] for r in db.conn.execute("PRAGMA table_info(regions)").fetchall()}


def test_regions_have_city_level_and_cannon(read_game):
    db, _, _ = read_game
    cols = _region_cols(db)
    assert "city_level" in cols
    assert "cannon" in cols


def test_city_level_tiers_by_history(read_game):
    db, _, _ = read_game

    def lv(rid):
        return db.conn.execute("SELECT city_level FROM regions WHERE id=?", (rid,)).fetchone()[0]

    assert lv("beizhili") == 5            # 京师
    assert lv("nanzhili") == 4            # 陪都/江南
    assert lv("zhejiang") == 4            # 江南
    assert lv("shenyang_liaoyang") == 4   # 后金盛京
    assert lv("huguang") == 3             # 汉口(四聚)
    assert lv("shaanxi") == 2             # 西安,旱灾衰(不是1也不是3)
    assert lv("liaodong") == 2            # 宁锦设防
    assert lv("yunnan") == 1              # 边远
    assert lv("dongjiang_area") == 0      # 皮岛孤悬
    assert lv("mongol_chahar") == 0       # 游牧


def test_region_cannon_cap_by_city_level(game):
    """城防炮上限 = city_level×8：北直隶(5)封顶 40，陕西(2)封顶 16。"""
    db, state, _ = game
    db.apply_region_cannon(state, "beizhili", 999)
    assert db.conn.execute("SELECT cannon FROM regions WHERE id='beizhili'").fetchone()[0] == 40
    db.apply_region_cannon(state, "shaanxi", 999)
    assert db.conn.execute("SELECT cannon FROM regions WHERE id='shaanxi'").fetchone()[0] == 16


def test_region_cannon_level0_caps_zero(game):
    """level 0 的地方(游牧/孤岛)城防炮上限 0。"""
    db, state, _ = game
    db.apply_region_cannon(state, "mongol_chahar", 50)
    assert db.conn.execute("SELECT cannon FROM regions WHERE id='mongol_chahar'").fetchone()[0] == 0


def test_simulator_payload_includes_region_defense(read_game):
    db, state, _ = read_game
    from ming_sim.simulation import build_simulator_payload
    payload = build_simulator_payload(state, db, "", "")
    cols = (payload.get("regions") or {}).get("cols") or []
    assert "city_level" in cols
    assert "cannon" in cols
