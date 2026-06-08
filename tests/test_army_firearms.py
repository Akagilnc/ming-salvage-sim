"""火器装备 / 大炮装备 两条军备轴（数据字段，供 simulator 软判，代码不硬算）。

火器装备：鸟铳/三眼铳——野战齐射 + 守城皆宜（0-100 状态轴）。
大炮装备：红夷炮——守城/攻城神器，笨重不利野战（随军门数，clamp 0-12；城防炮另挂 region.cannon）。
simulator 看得见、软性加权判战；引擎只 clamp、不算胜负。
"""

from __future__ import annotations

from ming_sim.constants import ARMY_SCORE_FIELDS


def _cols(db, table):
    return {r["name"] for r in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_score_fields_include_firearm_and_cannon():
    assert "firearm_equipment" in ARMY_SCORE_FIELDS
    assert "cannon_equipment" in ARMY_SCORE_FIELDS


def test_armies_table_has_firearm_columns(game):
    db, _, _ = game
    cols = _cols(db, "armies")
    assert "firearm_equipment" in cols
    assert "cannon_equipment" in cols


def test_new_army_defaults_zero_firearm(game):
    """新建军未指定火器/大炮时默认 0（列默认值 + 落库兜底）。
    注：开局存档各军火器/大炮已由玩法设定(全军30%)预填，故不再断言种子全 0，
    改测真正的不变式——没给值就落 0。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "plain_army_test", "name": "白杆兵测试", "owner_power": "ming",
        "manpower": 3000, "maintenance_per_turn": 1,
    }], actor="测试")
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id='plain_army_test'"
    ).fetchone()
    assert row["firearm_equipment"] == 0
    assert row["cannon_equipment"] == 0


def test_apply_army_delta_sets_firearm(game):
    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "配火器"})()
    db.apply_army_deltas(state, pseudo, None, "测试", {aid: {"firearm_equipment": 40, "cannon_equipment": 10}})
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert row["firearm_equipment"] == 40
    assert row["cannon_equipment"] == 10  # 随军炮 10 门(在 0-12 内)


def test_firearm_clamped_0_100(game):
    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "x"})()
    db.apply_army_deltas(state, pseudo, None, "测试", {aid: {"firearm_equipment": 999}})
    val = db.conn.execute("SELECT firearm_equipment FROM armies WHERE id=?", (aid,)).fetchone()[0]
    assert val == 100


def test_cannon_clamped_to_12(game):
    """部队随军大炮=红夷级门数，野战带不动几门，clamp 0-12（城防炮另挂 region）。"""
    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    pseudo = type("E", (), {"id": "test", "title": "x"})()
    db.apply_army_deltas(state, pseudo, None, "测试", {aid: {"cannon_equipment": 999}})
    val = db.conn.execute("SELECT cannon_equipment FROM armies WHERE id=?", (aid,)).fetchone()[0]
    assert val == 12


def test_create_army_with_firearm(game):
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "shenjiying_test", "name": "神机营测试", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": 2,
        "firearm_equipment": 70, "cannon_equipment": 12,
    }], actor="测试")
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id='shenjiying_test'"
    ).fetchone()
    assert row["firearm_equipment"] == 70
    assert row["cannon_equipment"] == 12  # 门数，12 门(在 0-12 上限内)


def test_create_army_cannon_count_clamped(game):
    """建军时给的大炮门数超 12 上限也截到 12。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "heavy_test", "name": "重炮营测试", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": 2, "cannon_equipment": 99,
    }], actor="测试")
    val = db.conn.execute("SELECT cannon_equipment FROM armies WHERE id='heavy_test'").fetchone()[0]
    assert val == 12


def test_extractor_prompts_allow_firearm_cannon_fields():
    """火器/随军大炮 必须进 extractor 军队字段白名单(shared + military prompt)，否则 simulator
    让 LLM 写、下一段 extractor 按旧闭合白名单自检 → 「配火器」叙事被吞成无 delta（codexB-P1，跨层 coverage）。"""
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "content", "prompts")
    for fn in ("score_extractor_shared.md", "score_extractor_military_external.md"):
        txt = open(os.path.join(base, fn), encoding="utf-8").read()
        assert "火器" in txt, f"{fn} 缺 火器 字段"
        assert "随军大炮" in txt, f"{fn} 缺 随军大炮 字段"


def test_apply_army_delta_chinese_keys(game):
    """extractor 按中文词干输出 火器/随军大炮 时也能落库（CMR F9 别名补全）。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "alias_test_army", "name": "别名测试军", "owner_power": "ming",
        "manpower": 3000, "maintenance_per_turn": 1,
    }], actor="测试")
    pseudo = type("E", (), {"id": "test", "title": "配火器"})()
    db.apply_army_deltas(state, pseudo, None, "测试",
                         {"alias_test_army": {"火器": 25, "随军大炮": 5}})
    row = db.conn.execute(
        "SELECT firearm_equipment, cannon_equipment FROM armies WHERE id='alias_test_army'"
    ).fetchone()
    assert row["firearm_equipment"] == 25
    assert row["cannon_equipment"] == 5


def test_simulator_payload_includes_firearm(game):
    """喂 simulator 的军表必须带火器/大炮列，否则 LLM 看不见、软判无从谈起。"""
    db, state, _ = game
    from ming_sim.simulation import build_simulator_payload
    payload = build_simulator_payload(state, db, "", "")
    armies = payload.get("armies") or {}
    cols = armies.get("cols") or []
    assert "firearm_equipment" in cols
    assert "cannon_equipment" in cols


def test_army_roster_shows_firearm_cannon(game):
    """大臣军表(army_roster)必须带火器/大炮——否则大臣（CLI 后端无工具）看不见、答不出。"""
    db, _, _ = game
    aid = db.conn.execute("SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    db.conn.execute(
        "UPDATE armies SET firearm_equipment=30, cannon_equipment=4 WHERE id=?", (aid,)
    )
    db.conn.commit()
    roster = db.army_roster()
    # 表头列名出现
    assert "火器" in roster
    assert "大炮" in roster
    # 该军那一行确实带上了 30 / 4 两个值
    name = db.conn.execute("SELECT name FROM armies WHERE id=?", (aid,)).fetchone()["name"]
    line = next(l for l in roster.splitlines() if l.startswith(name + "|"))
    cells = line.split("|")
    assert "30" in cells and "4" in cells
