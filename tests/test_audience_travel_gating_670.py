"""#670 召对 travel-gating 的公开 admission 与 fresh seed 契约。"""

from ming_sim.session import AudienceAdmission, GameSession


def _session(game):
    db, _state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db, sess.content, sess.temporary_characters = db, content, {}
    return sess


def _set_place(game, name, *, location, transit_to=""):
    db, _state, content = game
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to=? WHERE name=?",
        (location, transit_to, name),
    )
    db.conn.commit()
    return content.characters[name]


def test_audience_admission_distinguishes_capital_fresh_and_existing_transit(game):
    sess = _session(game)
    capital = _set_place(game, "毕自严", location="beizhili")
    fresh = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(game, "孙传庭", location="shaanxi", transit_to="henan")

    assert sess.admit_audience(capital).result is AudienceAdmission.IN_CAPITAL
    assert sess.admit_audience(fresh).result is AudienceAdmission.SUMMON_FRESH
    admitted = sess.admit_audience(moving)
    assert admitted.result is AudienceAdmission.SUMMON_IN_TRANSIT
    assert admitted.location == "shaanxi"
    assert admitted.transit_to == "henan"


def test_audience_admission_keeps_blank_fail_open_and_reuses_basic_qualification(game):
    blank = _set_place(game, "毕自严", location="")
    sess = _session(game)
    assert sess.admit_audience(blank).result is AudienceAdmission.IN_CAPITAL

    dead = _set_place(game, "洪承畴", location="shaanxi")
    db, state, _content = game
    db.set_character_status(state, dead.name, "dead", reason="测试")
    decision = sess.admit_audience(dead)
    assert decision.result is None
    assert "已故" in decision.reason


def test_fresh_seed_closes_ticket_670_named_locations(content):
    expected = {
        **{name: "beizhili" for name in "韩爌 张瑞图 来宗道 施凤来 黄立极 王绍徽 毕自严 郭允厚 杨嗣昌 温体仁 钱龙锡 刘鸿训 钱谦益 李标 孙承宗 崔呈秀 王在晋 徐光启 徐应秋 袁可立 周延儒 倪元璐 黄道周 曹化淳 王体乾 王承恩 魏忠贤 田尔耕 许显纯 李若琏 客氏 周皇后 周贵人 田贵妃 袁贵妃 慧妃 懿安皇后 高起潜 孙元化 许誉卿 乔允升".split()},
        "袁崇焕": "guangdong",
        **{name: "shaanxi" for name in "曹文诏 洪承畴 孙传庭 李从心".split()},
        **{name: "liaodong" for name in "祖大寿 赵率教 王之臣 阎鸣泰".split()},
        "满桂": "shanxi", "毛文龙": "dongjiang_area", "卢象升": "nanzhili",
    }
    assert {name: content.characters[name].location for name in expected} == expected
