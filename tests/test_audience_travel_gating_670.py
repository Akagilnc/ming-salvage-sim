"""#670 召对 travel-gating 的公开 admission 与 fresh seed 契约。"""

from ming_sim.session import AudienceAdmission, GameSession
from ming_sim import audience_night as an
from ming_sim.decree import force_transit_arrivals
from ming_sim.simulation import build_simulator_payload


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


def test_in_transit_summon_origin_is_idempotent_and_restorable(game):
    db, state, _content = game
    night_id = int(an.open_night(db, state)["id"])

    first = an.record_summon_in_transit(
        db, night_id, "洪承畴", origin_id="command:42",
    )
    again = an.record_summon_in_transit(
        db, night_id, "洪承畴", origin_id="command:42",
    )

    assert again == first
    assert an.list_unsettled_summons(db) == [{
        "entry_id": first,
        "night_id": night_id,
        "person_name": "洪承畴",
        "origin_id": "command:42",
        "kind": "in_transit",
    }]
    # The projection is rebuilt exclusively from the durable story ledger.
    assert an.list_unsettled_summons(db) == an.list_unsettled_summons(db)

    assert an.settle_summon_origin(db, "command:42") is True
    assert an.settle_summon_origin(db, "command:42") is False
    assert an.list_unsettled_summons(db) == []


def test_fresh_summon_origin_is_idempotent_and_projects_kind(game):
    db, state, _content = game
    night_id = int(an.open_night(db, state)["id"])

    first = an.record_summon_fresh(
        db, night_id, "洪承畴", origin_id="command:43",
    )
    again = an.record_summon_fresh(
        db, night_id, "洪承畴", origin_id="command:43",
    )

    assert again == first
    assert an.list_unsettled_summons(db) == [{
        "entry_id": first,
        "night_id": night_id,
        "person_name": "洪承畴",
        "origin_id": "command:43",
        "kind": "fresh",
    }]


def test_fresh_summon_departs_via_canonical_applier_only_when_night_closes(game):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_fresh(db, night_id, person.name, origin_id="command:close-1")

    before = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (before["location"], before["transit_to"]) == ("shaanxi", "")

    an.close_night(db, state, night_id=night_id, content=content)

    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    assert an.list_unsettled_summons(db) == []

    # Closed-night replay is a no-op and cannot reset the canonical departure clock.
    started = db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (person.name,)
    ).fetchone()["transit_start_turn"]
    assert an.close_night(db, state, night_id=night_id, content=content)["already"] is True
    assert db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (person.name,)
    ).fetchone()["transit_start_turn"] == started


def test_monthly_judge_receives_arrived_unsettled_summon_facts(game):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi", transit_to="henan")
    db.conn.execute(
        "UPDATE characters SET transit_start_turn=0 WHERE name=?", (person.name,)
    )
    db.conn.commit()
    night_id = int(an.open_night(db, state)["id"])
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id="command:arrived-1",
    )

    assert force_transit_arrivals(db, state, content) == [
        {"name": person.name, "location": "henan"}
    ]
    payload = build_simulator_payload(state, db, "", "")

    assert payload["unsettled_arrived_summons"] == [{
        "person_name": person.name,
        "original_destination": "henan",
        "origin_id": "command:arrived-1",
        "source_entry_id": entry_id,
        "required_fact": "抵原地后续赴京",
    }]


def test_arrived_summon_settles_only_after_canonical_applier_success(game):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="henan")
    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_in_transit(
        db, night_id, person.name, origin_id="command:continue-1",
    )

    # Judge/extractor failure (no accepted person change) preserves the durable retry.
    assert an.settle_applied_arrived_summons(db, {}) == []
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [
        "command:continue-1"
    ]

    from ming_sim.issues import apply_score_extraction
    applied = apply_score_extraction(db, state, {"人物变更": [{
        "name": person.name, "动作": "行止", "transit_to": "beizhili",
        "origin_ref": "盘面自发",
    }]}, content=content)

    assert an.settle_applied_arrived_summons(db, applied) == ["command:continue-1"]
    assert an.list_unsettled_summons(db) == []
    assert an.settle_applied_arrived_summons(db, applied) == []


def test_fresh_seed_closes_ticket_670_named_locations(content):
    expected = {
        **{name: "beizhili" for name in "韩爌 张瑞图 来宗道 施凤来 黄立极 王绍徽 毕自严 郭允厚 杨嗣昌 温体仁 钱龙锡 刘鸿训 钱谦益 李标 孙承宗 崔呈秀 王在晋 徐光启 徐应秋 袁可立 周延儒 倪元璐 黄道周 曹化淳 王体乾 王承恩 魏忠贤 田尔耕 许显纯 李若琏 客氏 周皇后 周贵人 田贵妃 袁贵妃 慧妃 懿安皇后 高起潜 孙元化 许誉卿 乔允升".split()},
        "袁崇焕": "guangdong",
        **{name: "shaanxi" for name in "曹文诏 洪承畴 孙传庭 李从心".split()},
        **{name: "liaodong" for name in "祖大寿 赵率教 王之臣 阎鸣泰".split()},
        "满桂": "shanxi", "毛文龙": "dongjiang_area", "卢象升": "nanzhili",
    }
    assert {name: content.characters[name].location for name in expected} == expected
