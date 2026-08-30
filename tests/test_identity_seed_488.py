import json

import pytest

import ming_sim.content as content_module
from ming_sim.assets import load_json_asset
from ming_sim.content import load_character_content
from ming_sim.session import _sync_offices_from_db_impl


def test_identity_and_seed_guilt_are_loaded_from_roster_and_seeded(game):
    db, state, content = game
    assert all(0 <= character.intrigue <= 100 for character in content.characters.values())
    assert min(content.characters[name].intrigue for name in ("魏忠贤", "田尔耕", "许显纯")) > max(
        content.characters[name].intrigue for name in ("钱谦益", "黄道周")
    )
    assert {"张惟贤", "周奎"} <= set(content.characters)
    row = db.conn.execute(
        "SELECT faction, identity, seed_guilt, intrigue, defected_from FROM characters WHERE name=?",
        ("王承恩",),
    ).fetchone()
    assert row["faction"] == "皇党"
    assert row["identity"] == 95
    assert json.loads(row["seed_guilt"]) == {"crime": "无", "severity": "无"}
    assert row["intrigue"] == content.characters["王承恩"].intrigue
    assert row["defected_from"] == content.characters["王承恩"].defected_from

    温 = db.conn.execute(
        "SELECT faction, identity, seed_guilt FROM characters WHERE name=?", ("温体仁",)
    ).fetchone()
    assert 温["faction"] == "皇党"
    assert 温["identity"] == 18
    assert json.loads(温["seed_guilt"]) == {
        "crime": "无(品性污点:工心计、枚卜案讦钱谦益以自进、柄国专务逢迎不引正人——《明史》列奸臣传,属品性污点非可坐之现行罪)",
        "severity": "无",
    }


def test_identity_and_seed_guilt_survive_restore(game):
    db, state, content = game
    db.conn.execute(
        "UPDATE characters SET defected_from=? WHERE name=?", ("东林", "魏忠贤")
    )
    before = db.conn.execute(
        "SELECT identity, seed_guilt, intrigue, defected_from FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    content.characters["魏忠贤"].identity = 0
    content.characters["魏忠贤"].intrigue = 0
    content.characters["魏忠贤"].defected_from = None
    content.characters["魏忠贤"].seed_guilt = {}
    _sync_offices_from_db_impl(content, db)
    after = db.conn.execute(
        "SELECT identity, seed_guilt, intrigue, defected_from FROM characters WHERE name=?", ("魏忠贤",)
    ).fetchone()
    assert dict(after) == dict(before)
    guilt = json.loads(after["seed_guilt"])
    assert guilt["severity"] == "重"
    assert content.characters["魏忠贤"].identity == before["identity"]
    assert content.characters["魏忠贤"].seed_guilt == guilt
    assert content.characters["魏忠贤"].intrigue == before["intrigue"]
    assert content.characters["魏忠贤"].defected_from == "东林"


def test_current_schema_rebuilds_missing_roster_member_from_content(tmp_path, content):
    """The current schema rebuilds a missing roster member from content."""
    from ming_sim.db import GameDB

    character = content.characters["王承恩"]
    character.intrigue = 47
    character.defected_from = "司礼监旧党"
    path = tmp_path / "current-schema.db"
    first = GameDB(str(path), content)
    first.seed_static_data()
    first.conn.execute("DELETE FROM character_offices WHERE character_name=?", (character.name,))
    first.conn.execute("DELETE FROM characters WHERE name=?", (character.name,))
    first.conn.commit()
    first.close()

    restored = GameDB(str(path), content)
    inserted = restored.conn.execute(
        "SELECT identity, seed_guilt, intrigue, defected_from FROM characters WHERE name=?",
        (character.name,),
    ).fetchone()
    assert inserted["identity"] == character.identity
    assert json.loads(inserted["seed_guilt"]) == character.seed_guilt
    assert inserted["intrigue"] == character.intrigue
    assert inserted["defected_from"] == character.defected_from
    restored.close()


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
    with pytest.raises(SystemExit, match="温体仁"):
        load_character_content()


def test_roster_rejects_duplicate_canonical_name(monkeypatch):
    data = load_json_asset("characters.json")
    duplicate = json.loads(json.dumps(data["characters"][0]))
    dup_name = duplicate["name"]
    data["characters"].append(duplicate)
    monkeypatch.setattr(content_module, "load_json_asset", lambda _: data)
    with pytest.raises(SystemExit, match=dup_name):
        load_character_content()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("identity", 101, "identity"),
        ("intrigue", 101, "intrigue"),
        ("defected_from", {}, "defected_from"),
        ("seed_guilt", {"crime": "", "severity": "轻"}, "crime"),
        ("seed_guilt", {"crime": "无", "severity": "未知"}, "severity"),
    ],
)
def test_seed_schema_rejects_invalid_values(monkeypatch, field, value, match):
    data = load_json_asset("characters.json")
    data["characters"][0][field] = value
    monkeypatch.setattr(content_module, "load_json_asset", lambda _: data)
    with pytest.raises(SystemExit, match=match):
        load_character_content()
