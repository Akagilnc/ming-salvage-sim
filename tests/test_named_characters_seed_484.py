"""#484 R4：named-character 史实档案的 loader/DB 契约。"""

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
    assert hu.office == "原三边总督，革职候勘"
    assert hu.office_type == "督抚"
    assert hu.status == "dismissed"
    assert hu.aliases == ["胡廷宴", "胡总督"]
    assert hu.seed_guilt == {
        "crime": "三边兵变弹压失机，已革职候勘；责任待勘，不预判为可坐重罪",
        "severity": "轻",
    }

    li = chars["李从心"]
    assert "工部尚书" in li.office
    assert "总理河道" in li.office
    assert "都察院" in li.office
    assert li.office_type == "工部"
    assert "工部尚书" in li.aliases
    assert "总理河道" in li.aliases
    assert {"河道治理", "漕运工程"} <= set(li.personal_skills)


def test_r4_hu_tingyan_loader_and_db_preserve_non_holder_seed(read_game):
    db, _state, _content = read_game

    row = db.conn.execute(
        "SELECT office, office_type, status, seed_guilt FROM characters WHERE name=?", ("胡廷宴",)
    ).fetchone()
    assert {key: row[key] for key in ("office", "office_type", "status")} == {
        "office": "原三边总督,革职候勘",
        "office_type": "督抚",
        "status": "dismissed",
    }
    assert __import__("json").loads(row["seed_guilt"]) == _by_name()["胡廷宴"].seed_guilt


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
    assert content.characters["汤若望"].debut_month == 0

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


def test_r6_xu_yingqiu_uses_verified_ministry_line_and_opening_status():
    character = _by_name()["徐应秋"]

    assert character.office == "礼部仪制司主事"
    assert character.office_type == "礼部"
    assert character.status == "active"
    assert character.debut_year == 1627
    assert character.debut_month == 0
    assert character.location == "beizhili"


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
                "intrigue": 50,
                "style": "测试",
                "power_id": "ming",
                "personal_skills": [],
                "seed_guilt": [],
            }],
        },
    )

    with pytest.raises(SystemExit, match="seed_guilt 必须是 JSON 对象"):
        content_module.load_character_content()


def _minimal_character_with_seed_guilt(seed_guilt, *, identity=50):
    return {
        "name": "测试人物",
        "office": "知县",
        "office_type": "地方",
        "faction": "测试派",
        "loyalty": 50,
        "ability": 50,
        "integrity": 50,
        "courage": 50,
        "intrigue": 50,
        "style": "测试",
        "power_id": "ming",
        "personal_skills": [],
        "seed_guilt": seed_guilt,
        "identity": identity,
    }


def _patch_single_character(monkeypatch, character):
    monkeypatch.setattr(
        content_module,
        "load_json_asset",
        lambda _name: {
            "factions": [{"name": "测试派", "satisfaction": 50, "leverage": 50, "agenda": "测试"}],
            "characters": [character],
        },
    )


def test_r5_loader_rejects_nested_seed_guilt_crime_list(monkeypatch):
    _patch_single_character(monkeypatch, _minimal_character_with_seed_guilt({"crime": [], "severity": "无"}))

    with pytest.raises(SystemExit, match="设定字段应为字符串"):
        content_module.load_character_content()


def test_r5_loader_rejects_nested_seed_guilt_severity_object(monkeypatch):
    _patch_single_character(monkeypatch, _minimal_character_with_seed_guilt({"crime": "", "severity": {}}))

    with pytest.raises(SystemExit, match="设定字段应为非空字符串"):
        content_module.load_character_content()


def test_r5_loader_preserves_zero_identity(monkeypatch):
    _patch_single_character(monkeypatch, _minimal_character_with_seed_guilt({"crime": "", "severity": "无"}, identity=0))

    _factions, characters = content_module.load_character_content()

    assert characters["测试人物"].identity == 0
