"""#1683：public_character 官印态 ⊥ 物理去向；袁可立新档 location=henan。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import web_app
from ming_sim.content import GameContent


def test_yuan_keli_seed_location_is_henan():
    """罢居睢州 ∈ 河南；新档 seed location 不得再写北直隶。"""
    raw = json.loads(
        (Path(__file__).resolve().parents[1] / "content/characters.json").read_text(
            encoding="utf-8"
        )
    )
    yuan = next(c for c in raw["characters"] if c["name"] == "袁可立")
    assert yuan["location"] == "henan"

    content = GameContent.load()
    assert content.characters["袁可立"].location == "henan"


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


def test_public_character_active_not_zaichao_and_projects_place(game):
    """active + 外地 location + 空 transit → status_label 非「在朝」；含 location/transit 键。"""
    db, state, content = game
    # 用既有在册人物造「已授官但未启程、人在河南」态
    name = "袁崇焕"
    db.conn.execute(
        "UPDATE characters SET status='active', office=?, location=?, transit_to='', "
        "transit_distance_remaining=NULL WHERE name=?",
        ("巡抚登莱", "henan", name),
    )
    db.conn.commit()
    ch = content.characters[name]
    ch.status = "active"
    ch.office = "巡抚登莱"
    ch.location = "henan"
    ch.transit_to = ""

    pub = web_app.WebGame.public_character(_runtime(db, state, content), ch)
    assert pub["status"] == "active"
    assert pub["status_label"] != "在朝"
    assert pub["status_label"] == "在事"
    assert pub["location"] == "henan"
    assert pub["location_label"] == "河南"
    assert pub["transit_to"] == ""
    assert pub.get("transit_to_label", "") == ""
    assert "transit_distance_remaining" not in pub


def test_public_character_projects_transit(game):
    db, state, content = game
    name = "袁崇焕"
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
    assert pub["status_label"] != "在朝"
    assert pub["location"] == "henan"
    assert pub["location_label"] == "河南"
    assert pub["transit_to"] == "shandong"
    assert pub["transit_to_label"] == "山东"
    assert "transit_distance_remaining" not in pub
