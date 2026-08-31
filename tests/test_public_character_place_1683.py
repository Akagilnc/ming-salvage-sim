"""#1683：public_character 官印态 ⊥ 物理去向；袁可立新档 location=henan。

active+空 transit+在事/非在朝 由 test_yuan_keli_appointment_no_summon_stays_henan
（原票 tracer）承接；本文件只留种子与 transit 投影主干。
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app


def test_yuan_keli_init_db_location_henan(game):
    db, _state, content = game
    assert content.characters["袁可立"].location == "henan"
    row = db.conn.execute(
        "SELECT location, status FROM characters WHERE name=?", ("袁可立",)
    ).fetchone()
    assert row is not None
    assert row["location"] == "henan"
    # 罢居污染清洗后 offstage，不靠改 active 消矛盾
    assert row["status"] == "offstage"


def _runtime(db, state, content):
    from ming_sim.skills import bind_content as bind_skills_content

    bind_skills_content(content)
    runtime = object.__new__(web_app.WebGame)
    runtime.favorites = set()
    runtime.session = SimpleNamespace(db=db, state=state, content=content)
    return runtime


def test_public_character_projects_transit(game):
    """transit_to → transit_to_label；不泄漏 transit_distance_remaining。"""
    db, state, content = game
    name = "袁崇焕"
    # public_character 从 DB 读 location/transit；status 亦经 DB
    db.conn.execute(
        "UPDATE characters SET status='active', office=?, location=?, transit_to=?, "
        "transit_distance_remaining=? WHERE name=?",
        ("辽东巡抚", "henan", "shandong", 12.5, name),
    )
    db.conn.commit()
    ch = content.characters[name]
    ch.status = "active"
    ch.office = "辽东巡抚"
    ch.location = "henan"
    ch.transit_to = "shandong"

    pub = web_app.WebGame.public_character(_runtime(db, state, content), ch)
    assert pub["location"] == "henan"
    assert pub["location_label"] == "河南"
    assert pub["transit_to"] == "shandong"
    assert pub["transit_to_label"] == "山东"
    assert "transit_distance_remaining" not in pub
