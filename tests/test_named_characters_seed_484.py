"""#484 R3：named-character 史实档案的 loader 契约。"""

from __future__ import annotations

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
    assert hu.office_type == "督抚"
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


def test_r2_late_debut_figures_are_not_present_at_1627(game):
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
