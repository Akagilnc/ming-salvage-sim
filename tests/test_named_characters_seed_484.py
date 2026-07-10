"""#484 R4：named-character 史实档案的 loader/DB 契约。"""

from __future__ import annotations

import pytest

import ming_sim.content as content_module
from ming_sim.content import load_character_content


def _by_name():
    _, characters = load_character_content()
    return characters


def test_r3_named_characters_load_legal_guilt_and_historical_offices():
    chars = _by_name()

    assert chars["郭允厚"].seed_guilt == {"crime": "交结近侍又次等", "severity": "中"}
    assert chars["李从心"].seed_guilt == {"crime": "交结近侍又次等", "severity": "中"}

    hu = chars["胡廷宴"]
    assert hu.office == "陕西巡抚"
    assert hu.office_type == "地方"
    assert hu.status == "active"
    assert hu.aliases == ["胡廷宴", "胡巡抚"]
    assert hu.seed_guilt == {"crime": "请建魏忠贤生祠", "severity": "轻"}

    li = chars["李从心"]
    assert "工部尚书" in li.office
    assert "总理河道" in li.office
    assert "都察院" in li.office
    assert li.office_type == "工部"
    assert "工部尚书" in li.aliases
    assert "总理河道" in li.aliases
    assert {"河道治理", "漕运工程"} <= set(li.personal_skills)


def test_r4_hu_tingyan_loader_and_db_use_legal_office_type(game):
    db, _state, _content = game

    row = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", ("胡廷宴",)
    ).fetchone()
    assert dict(row) == {"office": "陕西巡抚", "office_type": "地方"}


def test_r4_named_characters_debut_in_historical_order(game):
    db, state, content = game

    assert state.year == 1627
    expected = {
        "张缙彦": ("清涧知县", "地方", 1631, ""),
        "汤若望": ("钦天监历局修历", "礼部", 1630, "beizhili"),
        "李之藻": ("历局修历起复", "礼部", 1629, "beizhili"),
    }
    for name, (office, office_type, debut_year, location) in expected.items():
        character = content.characters[name]
        assert (character.office, character.office_type) == (office, office_type)
        assert character.status == "offstage"
        assert character.debut_year == debut_year
        assert character.location == location
        assert db.get_character_status(name)[0] == "offstage"

    assert db.apply_historical_debuts(state) == []

    state.year, state.period = 1629, 1
    debuted = db.apply_historical_debuts(state)
    assert {"name": "李之藻", "office": "历局修历起复", "faction": "西学"} in debuted
    assert db.get_character_status("李之藻")[0] == "active"

    state.year, state.period = 1630, 4
    debuted = db.apply_historical_debuts(state)
    assert {"name": "汤若望", "office": "钦天监历局修历", "faction": "西学"} in debuted
    assert db.get_character_status("汤若望")[0] == "active"

    state.year, state.period = 1631, 1
    debuted = db.apply_historical_debuts(state)
    assert {"name": "张缙彦", "office": "清涧知县", "faction": "皇党"} in debuted
    assert db.get_character_status("张缙彦")[0] == "active"


def test_r4_loader_rejects_seed_guilt_list(monkeypatch):
    monkeypatch.setattr(
        content_module,
        "load_json_asset",
        lambda _name: {
            "factions": [{"name": "测试派", "satisfaction": 50, "leverage": 50, "agenda": "测试"}],
            "characters": [{
                "name": "测试人物",
                "office": "知县",
                "office_type": "地方",
                "faction": "测试派",
                "loyalty": 50,
                "ability": 50,
                "integrity": 50,
                "courage": 50,
                "style": "测试",
                "power_id": "ming",
                "personal_skills": [],
                "seed_guilt": [],
            }],
        },
    )

    with pytest.raises(SystemExit, match="seed_guilt 必须是 JSON 对象"):
        content_module.load_character_content()
