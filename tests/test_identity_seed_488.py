import json

import pytest

import ming_sim.content as content_module
from ming_sim.assets import load_json_asset
from ming_sim.content import load_character_content
from ming_sim.decree import reload_state_from_db

def test_identity_and_seed_guilt_are_loaded_from_roster_and_seeded(game):
    """DB seed_guilt 与已加载 content 输入结构化全等（不硬编码 crime 散文）。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT faction, identity, seed_guilt FROM characters WHERE name=?",
        ("王承恩",),
    ).fetchone()
    assert row["faction"] == content.characters["王承恩"].faction
    assert row["identity"] == content.characters["王承恩"].identity
    assert json.loads(row["seed_guilt"]) == content.characters["王承恩"].seed_guilt

    温 = db.conn.execute(
        "SELECT faction, identity, seed_guilt FROM characters WHERE name=?", ("温体仁",)
    ).fetchone()
    assert 温["faction"] == content.characters["温体仁"].faction
    assert 温["identity"] == content.characters["温体仁"].identity
    assert json.loads(温["seed_guilt"]) == content.characters["温体仁"].seed_guilt

def test_identity_and_seed_guilt_survive_restore(game):
    db, state, content = game
    before = db.conn.execute(
        "SELECT identity, seed_guilt FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    content.characters["魏忠贤"].identity = 0
    content.characters["魏忠贤"].seed_guilt = {}
    reload_state_from_db(db, state, content=content)
    after = db.conn.execute(
        "SELECT identity, seed_guilt FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    assert dict(after) == dict(before)
    guilt = json.loads(after["seed_guilt"])
    assert guilt == json.loads(before["seed_guilt"])
    assert content.characters["魏忠贤"].identity == before["identity"]
    assert content.characters["魏忠贤"].seed_guilt == guilt

_DIG_7_REQUIRED_SEED_NAMES = {
    "韩爌", "张瑞图", "来宗道", "施凤来", "黄立极", "王绍徽", "毕自严", "杨嗣昌",
    "温体仁", "钱龙锡", "刘鸿训", "钱谦益", "李标", "孙承宗", "崔呈秀", "王在晋",
    "徐光启", "袁可立", "周延儒", "倪元璐", "黄道周", "曹化淳", "王体乾", "王承恩",
    "魏忠贤", "田尔耕", "许显纯", "李若琏", "客氏", "袁崇焕", "曹文诏", "祖大寿",
    "满桂", "赵率教", "王之臣", "毛文龙", "阎鸣泰", "洪承畴", "孙传庭", "卢象升",
    "史可法", "吴三桂", "左良玉", "高起潜", "孙元化", "陈新甲", "傅宗龙", "丁启睿",
    "朱常洵", "朱常瀛", "朱由崧", "懿安皇后", "张延登", "吴甡", "吴昌时", "张凤翼",
    "朱燮元", "邹维琏", "练国事", "李待问", "焦源溥", "曾樱", "余大成", "王尊德",
    "郑芝龙", "何腾蛟", "瞿式耜", "郑成功", "张煌言", "孔有德", "耿仲明", "尚可喜",
    "朱由榔", "朱术桂",
}

def test_required_dig_7_seed_roster_entries_are_persisted(game):
    db, state, content = game
    expected = _DIG_7_REQUIRED_SEED_NAMES | {"郭允厚", "李之藻", "张缙彦", "李从心", "汤若望", "胡廷宴"}
    assert expected <= set(content.characters)
    for name in expected:
        character = content.characters[name]
        row = db.conn.execute(
            "SELECT identity, seed_guilt FROM characters WHERE name=?", (character.name,)
        ).fetchone()
        assert row["identity"] == character.identity
        if character.name in {"高起潜", "吴昌时"}:
            assert row["seed_guilt"] == ""
        else:
            guilt = json.loads(row["seed_guilt"])
            assert set(guilt) == {"crime", "severity"}
            assert guilt["severity"] in {"无", "轻", "中", "重"}

def test_roster_has_no_cross_faction_aliases():
    _, characters = load_character_content()
    by_alias = {}
    for character in characters.values():
        for alias in character.aliases:
            by_alias.setdefault(alias, set()).add(character.faction)
    assert all(len(factions) == 1 for factions in by_alias.values())

def test_roster_rejects_alias_colliding_with_other_faction_name(monkeypatch):
    data = load_json_asset("characters.json")
    data["characters"][0]["aliases"].append("温体仁")
    monkeypatch.setattr(content_module, "load_json_asset", lambda _: data)
    with pytest.raises(SystemExit):
        load_character_content()

def test_roster_rejects_duplicate_canonical_name(monkeypatch):
    data = load_json_asset("characters.json")
    duplicate = json.loads(json.dumps(data["characters"][0]))
    data["characters"].append(duplicate)
    monkeypatch.setattr(content_module, "load_json_asset", lambda _: data)
    with pytest.raises(SystemExit):
        load_character_content()

@pytest.mark.parametrize(
    "field,value",
    [
        ("identity", 101),
        ("seed_guilt", {"crime": "", "severity": "轻"}),
        ("seed_guilt", {"crime": "无", "severity": "未知"}),
    ],
)
def test_seed_schema_rejects_invalid_values(monkeypatch, field, value):
    data = load_json_asset("characters.json")
    data["characters"][0][field] = value
    monkeypatch.setattr(content_module, "load_json_asset", lambda _: data)
    with pytest.raises(SystemExit):
        load_character_content()
