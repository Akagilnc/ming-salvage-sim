"""#484 R2：七条 named-character 史实修复的档案契约。"""

from __future__ import annotations

import json
from pathlib import Path


def _by_name():
    path = Path(__file__).resolve().parents[1] / "content" / "characters.json"
    return {item["name"]: item for item in json.loads(path.read_text(encoding="utf-8"))["characters"]}


def test_r2_named_characters_keep_reverse_case_guilt_and_historical_offices():
    chars = _by_name()

    assert chars["郭允厚"]["seed_guilt"] == {
        "crime": "交结近侍又次等",
        "severity": "次等",
    }
    assert chars["李从心"]["seed_guilt"] == {
        "crime": "交结近侍又次等",
        "severity": "次等",
    }

    hu = chars["胡廷宴"]
    assert hu["office"] == "陕西巡抚"
    assert hu["office_type"] == "督抚"
    assert hu["status"] == "active"
    assert hu["aliases"] == ["胡廷宴", "胡巡抚"]
    assert "魏忠贤生祠" in hu["seed_guilt"]["crime"]

    li = chars["李从心"]
    assert "工部尚书" in li["office"]
    assert "总理河道" in li["office"]
    assert "都察院" in li["office"]
    assert li["office_type"] == "工部"
    assert "工部尚书" in li["aliases"]
    assert "总理河道" in li["aliases"]
    assert {"河道治理", "漕运工程"} <= set(li["personal_skills"])


def test_r2_late_debut_figures_are_not_present_at_1627(game):
    db, state, content = game

    assert state.year == 1627
    expected = {
        "张缙彦": ("举人", "未仕", 1631),
        "汤若望": ("西安传教士", "外来", 1630),
    }
    for name, (office, office_type, debut_year) in expected.items():
        character = content.characters[name]
        assert (character.office, character.office_type) == (office, office_type)
        assert character.status == "offstage"
        assert character.debut_year == debut_year
        assert db.get_character_status(name)[0] == "offstage"

    assert db.apply_historical_debuts(state) == []
