"""火器装备 / 大炮装备 两条军备轴（数据字段，供 simulator 软判，代码不硬算）。

火器装备：鸟铳/三眼铳——野战齐射 + 守城皆宜（0-100 状态轴）。
大炮装备：红夷炮——守城/攻城神器，笨重不利野战（随军门数，clamp 0-12；城防炮另挂 region.cannon）。
simulator 看得见、软性加权判战；引擎只 clamp、不算胜负。

#1185 显示面：真实出口可数哨兵/双态差分；同 seam 合并为最短 tracer。
"""

from __future__ import annotations

import re

from ming_sim.constants import ARMY_SCORE_FIELDS


def _pay_source():
    return {
        "pay_source_region": "shaanxi",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }


def _cols(db, table):
    return {r["name"] for r in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_score_fields_include_firearm_and_cannon():
    assert "firearm_equipment" in ARMY_SCORE_FIELDS
    assert "cannon_equipment" in ARMY_SCORE_FIELDS


def test_armies_table_has_firearm_columns(read_game):
    db, _, _ = read_game
    cols = _cols(db, "armies")
    assert "firearm_equipment" in cols
    assert "cannon_equipment" in cols


def test_new_army_defaults_zero_firearm(game):
    """新建军未指定火器/大炮时默认 0（列默认值 + 落库兜底）。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "plain_army_test", "name": "白杆兵测试", "owner_power": "ming",
        "manpower": 3000, "maintenance_per_turn": 1, **_pay_source(),
    }], actor="测试")
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id='plain_army_test'"
    ).fetchone()
    assert row["firearm_equipment"] == 0
    assert row["cannon_equipment"] == 0


def test_apply_army_delta_sets_firearm(saved_game):
    db, state, _ = saved_game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "配火器"})()
    db.apply_army_deltas(
        state, pseudo, None, "测试",
        {aid: {"firearm_equipment": 40, "cannon_equipment": 10}},
    )
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert row["firearm_equipment"] == 40
    assert row["cannon_equipment"] == 10


def test_firearm_clamped_0_100(game):
    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "x"})()
    db.apply_army_deltas(state, pseudo, None, "测试", {aid: {"firearm_equipment": 999}})
    val = db.conn.execute(
        "SELECT firearm_equipment FROM armies WHERE id=?", (aid,)
    ).fetchone()[0]
    assert val == 100


def test_cannon_clamped_to_12(game):
    """部队随军大炮 clamp 0-12。"""
    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "x"})()
    db.apply_army_deltas(state, pseudo, None, "测试", {aid: {"cannon_equipment": 999}})
    val = db.conn.execute(
        "SELECT cannon_equipment FROM armies WHERE id=?", (aid,)
    ).fetchone()[0]
    assert val == 12


def test_create_army_with_firearm(game):
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "shenjiying_test", "name": "神机营测试", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": 2,
        "firearm_equipment": 70, "cannon_equipment": 12, **_pay_source(),
    }], actor="测试")
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id='shenjiying_test'"
    ).fetchone()
    assert row["firearm_equipment"] == 70
    assert row["cannon_equipment"] == 12


def test_create_army_cannon_count_clamped(game):
    """建军时大炮门数超 12 上限也截到 12。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "heavy_test", "name": "重炮营测试", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": 2, "cannon_equipment": 99,
        **_pay_source(),
    }], actor="测试")
    val = db.conn.execute(
        "SELECT cannon_equipment FROM armies WHERE id='heavy_test'"
    ).fetchone()[0]
    assert val == 12


def test_army_public_exits_surface_firearm_and_cannon(game):
    """detail/report/roster 同一读侧：可数火器/炮门 + roster 双态差分（无内部 renderer patch）。"""
    db, state, _ = game
    row = db.conn.execute(
        "SELECT id, name FROM armies WHERE owner_power='ming' LIMIT 1"
    ).fetchone()
    aid, name = row["id"], row["name"]

    def _set(**fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        db.conn.execute(f"UPDATE armies SET {cols} WHERE id=?", (*fields.values(), aid))
        db.conn.commit()

    def _report_seg() -> str:
        body = db.army_report(limit=8).split("：", 1)[-1]
        return next(p for p in body.split("；") if p.startswith(name + "："))

    def _roster_line(*, qualitative: bool) -> str:
        return next(
            line for line in db.army_roster(
                filter_names=[name], qualitative_equipment=qualitative
            ).splitlines()
            if line.startswith(name + "|")
        )

    _set(firearm_equipment=45, cannon_equipment=3)
    detail = db.army_detail(name)
    assert "45" in detail and "3" in detail
    _set(firearm_equipment=91, cannon_equipment=7)
    detail_hi = db.army_detail(name)
    assert detail != detail_hi and "91" in detail_hi and "7" in detail_hi and "91" not in detail

    # report：抬危入榜；固定火器只改炮数；截取目标军行核对炮门可数事实
    _set(firearm_equipment=45, cannon_equipment=11, supply=1, morale=1, loyalty=1, training=1)
    seg_a = _report_seg()
    assert re.search(r"(?<!\d)11(?!\d)", seg_a)
    _set(cannon_equipment=8)  # 火器不变
    seg_b = _report_seg()
    assert re.search(r"(?<!\d)8(?!\d)", seg_b)
    assert not re.search(r"(?<!\d)11(?!\d)", seg_b) and seg_a != seg_b

    _set(firearm_equipment=30, cannon_equipment=4)
    cells_num = _roster_line(qualitative=False).split("|")
    cells_q = _roster_line(qualitative=True).split("|")
    assert cells_num[-2] == "30" and cells_num[-1] == "4"
    assert cells_q[-2] != "30" and "30" not in cells_q and cells_q[-1] == "4"

    db.create_armies_from_extraction(state, [{
        "id": "probe_fire_new", "name": "火器新营", "owner_power": "ming",
        "manpower": 4000, "maintenance_per_turn": 1,
        "firearm_equipment": 77, "cannon_equipment": 5, **_pay_source(),
    }], actor="测试")
    for key in ("probe_fire_new", "火器新营"):
        d = db.army_detail(key)
        assert "77" in d and "5" in d


def test_fresh_seed_wires_firearm_not_all_zero(content):
    """新档 seed 必须贯通火器（非全 0）。"""
    import os
    import tempfile
    from ming_sim.db import GameDB

    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = GameDB(p, content)
        db.seed_static_data()
        rows = db.conn.execute("SELECT firearm_equipment FROM armies").fetchall()
        assert rows
        assert any(int(r["firearm_equipment"]) > 0 for r in rows)
        db.conn.close()
    finally:
        for f in (p, f"{p}_agno.db"):
            if os.path.exists(f):
                os.remove(f)


def test_create_army_cannon_nonint_rejected_not_crash(read_game):
    """建军 cannon_equipment 非 int → 逐项拒收，不崩不静默 0。"""
    db, state, _ = read_game
    created = db.create_armies_from_extraction(state, [{
        "id": "cannon_nonint_test", "name": "炮非数测试", "owner_power": "ming",
        "manpower": 2000, "maintenance_per_turn": 1, "cannon_equipment": "几门",
        **_pay_source(),
    }], actor="测试")
    assert db.conn.execute(
        "SELECT COUNT(*) FROM armies WHERE id='cannon_nonint_test'"
    ).fetchone()[0] == 0
    rej = [c for c in created if c.get("rejected")]
    assert len(rej) == 1 and rej[0]["category"] == "invalid_enum"


def test_apply_army_delta_chinese_keys(game):
    """extractor 中文词干 火器/随军大炮 也能落库。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "alias_test_army", "name": "别名测试军", "owner_power": "ming",
        "manpower": 3000, "maintenance_per_turn": 1, **_pay_source(),
    }], actor="测试")
    pseudo = type("E", (), {"id": "test", "title": "配火器"})()
    db.apply_army_deltas(
        state, pseudo, None, "测试",
        {"alias_test_army": {"火器": 25, "随军大炮": 5}},
    )
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id='alias_test_army'"
    ).fetchone()
    assert row["firearm_equipment"] == 25
    assert row["cannon_equipment"] == 5


def test_simulator_payload_includes_firearm(read_game):
    """喂 simulator 的军表必须带火器/大炮列。"""
    db, state, _ = read_game
    from ming_sim.simulation import build_simulator_payload

    payload = build_simulator_payload(state, db, "", "")
    armies = payload.get("armies") or {}
    cols = armies.get("cols") or []
    assert "firearm_equipment" in cols
    assert "cannon_equipment" in cols
