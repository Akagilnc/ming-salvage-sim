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


def test_army_detail_shows_firearm_cannon(game, monkeypatch):
    """army_detail 经 public 投影：火器为定性 band，随军大炮为可数门数（P4/#1185）。"""
    import copy

    import ming_sim.db as dbmod

    db, state, _ = game
    aid = db.conn.execute("SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    db.conn.execute("UPDATE armies SET firearm_equipment=45, cannon_equipment=3 WHERE id=?", (aid,))
    db.conn.commit()
    name = db.conn.execute("SELECT name FROM armies WHERE id=?", (aid,)).fetchone()["name"]
    entry = next(a for a in db.army_public_payload()["armies"] if a["id"] == aid)
    assert entry["firearm_equipment_band"] == "unstable"  # 45 → mid band
    assert int(entry["cannon_equipment"]) == 3
    assert "firearm_equipment" not in entry

    # Non-copy renderer sentinel: prove band consumption without Chinese pins.
    monkeypatch.setattr(
        dbmod, "_army_stat_label", lambda field, band: f"XBAND_{field}_{band}"
    )

    calls = []
    original = db.army_public_payload

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        out = {
            "armies": [dict(a) for a in result["armies"]],
            "monthly_pay_total": result.get("monthly_pay_total", 0),
            "manpower_total": result.get("manpower_total", 0),
        }
        for a in out["armies"]:
            if a["id"] == aid:
                a["cannon_equipment"] = 777
                a["name"] = f"ZTRACE_{a['name']}"
                a["firearm_equipment_band"] = "critical"
        calls.append({"kwargs": dict(kwargs), "result": copy.deepcopy(out)})
        return out

    monkeypatch.setattr(db, "army_public_payload", wrapper)
    detail = db.army_detail(name)
    assert len(calls) == 1, "army_detail must call army_public_payload"
    assert calls[0]["kwargs"].get("rows") is not None
    traced = calls[0]["result"]["armies"][0]
    assert traced["name"] in detail
    assert "777" in detail  # cannon_equipment consumed from projection
    assert "XBAND_equipment_critical" in detail  # firearm band via renderer sentinel
    assert "45" not in detail


def test_army_report_shows_firearm_and_cannon(read_game, monkeypatch):
    """army_report 必须调用 army_public_payload 并消费火器 band + 炮门数。"""
    import copy

    import ming_sim.db as dbmod

    db, _, _ = read_game
    # Pick one army present in danger-ordered report window.
    sample = db.army_rows(limit=8, danger_order=True)
    assert sample
    target_id = sample[0]["id"]

    monkeypatch.setattr(
        dbmod, "_army_stat_label", lambda field, band: f"XBAND_{field}_{band}"
    )

    calls = []
    original = db.army_public_payload

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        out = {
            "armies": [dict(a) for a in result["armies"]],
            "monthly_pay_total": result.get("monthly_pay_total", 0),
            "manpower_total": result.get("manpower_total", 0),
        }
        for a in out["armies"]:
            if a["id"] == target_id:
                a["name"] = f"ZTRACE_{a['name']}"
                a["cannon_equipment"] = 666
                a["firearm_equipment_band"] = "critical"
        calls.append({"kwargs": dict(kwargs), "result": copy.deepcopy(out)})
        return out

    monkeypatch.setattr(db, "army_public_payload", wrapper)
    rpt = db.army_report(limit=8)
    assert len(calls) == 1, "army_report must call army_public_payload"
    traced = next(a for a in calls[0]["result"]["armies"] if a["id"] == target_id)
    assert traced["name"] in rpt
    assert "XBAND_equipment_critical" in rpt  # firearm band via renderer sentinel
    assert "炮666门" in rpt


def test_army_detail_dynamic_new_army_shows_firearm(game):
    """动态 new_armies 建的军(不在静态 content.armies)按 id/name 查 army_detail 也能查到 + 显火器/炮。
    旧码 army_detail 用静态 matcher → 动态军 ValueError;改 DB 直查后 read 闭合（CMR codexB/C 架构 unify）。"""
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "probe_fire_new", "name": "火器新营", "owner_power": "ming",
        "manpower": 4000, "maintenance_per_turn": 1,
        "firearm_equipment": 77, "cannon_equipment": 5, **_pay_source(),
    }], actor="测试")
    entry = next(a for a in db.army_public_payload()["armies"] if a["id"] == "probe_fire_new")
    assert entry["firearm_equipment_band"] == "steady"  # 77 → steady band
    assert int(entry["cannon_equipment"]) == 5
    for key in ("probe_fire_new", "火器新营"):     # id 和 name 都能查到
        detail = db.army_detail(key)
        assert "火器" in detail, key
        assert "77" not in detail, key
        assert "随军大炮5" in detail, key


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


def test_create_army_cannon_nonint_rejected_not_crash(read_game):
    """建军时 cannon_equipment 给非 int(如"几门")→ 逐项拒收留痕,不抛崩也不再
    静默兜底 0（旧语义被 cmr S2 r1「在场即须合法」取代——静默 0=伪造军备）。"""
    db, state, _ = read_game
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


def test_simulator_payload_includes_firearm(read_game):
    """喂 simulator 的军表必须带火器/大炮列，否则 LLM 看不见、软判无从谈起。"""
    db, state, _ = read_game
    from ming_sim.simulation import build_simulator_payload
    payload = build_simulator_payload(state, db, "", "")
    armies = payload.get("armies") or {}
    cols = armies.get("cols") or []
    assert "firearm_equipment" in cols
    assert "cannon_equipment" in cols


def test_army_roster_shows_firearm_cannon(game, monkeypatch):
    """army_roster 双态：False=原数值火器；True=投影 band 定性；均消费同一投影。"""
    import copy

    import ming_sim.db as dbmod

    db, _, _ = game
    aid = db.conn.execute("SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"]
    db.conn.execute(
        "UPDATE armies SET firearm_equipment=30, cannon_equipment=4 WHERE id=?", (aid,)
    )
    db.conn.commit()
    entry = next(a for a in db.army_public_payload()["armies"] if a["id"] == aid)
    assert entry["firearm_equipment_band"] == "wavering"  # 30 → low band
    assert int(entry["cannon_equipment"]) == 4
    assert "firearm_equipment" not in entry
    name = db.conn.execute("SELECT name FROM armies WHERE id=?", (aid,)).fetchone()["name"]

    # Default False: numeric firearm cell (base dual-state), still via public projection.
    calls_num = []
    original = db.army_public_payload

    def wrap_num(*args, **kwargs):
        result = original(*args, **kwargs)
        out = {
            "armies": [dict(a) for a in result["armies"]],
            "monthly_pay_total": result.get("monthly_pay_total", 0),
            "manpower_total": result.get("manpower_total", 0),
        }
        for a in out["armies"]:
            if a["id"] == aid:
                a["name"] = f"ZTRACE_{a['name']}"
                a["cannon_equipment"] = 888
        calls_num.append({"kwargs": dict(kwargs), "result": copy.deepcopy(out)})
        return out

    monkeypatch.setattr(db, "army_public_payload", wrap_num)
    roster = db.army_roster(filter_names=[name])
    assert len(calls_num) == 1, "army_roster must call army_public_payload"
    assert calls_num[0]["kwargs"].get("rows") is not None
    traced_name = next(
        a["name"] for a in calls_num[0]["result"]["armies"] if a["id"] == aid
    )
    assert "火器" in roster and "大炮" in roster
    line = next(l for l in roster.splitlines() if l.startswith(traced_name + "|"))
    cells = line.split("|")
    assert "30" in cells  # False path: raw firearm count
    # Dual-state False: firearm column is the bare numeric cell (last-but-one).
    assert cells[-2] == "30"
    assert "888" in cells  # cannon_equipment consumed from projection

    # True: qualitative firearm from projection band (minister tool path).
    # Renderer sentinel replaces free Chinese so exit proves band id propagation.
    monkeypatch.undo()
    monkeypatch.setattr(
        dbmod, "_army_stat_label", lambda field, band: f"XBAND_{field}_{band}"
    )
    calls_q = []

    def wrap_q(*args, **kwargs):
        result = original(*args, **kwargs)
        out = {
            "armies": [dict(a) for a in result["armies"]],
            "monthly_pay_total": result.get("monthly_pay_total", 0),
            "manpower_total": result.get("manpower_total", 0),
        }
        for a in out["armies"]:
            if a["id"] == aid:
                a["name"] = f"QTRACE_{a['name']}"
                a["firearm_equipment_band"] = "critical"
                a["cannon_equipment"] = 4
        calls_q.append({"kwargs": dict(kwargs), "result": copy.deepcopy(out)})
        return out

    monkeypatch.setattr(db, "army_public_payload", wrap_q)
    roster_q = db.army_roster(filter_names=[name], qualitative_equipment=True)
    assert len(calls_q) == 1
    q_name = next(a["name"] for a in calls_q[0]["result"]["armies"] if a["id"] == aid)
    q_line = next(l for l in roster_q.splitlines() if l.startswith(q_name + "|"))
    q_cells = q_line.split("|")
    # True path firearm cell carries band sentinel (not raw score).
    assert any("XBAND_equipment_critical" in c for c in q_cells)
    assert q_cells[-2] != "30"
    assert "30" not in q_cells
    assert "4" in q_cells
