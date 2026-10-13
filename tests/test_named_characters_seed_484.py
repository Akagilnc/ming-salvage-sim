"""#484 R4：named-character 史实档案的 loader/DB 契约。"""


import ming_sim.content as content_module
from ming_sim.assets import load_json_asset
from ming_sim.content import load_character_content


def _by_name():
    _, characters = load_character_content()
    return characters


def test_r3_named_characters_load_legal_guilt_and_historical_offices():
    """loader 输出与 characters.json 已加载输入结构化保真（crime/severity 全等，不硬编码文句）。"""
    chars = _by_name()
    raw_items = load_json_asset("characters.json")["characters"]
    raw_by_name = {str(item["name"]): item for item in raw_items}

    def _expected_guilt(name: str) -> dict:
        raw = raw_by_name[name].get("seed_guilt") or {}
        return {
            "crime": str(raw.get("crime") or "").strip(),
            "severity": str(raw.get("severity") or "无").strip(),
        }

    for name in ("郭允厚", "李从心", "胡廷宴"):
        assert chars[name].seed_guilt == _expected_guilt(name)

    hu = chars["胡廷宴"]
    # ADR 0009：离事职名分必清；罪由走 seed_guilt，不挂现职。
    assert hu.office == ""
    assert hu.office_type == "督抚"
    assert hu.status == "dismissed"
    assert hu.aliases == ["胡廷宴", "胡总督"]

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
        "office": "",
        "office_type": "督抚",
        "status": "dismissed",
    }
    assert __import__("json").loads(row["seed_guilt"]) == _by_name()["胡廷宴"].seed_guilt


def test_r4_named_characters_debut_in_historical_order(tmp_path, content):
    """offstage 登场预备：职名分空 office（ADR 0009 / #1843 名分）；office_type/debut 元数据保留。
    登场名分来自显式 content.debut_office，经过 GameSession sync 写入库并出现在登场事实里。"""
    from ming_sim.models import LLMConfig
    from ming_sim.content import GameContent
    from ming_sim.session import GameSession

    db_path = str(tmp_path / "game_r4.db")
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    session = GameSession(db_path=db_path, llm_config=cfg, content=content, start_ym="1627.01")
    try:
        db = session.db
        state = session.state

        assert state.year == 1627
        expected = {
            "张缙彦": ("地方", 1631, "", "皇党"),
            "汤若望": ("礼部", 1630, "beizhili", "西学"),
            "李之藻": ("礼部", 1629, "beizhili", "西学"),
        }
        for name, (office_type, debut_year, location, _faction) in expected.items():
            character = session.content.characters[name]
            assert character.office == ""
            assert character.office_type == office_type
            assert character.status == "offstage"
            assert character.debut_year == debut_year
            assert character.location == location
            assert db.characters.get_character_status(name)[0] == "offstage"
        assert session.content.characters["汤若望"].debut_month == 0

        assert db.apply_historical_debuts(state) == []
        arrivals = {
            (1628, 1): [("韩一良", "户科给事中", "中立")],
            (1629, 1): [("李之藻", "南京太仆寺少卿", "西学")],
            (1630, 4): [("汤若望", "历局修历", "西学"),
                        ("左良玉", "辽东车右营都司", "军队")],
            (1631, 1): [("张缙彦", "清涧知县", "皇党"),
                        ("吴三桂", "都督指挥", "军队")],
            (1639, 1): [("傅宗龙", "四川巡抚", "军队")],
            (1640, 1): [("陈新甲", "兵部尚书", "军队")],
        }
        names = [name for batch in arrivals.values() for name, _, _ in batch]
        archives = db.conn.execute(
            "SELECT character_name FROM character_offices"
        ).fetchall()
        assert not set(names).intersection(row["character_name"] for row in archives)

        # 经过真实关库/恢复入口，避免仅以未同步的 content 夹具证明登场。
        session.close()
        session = GameSession(db_path=db_path, llm_config=cfg, content=GameContent.load())
        db, state = session.db, session.state
        for (year, month), batch in arrivals.items():
            state.year, state.period = year, month
            db.reign.save_game_state(state)
            session.begin_turn()
            debuted = session.debuts_this_turn
            state = session.state
            for name, office, faction in batch:
                assert office == session.content.characters[name].debut_office
                assert {"name": name, "office": office, "faction": faction} in debuted
                row = db.characters.row(name, fields="office")
                assert row["office"] == office
                assert db.characters.get_character_status(name)[0] == "active"
    finally:
        session.close()


def test_r6_xu_yingqiu_uses_verified_ministry_line_and_opening_status():
    character = _by_name()["徐应秋"]

    assert character.office == "礼部仪制司主事"
    assert character.office_type == "礼部"
    assert character.status == "active"
    assert character.debut_year == 1627
    assert character.debut_month == 0
    assert character.location == "beizhili"


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


def test_r5_loader_preserves_zero_identity(monkeypatch):
    _patch_single_character(monkeypatch, _minimal_character_with_seed_guilt({"crime": "", "severity": "无"}, identity=0))

    _factions, characters = content_module.load_character_content()

    assert characters["测试人物"].identity == 0
