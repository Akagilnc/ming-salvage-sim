"""火器装备 / 大炮装备 两条军备轴（数据字段，供 simulator 软判，代码不硬算）。

火器装备：鸟铳/三眼铳——野战齐射 + 守城皆宜（0-100 状态轴）。
大炮装备：红夷炮——守城/攻城神器，笨重不利野战（随军门数，clamp 0-12；城防炮另挂 region.cannon）。
simulator 看得见、软性加权判战；引擎只 clamp、不算胜负。
"""

from __future__ import annotations

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
    """新建军未指定火器/大炮时默认 0（列默认值 + 落库兜底）。
    注：开局存档各军火器/大炮已由玩法设定(全军30%)预填，故不再断言种子全 0，
    改测真正的不变式——没给值就落 0。"""
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
    db, state, _ = saved_game  # saved_game：断言依赖玩过存档的特定 army 火器基线（#5）
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
        "firearm_equipment": 70, "cannon_equipment": 12, **_pay_source(),
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
        **_pay_source(),
    }], actor="测试")
    val = db.conn.execute("SELECT cannon_equipment FROM armies WHERE id='heavy_test'").fetchone()[0]
    assert val == 12


def test_army_numeric_fields_synced_across_prompts():
    """治本（CMR codexA/B 火器 coverage-drift）：军队数值字段以 constants 为唯一源，
    extractor 两 prompt 必须全含其中文标签、enrich prompt 至少含军备两轴。
    标签从 ARMY_SCORE_FIELDS/ARMY_FIELD_LABELS 派生 —— 将来加字段本测试立挂，
    不再每轮 cross-model review 揪一处没同步的 prompt（杀 whack-a-mole）。"""
    import os
    import inspect
    from ming_sim.constants import ARMY_SCORE_FIELDS, ARMY_FIELD_LABELS
    base = os.path.join(os.path.dirname(__file__), "..", "content", "prompts")
    shared = open(os.path.join(base, "score_extractor_shared.md"), encoding="utf-8").read()
    military = open(os.path.join(base, "score_extractor_military_external.md"), encoding="utf-8").read()
    # extractor 可写数值轴 = score 字段去 arrears（欠饷由 flows 唯一变更，prompt 严禁写）
    full = [ARMY_FIELD_LABELS[f] for f in ARMY_SCORE_FIELDS if f != "arrears"]
    for label in full:
        assert label in shared, f"score_extractor_shared.md 缺军队数值字段「{label}」(constants 已定义)"
        assert label in military, f"score_extractor_military_external.md 缺军队数值字段「{label}」(constants 已定义)"
    # enrich 内联 prompt（数值结算设计器）至少含军备两轴，新军/扩编可武装
    import ming_sim.cli_backend as _cb
    enrich_src = inspect.getsource(_cb.enrich_initiative_effects)
    for f in ("firearm_equipment", "cannon_equipment"):
        assert ARMY_FIELD_LABELS[f] in enrich_src, f"enrich prompt 缺军备轴「{ARMY_FIELD_LABELS[f]}」"


def test_army_detail_shows_firearm_cannon(game):
    """army_detail(大臣 inspect_army 走它)必须显示火器/随军大炮数值——否则 tool-call 大臣查军详情
    看不到军备两轴，火器 read 侧不闭环(CMR codexB read-surface)。"""
    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    db.conn.execute("UPDATE armies SET firearm_equipment=45, cannon_equipment=3 WHERE id=?", (aid,))
    db.conn.commit()
    name = db.conn.execute("SELECT name FROM armies WHERE id=?", (aid,)).fetchone()["name"]
    detail = db.army_detail(name)
    assert "火器45" in detail
    assert "随军大炮3" in detail


def test_army_report_shows_firearm_and_cannon(game):
    """army_report(list_armies 警讯)带火器 + 随军大炮(炮)，read 摘要面闭环（CMR codexC）。"""
    db, _, _ = game
    rpt = db.army_report(limit=8)
    assert "火器" in rpt
    assert "炮" in rpt


def test_army_detail_dynamic_new_army_shows_firearm(game):
    """动态 new_armies 建的军(不在静态 content.armies)按 id/name 查 army_detail 也能查到 + 显火器/炮。
    旧码 army_detail 用静态 matcher → 动态军 ValueError;改 DB 直查后 read 闭合（CMR codexB/C 架构 unify）。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "probe_fire_new", "name": "火器新营", "owner_power": "ming",
        "manpower": 4000, "maintenance_per_turn": 1,
        "firearm_equipment": 77, "cannon_equipment": 5, **_pay_source(),
    }], actor="测试")
    for key in ("probe_fire_new", "火器新营"):     # id 和 name 都能查到
        detail = db.army_detail(key)
        assert "火器77" in detail, key
        assert "随军大炮5" in detail, key


def test_game_world_prompt_lists_firearm_cannon():
    """全局 game_world 军队字段表含火器/随军大炮(大臣据此知军备轴，CMR codexB)。"""
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "content", "prompts", "game_world.md")
    txt = open(p, encoding="utf-8").read()
    assert "火器" in txt and "随军大炮" in txt


def test_fresh_seed_wires_firearm_not_all_zero(content):
    """新档 seed（非 data/probe.db 老档副本）必须贯通火器：armies.json 缺省由 loader 给基线、
    fresh seed INSERT 写两列。曾全 0 被 probe.db fixture 掩盖（CMR codexB-P1）。"""
    import os
    import tempfile
    from ming_sim.db import GameDB
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = GameDB(p, content)
        db.seed_static_data()                     # 真实新档路径
        rows = db.conn.execute("SELECT firearm_equipment FROM armies").fetchall()
        assert rows                               # 新档有军队
        assert any(int(r["firearm_equipment"]) > 0 for r in rows)   # 火器非全 0 = 已贯通
        db.conn.close()
    finally:
        for f in (p, f"{p}_agno.db"):
            if os.path.exists(f):
                os.remove(f)


def test_create_army_cannon_nonint_rejected_not_crash(game):
    """建军时 cannon_equipment 给非 int(如"几门")→ 逐项拒收留痕,不抛崩也不再
    静默兜底 0（旧语义被 cmr S2 r1「在场即须合法」取代——静默 0=伪造军备）。"""
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "cannon_nonint_test", "name": "炮非数测试", "owner_power": "ming",
        "manpower": 2000, "maintenance_per_turn": 1, "cannon_equipment": "几门",
        **_pay_source(),
    }], actor="测试")
    assert db.conn.execute(
        "SELECT COUNT(*) FROM armies WHERE id='cannon_nonint_test'").fetchone()[0] == 0
    rej = [c for c in created if c.get("rejected")]
    assert len(rej) == 1 and rej[0]["category"] == "invalid_enum"


def test_apply_army_delta_chinese_keys(game):
    """extractor 按中文词干输出 火器/随军大炮 时也能落库（CMR F9 别名补全）。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "alias_test_army", "name": "别名测试军", "owner_power": "ming",
        "manpower": 3000, "maintenance_per_turn": 1, **_pay_source(),
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
